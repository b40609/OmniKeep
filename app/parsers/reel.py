import os
import re
import shutil
import base64
import asyncio
import importlib.util
import logging
import subprocess
import tempfile
from typing import Dict, Any, Optional
import numpy as np
from urllib.parse import urlsplit
from app.network import validate_url
from app.parsers.media_network import PublicYoutubeDL

from app.providers import get_primary_provider, get_gemini_provider, has_video_provider
from app.providers.openai_compatible import extract_completion_content
from app.providers.gemini import _generate_content
from app import ai_usage
from app.parsers.web import parse_facebook_page
from app.parsers.cookie_manager import ytdlp_cookie_opts
from app.config import settings

logger = logging.getLogger("omnikeep.reel")

_local_whisper_model = None
_force_cpu_stt = False
# tiny got Mandarin wrong too often to analyse from (and long videos now go through it too):
# large-v3-turbo on the GPU (about 1.6 GB download, 2 GB VRAM), small on a CPU.
GPU_STT_MODEL = "large-v3-turbo"
CPU_STT_MODEL = "small"


class ReelUnavailableError(RuntimeError):
    """The reel could not be retrieved for video analysis."""


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

def get_local_whisper_model():
    """Lazily load local faster-whisper model (optimized for CUDA GPU / CPU multi-thread int8)"""
    global _local_whisper_model
    if _local_whisper_model is None and importlib.util.find_spec("faster_whisper") is None:
        # Optional (requirements-stt.txt): Reels fall back to cloud transcription.
        logger.warning("[Local STT] faster-whisper is not installed; local transcription is off "
                       "(pip install -r requirements-stt.txt)")
        _local_whisper_model = False
    if _local_whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            if not _force_cpu_stt:
                _preload_cuda_dlls()
                try:
                    import ctranslate2
                    if ctranslate2.get_cuda_device_count() > 0:
                        _local_whisper_model = WhisperModel(GPU_STT_MODEL, device="cuda", compute_type="float16")
                        logger.info("[Local STT] Initialized faster-whisper %s on CUDA GPU", GPU_STT_MODEL)
                        return _local_whisper_model
                except Exception as e:
                    logger.warning(f"[Local STT] CUDA init failed, falling back to CPU: {e}")

            threads = min(8, max(2, os.cpu_count() or 4))
            _local_whisper_model = WhisperModel(CPU_STT_MODEL, device="cpu", compute_type="int8", cpu_threads=threads)
            logger.info(f"[Local STT] Initialized faster-whisper on CPU ({threads} threads int8)")
        except Exception as e:
            logger.warning(f"[Local STT] Could not load faster-whisper: {e}")
            _local_whisper_model = False
    return _local_whisper_model if _local_whisper_model is not False else None

def transcribe_local_whisper(audio_path: str, timeout: int = 60, max_duration_sec: Optional[int] = None) -> str:
    """Decodes audio via FFmpeg pipe to 16kHz float32 and transcribes locally in ~0.3s"""
    global _force_cpu_stt, _local_whisper_model
    model = get_local_whisper_model()
    if not model or not os.path.exists(audio_path):
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
        segments, _ = model.transcribe(audio_np, beam_size=3)
        texts = [s.text.strip() for s in segments if s.text.strip()]
        return " ".join(texts)
    except Exception as e:
        logger.warning(f"[Local STT] Local transcription error: {e}")
        # GPU init can succeed while inference still hits a missing CUDA runtime
        # (lazy DLL load) — self-heal by rebuilding on CPU for subsequent calls.
        if not _force_cpu_stt:
            logger.warning("[Local STT] Disabling GPU path for this session, rebuilding on CPU...")
            _force_cpu_stt = True
            _local_whisper_model = None
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

    prompt = """請仔細觀察這張短影音時間軸影格拼貼圖（Storyboard Tile）。
畫面中展示了短影音不同時間點展示的開源專案、工具卡片、投影片或系統架構。
請嚴格根據畫面內容，逐一完整條列出畫面上出現的所有專案/工具：
1. 專案/工具序號與名稱（例如 No.01 Security Audit, No.06 AgentGuard 等）
2. 畫面中標註的 GitHub 倉庫路徑或網址（例如 cloudflare/security-audit-skill, GoPlusSecurity/agentguard 等）
3. GitHub Stars 數量（若有標示）
4. 核心功能與防護/技術亮點說明
請務必將畫面中出現的「每一個」卡片或工具完整列出，切勿遺漏任何一項！格式維持高密度結構化文字。"""

    with open(tile_path, "rb") as f:
        img_bytes = f.read()

    # 1. Primary OpenAI-Compatible Provider
    provider = get_primary_provider()
    if hasattr(provider, "client") and hasattr(provider.client, "chat"):
        try:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            try:
                res = await provider.client.chat.completions.create(
                    model=provider.model,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                        ]
                    }],
                    temperature=0.1
                )
            except Exception:
                ai_usage.record_failure(getattr(provider, "status_key", ""))
                raise
            ai_usage.record_success(getattr(provider, "status_key", ""), res)
            return extract_completion_content(res).strip()
        except Exception as e:
            logger.warning(f"[Reel Vision] Primary provider vision failed: {e}")

    # 2. Gemini Provider Fallback
    if has_video_provider():
        try:
            from google import genai
            from google.genai import types as gtypes
            gemini_prov = get_gemini_provider()
            key = gemini_prov._get_next_key()
            if key:
                client = gemini_prov.make_client(key)
                resp = await _generate_content(
                    client, gemini_prov.status_key, gemini_prov.label, gemini_prov.limiter,
                    model=gemini_prov.model,
                    contents=[
                        gtypes.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                        prompt
                    ]
                )
                return (resp.text or "").strip()
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

        return {
            "url": url,
            "title": cleaned_title or "短影音情報",
            "content_raw": combined_raw.strip(),
            "cover_image": cover_image,
            "author": author,
            "published_date": "",
        }

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
