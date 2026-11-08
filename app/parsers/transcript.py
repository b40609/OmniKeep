"""What is said in a video: its subtitles, else its audio transcribed on this machine.

The common order (video summarizers, transcript tools): the uploader's subtitles first, then the
site's automatic captions in the video's own language, and only when there are none, the audio
downloaded and transcribed with faster-whisper. Before 2026-11-09 a YouTube video was analysed from
its title and description alone whenever no Gemini video connection was set (41 of 44 saved videos).

A transcript that could not be read is reported as "failed" with a reason, never replaced by the
description: the pipeline then keeps the item as a fetch failure and app/refetch.py tries again. A
video whose audio has no speech is "no_speech", which is an answer, not a failure.
"""
import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

logger = logging.getLogger("omnikeep.transcript")

TRANSCRIPT_MISSING = "（影片逐字稿這次沒有讀到，OmniKeep 稍後會自動再試）"
MAX_STT_SECONDS = 2 * 3600  # longer audio is transcribed up to here (float32 16 kHz: about 460 MB)
MAX_CHARS = 60000  # kept in content_raw; the analysis prompt takes less
PREFERRED_LANGS = ("zh-Hant", "zh-TW", "zh-HK", "zh", "zh-Hans", "zh-CN", "en", "en-US", "en-GB", "ja", "ko")
TRACK_EXTS = ("json3", "vtt", "srt")
SOURCE_LABELS = {"subtitles": "上傳者字幕", "auto": "平台自動字幕", "stt": "本機語音轉錄"}

_stt_lock = threading.Lock()  # one transcription at a time on the GPU


@dataclass
class Transcript:
    status: str  # "ok" | "no_speech" | "failed"
    text: str = ""
    source: str = ""  # key of SOURCE_LABELS
    language: str = ""
    reason: str = ""
    truncated: bool = False

    def section(self) -> str:
        """The block appended to content_raw."""
        if self.status == "ok":
            cut = f"（只轉錄前 {MAX_STT_SECONDS // 3600} 小時）" if self.truncated else ""
            lang = f"，{self.language}" if self.language else ""
            return f"## 影片逐字稿（{SOURCE_LABELS.get(self.source, self.source)}{lang}）{cut}\n{self.text}"
        if self.status == "no_speech":
            return "## 影片逐字稿\n（影片沒有字幕，音訊裡也沒有辨識到口語內容）"
        return f"## 影片逐字稿\n{TRANSCRIPT_MISSING}\n原因：{self.reason}"


def _short(exc: BaseException) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).replace("ERROR: ", "").strip()
    text = re.sub(r"https?://\S+", "", text)
    return (text.splitlines() or [type(exc).__name__])[0][:160] or type(exc).__name__


# ── subtitles ──────────────────────────────────────────────────────────────────

def _base(lang: str) -> str:
    return lang.split("-")[0].lower()


def pick_track(info: Dict[str, Any]) -> Optional[Tuple[str, str, Dict[str, Any]]]:
    """(source, language, format entry) of the best text track, or None.

    The uploader's subtitles: the video's own language first, then Chinese, English and so on.
    Automatic captions: only the speech recognition of the video's own language ("xx-orig", or the
    language yt-dlp reports); the other languages are machine translations of it.
    """
    original = (info.get("language") or "").strip()
    manual = {k: v for k, v in (info.get("subtitles") or {}).items() if v and k not in ("live_chat", "rechat")}
    auto = {k: v for k, v in (info.get("automatic_captions") or {}).items() if v}

    def best_format(formats: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        for ext in TRACK_EXTS:
            for fmt in formats:
                if fmt.get("ext") == ext and fmt.get("url"):
                    return fmt
        return None

    manual_order = []
    if original:
        manual_order += [k for k in manual if k == original] + [k for k in manual if _base(k) == _base(original)]
    manual_order += [k for pref in PREFERRED_LANGS for k in manual if k == pref]
    manual_order += list(manual)
    for lang in dict.fromkeys(manual_order):
        fmt = best_format(manual[lang])
        if fmt:
            return "subtitles", lang, fmt

    auto_order = [k for k in auto if k.endswith("-orig")]
    if original:
        auto_order += [k for k in auto if k == original]
    for lang in dict.fromkeys(auto_order):
        fmt = best_format(auto[lang])
        if fmt:
            return "auto", lang.removesuffix("-orig"), fmt
    return None


def _cjk_join(parts: List[str]) -> str:
    out = ""
    for part in parts:
        if out and not (re.search(r"[　-鿿＀-￯]$", out) and re.match(r"[　-鿿＀-￯]", part)):
            out += " "
        out += part
    return out


def track_text(body: str, ext: str) -> str:
    """Plain text of a json3 / WebVTT / SRT subtitle file, without timings, tags or rolling repeats."""
    lines: List[str] = []
    if ext == "json3":
        try:
            events = json.loads(body).get("events") or []
        except ValueError:
            return ""
        for event in events:
            text = "".join(seg.get("utf8", "") for seg in event.get("segs") or []).strip()
            if text:
                lines.extend(t.strip() for t in text.splitlines() if t.strip())
    else:
        for raw in body.splitlines():
            line = raw.strip()
            if (not line or line == "WEBVTT" or "-->" in line or line.isdigit()
                    or re.match(r"^(Kind|Language|NOTE|STYLE|REGION)\b", line)):
                continue
            line = re.sub(r"<[^>]+>", "", line).strip()
            if line:
                lines.append(line)
    deduped: List[str] = []
    for line in lines:  # automatic captions repeat the previous line as the next one starts
        if not deduped or line != deduped[-1]:
            deduped.append(line)
    return _cjk_join(deduped)


# ── yt-dlp ─────────────────────────────────────────────────────────────────────

@contextmanager
def _session(url: str) -> Iterator[Dict[str, Any]]:
    from app.parsers.cookie_manager import ytdlp_cookie_opts
    with ytdlp_cookie_opts(url) as opts:
        yield opts


def _with_session(url: str, opts: Dict[str, Any], run: Callable[[Any], Any]) -> Any:
    """run(ydl) with this site's cookies, then once more without them (an expired session can fail
    where an anonymous request works)."""
    from app.parsers.media_network import PublicYoutubeDL
    with _session(url) as cookie_opts:
        try:
            with PublicYoutubeDL({**opts, **cookie_opts}) as ydl:
                return run(ydl)
        except Exception as exc:
            if not cookie_opts:
                raise
            logger.info("[Transcript] with the session failed (%s); trying without it", _short(exc))
    with PublicYoutubeDL(opts) as ydl:
        return run(ydl)


BASE_OPTS = {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 15, "noplaylist": True}


def extract_info(url: str) -> Dict[str, Any]:
    return _with_session(url, {**BASE_OPTS, "skip_download": True},
                         lambda ydl: ydl.extract_info(url, download=False)) or {}


def _read_track(url: str, fmt: Dict[str, Any]) -> str:
    def run(ydl):
        return ydl.urlopen(fmt["url"]).read().decode("utf-8", "replace")
    return track_text(_with_session(url, dict(BASE_OPTS), run), fmt.get("ext", ""))


def _download_audio(url: str, folder: str) -> str:
    opts = {**BASE_OPTS, "format": "bestaudio[abr<=96]/worstaudio/bestaudio/best",
            "outtmpl": os.path.join(folder, "audio.%(ext)s"), "overwrites": True}
    _with_session(url, opts, lambda ydl: ydl.extract_info(url, download=True))
    found = [os.path.join(folder, f) for f in os.listdir(folder) if f.startswith("audio.") and not f.endswith(".part")]
    if not found:
        raise RuntimeError("音訊沒有下載下來")
    return found[0]


# ── speech to text ─────────────────────────────────────────────────────────────

def stt_available() -> bool:
    from app.parsers.reel import get_local_whisper_model
    return get_local_whisper_model() is not None


def transcribe_file(path: str, max_seconds: int = MAX_STT_SECONDS) -> str:
    """Text spoken in an audio / video file ("" when there is no speech). Raises when it cannot run."""
    import numpy as np
    from app.parsers.reel import get_local_whisper_model
    model = get_local_whisper_model()
    if model is None:
        raise RuntimeError("本機語音轉文字（faster-whisper）沒有裝")
    cmd = ["ffmpeg", "-y", "-protocol_whitelist", "file,pipe", "-t", str(max_seconds), "-i", path,
           "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"]
    proc = subprocess.run(cmd, capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError("ffmpeg 解不開音訊：" + proc.stderr.decode("utf-8", "replace").strip()[-160:])
    audio = np.frombuffer(proc.stdout, dtype=np.float32)
    if len(audio) < 8000:
        return ""
    with _stt_lock:
        segments, _ = model.transcribe(audio, beam_size=5, vad_filter=True)
        parts = [s.text.strip() for s in segments if s.text.strip()]
    text = _cjk_join(parts)
    return text if spoken(text) else ""


# What Whisper writes for music, noise or silence (seen 2026-11-09: a music clip on X became "You").
HALLUCINATIONS = re.compile(
    r"(?i)^(you|thank you|thanks for watching|請不吝點贊.*|字幕由.*提供|謝謝觀看|謝謝大家|ご視聴ありがとうございました|music|音樂)$")


def spoken(text: str) -> bool:
    """False for an empty transcript or one that is only a known hallucination of Whisper."""
    words = [w for w in re.split(r"[\s。，、！？.,!?…]+", text) if w]
    if not words:
        return False
    if all(HALLUCINATIONS.match(w) for w in words) or HALLUCINATIONS.match(" ".join(words)):
        return False
    return len(re.sub(r"[\s\W_]+", "", text)) >= 6


# ── the transcript ─────────────────────────────────────────────────────────────

def _transcript_sync(url: str, info: Optional[Dict[str, Any]]) -> Transcript:
    if not info or not any(k in info for k in ("subtitles", "automatic_captions")):
        try:
            info = extract_info(url)
        except Exception as exc:
            return Transcript("failed", reason=f"讀不到影片資訊：{_short(exc)}")
    track = pick_track(info)
    if track:
        source, lang, fmt = track
        try:
            text = _read_track(url, fmt)
        except Exception as exc:
            logger.warning("[Transcript] %s: subtitles %s could not be read (%s)", url, lang, _short(exc))
            text = ""
        if len(text) >= 20:
            return Transcript("ok", text[:MAX_CHARS], source, lang)
    if info.get("is_live") or info.get("live_status") in ("is_live", "is_upcoming"):
        return Transcript("failed", reason="直播還沒結束")
    if not stt_available():
        return Transcript("failed", reason="影片沒有字幕，本機語音轉文字（faster-whisper）也沒有裝")
    folder = tempfile.mkdtemp(prefix="omni_audio_")
    try:
        try:
            audio = _download_audio(url, folder)
        except Exception as exc:
            return Transcript("failed", reason=f"音訊沒有下載到：{_short(exc)}")
        try:
            text = transcribe_file(audio)
        except Exception as exc:
            return Transcript("failed", reason=f"語音轉文字失敗：{_short(exc)}")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if not text.strip():
        return Transcript("no_speech")
    duration = float(info.get("duration") or 0)
    return Transcript("ok", text[:MAX_CHARS], "stt", info.get("language") or "",
                      truncated=duration > MAX_STT_SECONDS)


async def get_transcript(url: str, info: Optional[Dict[str, Any]] = None) -> Transcript:
    """The transcript of a video page that yt-dlp can open. info: yt-dlp's info, if already fetched."""
    result = await asyncio.to_thread(_transcript_sync, url, info)
    if result.status == "ok":
        logger.info("[Transcript] %s: %s chars from %s", url, len(result.text), result.source)
    else:
        logger.warning("[Transcript] %s: %s %s", url, result.status, result.reason)
    return result


async def attached_video_section(media_url: str) -> str:
    """The transcript block for a video attached to a post (X, Threads), "" when it has no speech.

    The post's own text is the main content there, so a transcript that fails is noted in the text
    instead of turning the post into a fetch failure."""
    if not media_url:
        return ""
    result = await get_transcript(media_url)
    if result.status == "ok":
        return "\n\n" + result.section()
    if result.status == "no_speech":
        return ""
    return f"\n\n## 影片逐字稿\n（附帶的影片這次沒有轉出逐字稿：{result.reason}）"
