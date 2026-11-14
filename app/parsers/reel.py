import gc
import os
import re
import shutil
import asyncio
import importlib.util
import logging
import subprocess
import tempfile
import time
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
from urllib.parse import urlsplit
from app.network import validate_url
from app.parsers.media_network import PublicYoutubeDL

from app.providers import get_primary_provider, get_gemini_provider, has_video_provider
from app.providers.gemini import _generate_content
from app import ai_usage
from app.parsers.web import parse_facebook_page
from app.parsers.cookie_manager import ytdlp_cookie_opts
from app.config import settings

logger = logging.getLogger("omnikeep.reel")

_local_whisper_model = None  # the loaded WhisperModel; False once local STT turned out unusable
_local_whisper_name = ""  # which one: BREEZE_STT_MODEL, GPU_STT_MODEL or CPU_STT_MODEL
_force_cpu_stt = False
_breeze_off_until = 0.0  # time.monotonic() until which Breeze is skipped: it could not be loaded (offline ...)
BREEZE_RETRY_SECONDS = 3600
_cuda_dlls_added = False
# Which model, measured 2026-11-09 on 4 Taiwanese YouTube videos (40 min, the uploaders' subtitles as
# reference): Breeze-ASR-25 (MediaTek Research, Whisper large-v2 tuned on Taiwanese Mandarin and
# Mandarin-English code-switching) 7.7% mixed error rate against 9.4% for large-v3-turbo, Traditional
# output (turbo: 24% Simplified), 7.4x real time, about 4.5 GB VRAM. On an English talk turbo was
# better (6.0% against 7.0%) and Breeze is not trained on Japanese, Korean and so on. So on a GPU:
# Chinese or an unknown language -> Breeze, a language the video declares otherwise -> turbo; on a
# CPU small (Breeze is large-v2 sized, far too slow there). tiny got Mandarin wrong too often.
BREEZE_STT_MODEL = "breeze-asr-25"
# A CTranslate2 conversion of MediaTek-Research/Breeze-ASR-25 (Apache-2.0); faster-whisper cannot load
# the original. Pinned: model.bin is data, not code, but a moved branch would change what is loaded.
BREEZE_REPO = "shdennlin/breeze-asr-25-ct2"
BREEZE_REVISION = "70660216b01a6f6b7b8c5690767a4763df61755f"
BREEZE_VARIANT = "float16"
GPU_STT_MODEL = "large-v3-turbo"  # about 1.6 GB download, 2 GB VRAM
CPU_STT_MODEL = "small"
Segment = Tuple[Any, Any, str]  # start and end in seconds, text


class ReelUnavailableError(RuntimeError):
    """The reel could not be retrieved for video analysis."""


GENERIC_REEL_TITLES = {"", "facebook", "instagram", "video", "reel", "reels", "facebook watch"}


def session_lost_metadata(info: Optional[Dict[str, Any]]) -> bool:
    """yt-dlp got the clip but not the post: a bare site name for a title and no description."""
    info = info or {}
    title = (info.get("title") or "").strip().lower()
    return title in GENERIC_REEL_TITLES and not (info.get("description") or "").strip()


def is_empty_reel_metadata(item: Dict[str, Any]) -> bool:
    """Recognize legacy placeholder entries mistakenly saved as reel analyses."""
    return (
        is_video_reel_url(item.get("url") or "")
        and (item.get("content_raw") or "").strip()
        in (
            "（Facebook 貼文未提供公開文字說明）",
            "（Instagram 貼文未提供公開文字說明）",
        )
    )


async def _run_thread(func):
    """Keep temporary media alive until a cancelled native operation finishes."""
    task = asyncio.create_task(asyncio.to_thread(func))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


def _preload_cuda_dlls() -> None:
    """Register CUDA 12 runtime DLLs shipped via pip wheels (nvidia-cublas-cu12 /
    nvidia-cudnn-cu12). ctranslate2 loads cublas64_12.dll lazily at first inference
    and only searches the process DLL path — without this, GPU init appears to
    succeed but every transcription dies with 'cublas64_12.dll not found'."""
    global _cuda_dlls_added
    if _cuda_dlls_added:
        return  # once: PATH would grow with every model load
    _cuda_dlls_added = True
    import site
    seen = set()
    for sp in (*site.getsitepackages(), site.getusersitepackages()):
        if not sp or sp in seen:
            continue
        seen.add(sp)
        for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin", "nvidia/cuda_nvrtc/bin"):
            p = os.path.join(sp, sub)
            if os.path.isdir(p):
                try:
                    os.add_dll_directory(p)
                except Exception:
                    pass
                os.environ["PATH"] = p + os.pathsep + os.environ.get("PATH", "")

def chinese_or_unknown(language: str) -> bool:
    """Breeze's languages: Chinese, or nothing declared (Reels, X and Threads clips, most uploads)."""
    return (language or "").split("-")[0].strip().lower() in ("", "zh", "cmn")


def _cuda() -> bool:
    if _force_cpu_stt:
        return False
    _preload_cuda_dlls()
    try:
        import ctranslate2
        return ctranslate2.get_cuda_device_count() > 0
    except Exception as e:
        logger.warning(f"[Local STT] CUDA init failed, falling back to CPU: {e}")
        return False


def _breeze_path() -> str:
    """The pinned Breeze CT2 folder in the Hugging Face cache (downloaded the first time, 2.9 GB)."""
    from huggingface_hub import snapshot_download
    root = snapshot_download(BREEZE_REPO, revision=BREEZE_REVISION, allow_patterns=[f"{BREEZE_VARIANT}/*"])
    return os.path.join(root, BREEZE_VARIANT)


def _build(name: str):
    from faster_whisper import WhisperModel
    if name == CPU_STT_MODEL:
        threads = min(8, max(2, os.cpu_count() or 4))
        return WhisperModel(CPU_STT_MODEL, device="cpu", compute_type="int8", cpu_threads=threads)
    path = _breeze_path() if name == BREEZE_STT_MODEL else GPU_STT_MODEL
    return WhisperModel(path, device="cuda", compute_type="float16")


def _unload() -> None:
    """Free the loaded model's VRAM before another is loaded: the GPU is shared with Ollama."""
    global _local_whisper_model, _local_whisper_name
    old, _local_whisper_model, _local_whisper_name = _local_whisper_model, None, ""
    if old:
        try:
            old.model.unload_model()
        except Exception:
            pass
        del old
        gc.collect()


def get_local_whisper_model(language: str = ""):
    """The faster-whisper model for this language, loaded on first use; None when local STT is off.

    One model in memory at a time: asking for the other one unloads the first. language is what the
    video declares (yt-dlp's "language"), "" when unknown."""
    global _local_whisper_model, _local_whisper_name, _breeze_off_until, _force_cpu_stt
    from app.parsers.transcript import _stt_lock
    with _stt_lock:
        if _local_whisper_model is False:
            return None
        if _local_whisper_model is None and importlib.util.find_spec("faster_whisper") is None:
            # Optional (requirements-stt.txt): Reels fall back to cloud transcription.
            logger.warning("[Local STT] faster-whisper is not installed; local transcription is off "
                           "(pip install -r requirements-stt.txt)")
            _local_whisper_model = False
            return None
        if _cuda():
            breeze_ok = time.monotonic() >= _breeze_off_until
            wanted = BREEZE_STT_MODEL if chinese_or_unknown(language) and breeze_ok else GPU_STT_MODEL
        else:
            wanted = CPU_STT_MODEL
        if _local_whisper_model is not None and _local_whisper_name == wanted:
            return _local_whisper_model
        _unload()
        order = {BREEZE_STT_MODEL: [BREEZE_STT_MODEL, GPU_STT_MODEL, CPU_STT_MODEL],
                 GPU_STT_MODEL: [GPU_STT_MODEL, CPU_STT_MODEL]}.get(wanted, [CPU_STT_MODEL])
        for name in order:
            try:
                model = _build(name)
            except Exception as e:
                # Breeze not downloadable (offline, Hugging Face down ...): turbo, never no transcript.
                logger.warning("[Local STT] %s could not be loaded (%s)%s", name, e,
                               "; large-v3-turbo for the next hour" if name == BREEZE_STT_MODEL else "")
                if name == BREEZE_STT_MODEL:
                    _breeze_off_until = time.monotonic() + BREEZE_RETRY_SECONDS
                elif name == GPU_STT_MODEL:
                    _force_cpu_stt = True  # the GPU itself does not work: do not retry it on every video
                continue
            _local_whisper_model, _local_whisper_name = model, name
            logger.info("[Local STT] Loaded faster-whisper %s on %s", name, "CPU" if name == CPU_STT_MODEL else "CUDA GPU")
            return model
        _local_whisper_model = False
        return None


def _whisper_language(language: str) -> Optional[str]:
    """The declared language as Whisper's code, None to let it detect."""
    base = (language or "").split("-")[0].strip().lower()
    try:
        from faster_whisper.tokenizer import _LANGUAGE_CODES
    except Exception:
        return None
    return base if base in _LANGUAGE_CODES else None


def transcribe_audio(audio: np.ndarray, language: str = "", **options) -> List[Segment]:
    """Speech in 16 kHz mono float32 audio as (start, end, text), one transcription at a time.

    Breeze detects the language itself (as measured); turbo and small get the declared one. Chinese
    from them is turned into Taiwan Traditional (OpenCC s2twp): turbo wrote 24% Simplified."""
    from app.parsers.transcript import _stt_lock, to_traditional
    with _stt_lock:
        model = get_local_whisper_model(language)
        if model is None:
            raise RuntimeError("本機語音轉文字（faster-whisper）沒有裝")
        name = _local_whisper_name
        breeze = name == BREEZE_STT_MODEL
        segments, info = model.transcribe(audio, language=None if breeze else _whisper_language(language), **options)
        found = [(getattr(s, "start", None), getattr(s, "end", None), s.text.strip()) for s in segments if s.text.strip()]
    detected = getattr(info, "language", None) or language
    if not breeze and (detected or "").split("-")[0].lower() == "zh":
        found = [(start, end, to_traditional(text)) for start, end, text in found]
    return found


def transcribe_local_whisper(audio_path: str, timeout: int = 60, max_duration_sec: Optional[int] = None,
                             language: str = "") -> str:
    """Decodes audio via FFmpeg pipe to 16kHz float32 and transcribes it on this machine."""
    global _force_cpu_stt
    if not get_local_whisper_model(language) or not os.path.exists(audio_path):
        return ""
    try:
        cmd = ["ffmpeg", "-y", "-protocol_whitelist", "file,pipe"]
        if max_duration_sec:
            cmd.extend(["-t", str(max_duration_sec)])
        cmd.extend(["-i", audio_path, "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"])
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
        if proc.returncode != 0 or not proc.stdout:
            return ""
        audio_np = np.frombuffer(proc.stdout, dtype=np.float32)
        if len(audio_np) < 8000:
            return ""
        return " ".join(text for _, _, text in transcribe_audio(audio_np, language, beam_size=3))
    except Exception as e:
        logger.warning(f"[Local STT] Local transcription error: {e}")
        # GPU init can succeed while inference still hits a missing CUDA runtime
        # (lazy DLL load) — self-heal by rebuilding on CPU for subsequent calls.
        if not _force_cpu_stt:
            logger.warning("[Local STT] Disabling GPU path for this session, rebuilding on CPU...")
            from app.parsers.transcript import _stt_lock
            with _stt_lock:
                _force_cpu_stt = True
                _unload()
        return ""

def is_video_reel_url(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path.lower()
    if host == "fb.watch" or host.endswith(".fb.watch"):
        return True
    domains = ("facebook.com", "instagram.com")
    if any(host == domain or host.endswith("." + domain) for domain in domains) and (
        path.startswith("/reel/") or path.startswith("/reels/") or path.startswith("/share/r/")
    ):
        return True
    yt_domains = ("youtube.com", "youtu.be")
    if any(host == domain or host.endswith("." + domain) for domain in yt_domains) and (
        path.startswith("/shorts/")
    ):
        return True
    return False


def extract_scene_tile(video_path: str, tile_output_path: str, duration: float = 10.0) -> bool:
    """
    Extract time-distributed frames across the complete video timeline and stitch into a 3x4 Tile Storyboard.
    Uses FFmpeg -hwaccel auto for GPU decoding acceleration and scale=540:-1 for crystal-clear OCR.
    Guarantees 100% timeline coverage (early, mid, late frames) regardless of motion or scene cuts.
    """
    safe_duration = max(3.0, float(duration))
    # Offset by 0.3s (or 5% of duration) to bypass intro animations/transitions and capture steady text
    start_offset = min(0.3, safe_duration * 0.05)
    effective_duration = max(1.0, safe_duration - start_offset)
    sample_fps = 12.0 / effective_duration

    # 1. Primary: Time-distributed 3x4 Storyboard covering the entire timeline
    cmd_grid = [
        "ffmpeg", "-y", "-hwaccel", "auto", "-protocol_whitelist", "file,pipe",
        "-ss", str(round(start_offset, 2)), "-i", video_path,
        "-vf", f"fps={sample_fps:.3f},scale=540:-1,tile=3x4",
        "-frames:v", "1",
        tile_output_path
    ]
    try:
        subprocess.run(cmd_grid, capture_output=True, timeout=30)
    except Exception as e:
        logger.warning(f"[Reel Storyboard] FFmpeg grid sampling failed: {e}")

    if os.path.exists(tile_output_path) and os.path.getsize(tile_output_path) > 1024:
        logger.info(f"[Reel Storyboard] Generated 3x4 timeline storyboard ({os.path.getsize(tile_output_path)} bytes, {sample_fps:.2f} fps)")
        return True

    # 2. Fallback: Standard 3x3 grid without start offset
    logger.info("[Reel Storyboard] 3x4 grid failed, falling back to 3x3 uniform tile...")
    fallback_fps = max(0.5, 9.0 / safe_duration)
    cmd_fallback = [
        "ffmpeg", "-y", "-hwaccel", "auto", "-protocol_whitelist", "file,pipe", "-i", video_path,
        "-vf", f"fps={fallback_fps:.3f},scale=540:-1,tile=3x3",
        "-frames:v", "1",
        tile_output_path
    ]
    try:
        subprocess.run(cmd_fallback, capture_output=True, timeout=30)
    except Exception as e:
        logger.warning(f"[Reel Storyboard] Fallback 3x3 tile failed: {e}")

    return os.path.exists(tile_output_path) and os.path.getsize(tile_output_path) > 1024

def extract_audio_stream(video_path: str, audio_output_path: str) -> bool:
    """
    Fast extraction of audio track (16kHz mono MP3, optimized for Whisper/speech recognition).
    Takes ~0.05-0.2 seconds.
    """
    cmd = [
        "ffmpeg", "-y", "-protocol_whitelist", "file,pipe", "-i", video_path,
        "-vn", "-acodec", "libmp3lame",
        "-ar", "16000", "-ac", "1", "-q:a", "5",
        audio_output_path
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=20)
        return os.path.exists(audio_output_path) and os.path.getsize(audio_output_path) > 500
    except Exception as e:
        logger.warning(f"[Reel Audio] FFmpeg audio extraction failed: {e}")
        return False

async def analyze_storyboard_vision(tile_path: str) -> str:
    """
    Single Vision API call analyzing the complete 3x3 storyboard tile.
    Replaces 12 separate frame requests with 1 unified multimodal call.
    """
    if not os.path.exists(tile_path) or os.path.getsize(tile_path) < 1024:
        return ""

    prompt = """辨識這張短影音時間軸影格拼貼圖（Storyboard Tile）的畫面文字與關鍵動作。
畫面中展示了短影音不同時間點展示的開源專案、工具卡片、投影片或系統架構。
請嚴格根據畫面內容，逐一完整條列出畫面上出現的所有專案/工具：
1. 專案/工具序號與名稱（例如 No.01 Security Audit, No.06 AgentGuard 等）
2. 畫面中標註的 GitHub 倉庫路徑或網址（例如 cloudflare/security-audit-skill, GoPlusSecurity/agentguard 等）
3. GitHub Stars 數量（若有標示）
4. 核心功能與防護/技術亮點說明
請務必將畫面中出現的「每一個」卡片或工具完整列出，切勿遺漏任何一項！格式維持高密度結構化文字。
畫面不是專案或工具卡片時，就條列畫面上看得到的文字、數字與圖表重點。看不清楚的不要猜。"""

    with open(tile_path, "rb") as f:
        img_bytes = f.read()

    # 1. The analysis slot: its chain reads the image with the first connection that can
    #    (Gemini / Vertex natively, an OpenAI-compatible model through image_url). Before
    #    2026-11-09 only an OpenAI-compatible primary was tried, so with a Vertex primary every
    #    storyboard came back empty without a word in the log.
    provider = get_primary_provider()
    if callable(getattr(provider, "describe_image", None)):
        try:
            text = (await provider.describe_image(img_bytes, prompt)).strip()
            if text:
                return text
            logger.warning("[Reel Vision] The analysis slot read the storyboard but returned no text")
        except Exception as e:
            logger.warning(f"[Reel Vision] Analysis slot could not read the storyboard: {e}")

    # 2. The video slot's Gemini, when one is set
    if has_video_provider():
        try:
            return (await get_gemini_provider().describe_image(img_bytes, prompt)).strip()
        except Exception as e:
            logger.warning(f"[Reel Vision] Gemini vision fallback failed: {e}")

    return ""

async def transcribe_audio_stream(audio_path: str) -> str:
    """
    Speech-to-text on the extracted audio track.
    1. First priority: Local high-speed faster-whisper (0.3s, zero API cost).
    2. Second priority: Remote OpenAI Compatible whisper-1.
    3. Third priority: Gemini Multimodal audio.
    """
    if not os.path.exists(audio_path) or os.path.getsize(audio_path) < 500:
        return ""

    # 1. Try Local faster-whisper
    local_text = await _run_thread(lambda: transcribe_local_whisper(audio_path))
    if local_text and local_text.strip():
        from app.parsers.transcript import spoken
        if not spoken(local_text):
            return ""  # music or silence: Whisper's "You" / "Thank you." is not speech
    if local_text and len(local_text.strip()) > 2:
        logger.info(f"[Reel Audio] Local Whisper transcribed {len(local_text)} chars")
        return local_text.strip()

    # 2. Try OpenAI client audio.transcriptions
    provider = get_primary_provider()
    if hasattr(provider, "client") and hasattr(provider.client, "audio"):
        try:
            with open(audio_path, "rb") as af:
                try:
                    resp = await provider.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=af,
                        response_format="text"
                    )
                except Exception:
                    ai_usage.record_failure(getattr(provider, "status_key", ""))
                    raise
                ai_usage.record_success(getattr(provider, "status_key", ""), None)
                if isinstance(resp, str):
                    return resp.strip()
                return getattr(resp, "text", "").strip()
        except Exception as e:
            logger.debug(f"[Reel Audio] Primary audio transcription skipped/failed: {e}")

    # 3. Try Gemini audio multimodal understanding
    if has_video_provider():
        try:
            from google import genai
            from google.genai import types as gtypes
            gemini_prov = get_gemini_provider()
            key = gemini_prov._get_next_key()
            if key:
                client = gemini_prov.make_client(key)
                with open(audio_path, "rb") as af:
                    audio_bytes = af.read()
                resp = await _generate_content(
                    client, gemini_prov.status_key, gemini_prov.label, gemini_prov.limiter,
                    model=gemini_prov.model,
                    contents=[
                        gtypes.Part.from_bytes(data=audio_bytes, mime_type="audio/mp3"),
                        "請忠實將這段短影音的中文/口播語音逐字聽打轉錄為繁體中文，保持高精確度，無贅字。"
                    ]
                )
                return (resp.text or "").strip()
        except Exception as e:
            logger.debug(f"[Reel Audio] Gemini audio transcription failed: {e}")

    return ""

async def parse_video_reel(url: str) -> Dict[str, Any]:
    """
    Dual-Stream Video Reel Analyzer:
    1. Downloads short reel video stream via yt-dlp (with local cookie bridge).
    2. Visual Stream: Scene Cut gt(scene, 0.35) + 3x3 Tile Storyboard -> Single Vision API call.
    3. Audio Stream: FFmpeg 0.2s extraction (audio.mp3) -> Local/Remote Whisper transcription.
    4. Concurrently gathers Visual + Audio tracks into comprehensive technical briefing.
    Falls back gracefully to web page metadata parser if video download fails.
    """
    validate_url(url)
    if not is_video_reel_url(url):
        raise ValueError("Unsupported reel host or path")
    temp_dir = tempfile.mkdtemp(prefix="omni_reel_")
    video_template = os.path.join(temp_dir, "reel.%(ext)s")
    tile_path = os.path.join(temp_dir, "storyboard_tile.jpg")
    audio_path = os.path.join(temp_dir, "audio.mp3")

    try:
        # 1. Download short reel stream via yt-dlp with browser cookie bridge
        #    (only this site's cookies, in a temp file deleted when the block ends)
        with ytdlp_cookie_opts(url) as cookie_opts:
            ydl_opts = {
                'format': 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
                'outtmpl': video_template,
                'quiet': True,
                'overwrites': True,
                'socket_timeout': 15,
                'hls_prefer_native': True,
                'external_downloader': {'default': 'native'},
                'external_downloader_args': {'ffmpeg_i': ['-protocol_whitelist', 'file,pipe']},
                # Facebook /share/r/ links require GenericIE to resolve their redirect; YouTube Shorts uses youtube extractor.
                'allowed_extractors': ['facebook.*', 'instagram.*', 'youtube.*', 'generic'],
                **cookie_opts
            }

            def _download():
                try:
                    with PublicYoutubeDL(ydl_opts) as ydl:
                        return ydl.extract_info(url, download=True)
                except Exception as e:
                    if "cookiesfrombrowser" in ydl_opts or "cookiefile" in ydl_opts:
                        logger.info(f"[Reel Analyzer] Download with session failed ({e}), retrying without session...")
                        fallback_opts = {k: v for k, v in ydl_opts.items() if k not in ("cookiesfrombrowser", "cookiefile")}
                        with PublicYoutubeDL(fallback_opts) as ydl_fb:
                            return ydl_fb.extract_info(url, download=True)
                    raise

            info = await _run_thread(_download)
            if session_lost_metadata(info) and cookie_opts:
                # Facebook serves a logged-in session a page without the post: title "Facebook",
                # no description (2026-11-09: 18 reels lost their text this way). Ask once more
                # without the session for the text only; the downloaded video stays.
                def _public_metadata():
                    meta_opts = {k: v for k, v in ydl_opts.items() if k not in ("cookiesfrombrowser", "cookiefile")}
                    with PublicYoutubeDL({**meta_opts, "skip_download": True}) as ydl_meta:
                        return ydl_meta.extract_info(url, download=False)
                try:
                    public = await _run_thread(_public_metadata)
                    if not session_lost_metadata(public):
                        info = {**info, **{k: public[k] for k in ("title", "description", "uploader", "channel")
                                           if public.get(k)}}
                except Exception as e:
                    logger.info(f"[Reel Analyzer] Public metadata retry failed: {e}")
        raw_title = info.get("title") or ""
        uploader = info.get("uploader") or info.get("channel") or ""
        description = info.get("description") or ""
        duration = float(info.get("duration") or 10.0)

        # Locate downloaded video file in temp_dir
        downloaded_videos = [
            os.path.join(temp_dir, f)
            for f in os.listdir(temp_dir)
            if f.startswith("reel.") and not f.endswith((".mp3", ".jpg"))
        ]
        video_path = downloaded_videos[0] if downloaded_videos else os.path.join(temp_dir, "reel.mp4")

        # Clean title
        cleaned_title = raw_title
        if "|" in cleaned_title:
            cleaned_title = cleaned_title.rsplit("|", 1)[0].strip()
        cleaned_title = re.sub(r'^\d+\s*reactions.*?[\|·]\s*', '', cleaned_title)
        cleaned_title = re.sub(r'^\d+\s*個心情.*?\|\s*', '', cleaned_title)
        if len(cleaned_title) > 60:
            cleaned_title = cleaned_title[:60].strip() + "..."

        author = uploader or "短影音創作者"

        # 2. Extract Visual Tile & Audio Stream via FFmpeg in parallel executor
        def _ffmpeg_dual_stream():
            tile_ok = extract_scene_tile(video_path, tile_path, duration)
            audio_ok = extract_audio_stream(video_path, audio_path)
            return tile_ok, audio_ok

        tile_ok, audio_ok = await _run_thread(_ffmpeg_dual_stream)

        # 3. Parallel Multimodal Ingestion: Single Vision Call + Audio Transcript
        vision_task = analyze_storyboard_vision(tile_path) if tile_ok else asyncio.sleep(0, result="")
        audio_task = transcribe_audio_stream(audio_path) if audio_ok else asyncio.sleep(0, result="")

        tasks = [asyncio.create_task(vision_task), asyncio.create_task(audio_task)]
        try:
            visual_content, audio_transcript = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        # 4. Synthesize raw content combining description + speech transcript + visual OCR
        combined_raw = f"""# {cleaned_title}
作者/發布者：{author}
影音長度：約 {int(duration)} 秒

## 影片貼文說明
{description}

## 口播語音內容轉錄
{audio_transcript if audio_transcript else "(無口播語音或語音辨識未觸發)"}

## 視覺轉場九宮格 (Tile Storyboard) OCR 與架構解構
{visual_content if visual_content else "(無視覺 OCR 內容)"}
"""

        cover_image = info.get("thumbnail") or ""
        result = {
            "url": url,
            "title": cleaned_title or "短影音情報",
            "content_raw": combined_raw.strip(),
            "cover_image": cover_image,
            "author": author,
            "published_date": "",
        }
        if not description.strip() and not audio_transcript and not visual_content:
            # Downloaded, yet no post text, no speech and nothing read off the frames: analysing
            # that would be a guess from the title. Same rule as a video without its transcript.
            from app.parsers.transcript import TRANSCRIPT_MISSING
            reason = "影片下載了，但貼文文字、語音和畫面文字都沒有讀到"
            missing = f"## 影片逐字稿\n{TRANSCRIPT_MISSING}\n原因：{reason}"
            result.update(content_raw=f"{result['content_raw']}\n\n{missing}",
                          transcript_status="failed", transcript_reason=reason)
        return result

    except Exception as e:
        host = (urlsplit(url).hostname or "").lower()
        logger.warning(f"[Reel Analyzer] Video extraction failed ({e}), falling back to page metadata...")
        if host == "instagram.com" or host.endswith(".instagram.com"):
            from app.parsers.web import parse_instagram_page
            page = await parse_instagram_page(url)
        elif any(host == d or host.endswith("." + d) for d in ("youtube.com", "youtu.be")):
            from app.parsers.youtube import fetch_youtube_metadata
            meta = await fetch_youtube_metadata(url)
            desc_val = meta.get("description", "")
            page = {
                "url": url,
                "title": meta.get("title", "YouTube Shorts"),
                "content_raw": f"# {meta.get('title')}\n\n頻道: {meta.get('author')}\n說明:\n{desc_val}\nURL: {url}",
                "cover_image": meta.get("cover_image", ""),
                "author": meta.get("author", ""),
                "published_date": "",
            }
        else:
            page = await parse_facebook_page(url)
        if is_empty_reel_metadata(page):
            raise ReelUnavailableError("無法取得短影音或貼文內容，請確認平台登入狀態後重新傳送連結。") from e
        # Only the post's text: say so, so the pipeline keeps it as a fetch failure and refetch retries.
        from app.parsers.transcript import TRANSCRIPT_MISSING, _short
        reason = f"影片沒有下載到：{_short(e)}"
        missing = f"## 影片逐字稿\n{TRANSCRIPT_MISSING}\n原因：{reason}"
        page = dict(page, content_raw=f"{page.get('content_raw') or ''}\n\n{missing}",
                    transcript_status="failed", transcript_reason=reason)
        return page

    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
