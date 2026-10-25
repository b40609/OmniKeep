import os
import re
import shutil
import base64
import asyncio
import logging
import subprocess
import tempfile
from typing import Dict, Any, Optional
import numpy as np
import yt_dlp

from app.providers import get_primary_provider, get_gemini_provider
from app.parsers.web import parse_facebook_page
from app.parsers.cookie_manager import get_ytdlp_cookie_opts
from app.config import settings

logger = logging.getLogger("omnikeep.reel")

_local_whisper_model = None
_force_cpu_stt = False

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
    """Lazily load local faster-whisper model (optimized for i7-14700 8-thread int8 / CUDA)"""
    global _local_whisper_model
    if _local_whisper_model is None:
        try:
            from faster_whisper import WhisperModel
            if not _force_cpu_stt:
                _preload_cuda_dlls()
                try:
                    import ctranslate2
                    if ctranslate2.get_cuda_device_count() > 0:
                        _local_whisper_model = WhisperModel("tiny", device="cuda", compute_type="float16")
                        logger.info("[Local STT] Initialized faster-whisper on CUDA GPU")
                        return _local_whisper_model
                except Exception as e:
                    logger.warning(f"[Local STT] CUDA init failed, falling back to CPU: {e}")

            _local_whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8", cpu_threads=8)
            logger.info("[Local STT] Initialized faster-whisper on CPU (i7-14700 8 threads int8)")
        except Exception as e:
            logger.warning(f"[Local STT] Could not load faster-whisper: {e}")
            _local_whisper_model = False
    return _local_whisper_model if _local_whisper_model is not False else None

def transcribe_local_whisper(audio_path: str) -> str:
    """Decodes audio via FFmpeg pipe to 16kHz float32 and transcribes locally in ~0.3s"""
    global _force_cpu_stt
    model = get_local_whisper_model()
    if not model or not os.path.exists(audio_path):
        return ""
    try:
        cmd = ["ffmpeg", "-y", "-i", audio_path, "-f", "f32le", "-ac", "1", "-ar", "16000", "pipe:1"]
        proc = subprocess.run(cmd, capture_output=True, timeout=15)
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
    clean = url.lower()
    return (
        "facebook.com/reel" in clean
        or "facebook.com/share/r" in clean
        or "fb.watch" in clean
        or "instagram.com/reel" in clean
    )

def extract_scene_tile(video_path: str, tile_output_path: str, duration: float = 10.0) -> bool:
    """
    Extract dynamic scene change frames and stitch into a single 3x3 Tile Storyboard.
    Uses FFmpeg -hwaccel auto for GPU decoding acceleration and scale=640:-1 for high-res OCR.
    Falls back to uniform interval sampling if no dramatic scene cuts are detected.
    """
    # 1. Primary approach: FFmpeg dynamic scene cut gt(scene, 0.35) into 3x3 tile
    cmd_scene = [
        "ffmpeg", "-y", "-hwaccel", "auto", "-i", video_path,
        "-vf", r"select=gt(scene\,0.35),scale=640:-1,tile=3x3",
        "-frames:v", "1",
        tile_output_path
    ]
    try:
        subprocess.run(cmd_scene, capture_output=True, timeout=30)
    except Exception as e:
        logger.warning(f"[Reel SceneCut] FFmpeg scene detection failed: {e}")

    if os.path.exists(tile_output_path) and os.path.getsize(tile_output_path) > 1024:
        logger.info(f"[Reel SceneCut] Generated 3x3 scene storyboard: {os.path.getsize(tile_output_path)} bytes")
        return True

    # 2. Fallback approach: Uniform fps sampling into 3x3 tile (for white-bg talking heads or subtle cuts)
    logger.info("[Reel SceneCut] Few/no scene cuts detected, falling back to uniform interval 3x3 tile...")
    sample_rate = "1" if duration <= 15 else "0.5"
    cmd_uniform = [
        "ffmpeg", "-y", "-hwaccel", "auto", "-i", video_path,
        "-vf", f"fps={sample_rate},scale=640:-1,tile=3x3",
        "-frames:v", "1",
        tile_output_path
    ]
    try:
        subprocess.run(cmd_uniform, capture_output=True, timeout=30)
    except Exception as e:
        logger.warning(f"[Reel SceneCut] Uniform tile fallback failed: {e}")

    return os.path.exists(tile_output_path) and os.path.getsize(tile_output_path) > 1024

def extract_audio_stream(video_path: str, audio_output_path: str) -> bool:
    """
    Fast extraction of audio track (16kHz mono MP3, optimized for Whisper/speech recognition).
    Takes ~0.05-0.2 seconds.
    """
    cmd = [
        "ffmpeg", "-y", "-i", video_path,
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

    prompt = """請仔細觀察這張短影音畫面抽取出的時間軸/轉場九宮格畫面（Tile Storyboard）。
畫面中可能展示開源專案卡片、投影片、終端機程式碼、架構圖或網址。
請辨識並逐一條列出：
1. 專案/工具名稱（例如 OpenHands, AnythingLLM, v0 等）
2. 畫面中出現的 GitHub 網址、官網或作者名稱
3. 核心功能、特色與視覺架構亮點
輸出清晰高密度的純文字條列，不要客套套話。"""

    with open(tile_path, "rb") as f:
        img_bytes = f.read()

    # 1. Primary OpenAI-Compatible Provider
    provider = get_primary_provider()
    if hasattr(provider, "client") and hasattr(provider.client, "chat"):
        try:
            b64 = base64.b64encode(img_bytes).decode("utf-8")
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
            return (res.choices[0].message.content or "").strip()
        except Exception as e:
            logger.warning(f"[Reel Vision] Primary provider vision failed: {e}")

    # 2. Gemini Provider Fallback
    if settings.gemini_keys:
        try:
            from google import genai
            from google.genai import types as gtypes
            gemini_prov = get_gemini_provider()
            key = gemini_prov._get_next_key()
            if key:
                client = genai.Client(api_key=key)
                loop = asyncio.get_event_loop()
                resp = await loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=gemini_prov.model,
                        contents=[
                            gtypes.Part.from_bytes(data=img_bytes, mime_type="image/jpeg"),
                            prompt
                        ]
                    )
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

    loop = asyncio.get_event_loop()

    # 1. Try Local faster-whisper
    local_text = await loop.run_in_executor(None, lambda: transcribe_local_whisper(audio_path))
    if local_text and len(local_text.strip()) > 2:
        logger.info(f"[Reel Audio] Local Whisper transcribed {len(local_text)} chars")
        return local_text.strip()

    # 2. Try OpenAI client audio.transcriptions
    provider = get_primary_provider()
    if hasattr(provider, "client") and hasattr(provider.client, "audio"):
        try:
            with open(audio_path, "rb") as af:
                resp = await provider.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=af,
                    response_format="text"
                )
                if isinstance(resp, str):
                    return resp.strip()
                return getattr(resp, "text", "").strip()
        except Exception as e:
            logger.debug(f"[Reel Audio] Primary audio transcription skipped/failed: {e}")

    # 3. Try Gemini audio multimodal understanding
    if settings.gemini_keys:
        try:
            from google import genai
            from google.genai import types as gtypes
            gemini_prov = get_gemini_provider()
            key = gemini_prov._get_next_key()
            if key:
                client = genai.Client(api_key=key)
                with open(audio_path, "rb") as af:
                    audio_bytes = af.read()
                resp = await loop.run_in_executor(
                    None,
                    lambda: client.models.generate_content(
                        model=gemini_prov.model,
                        contents=[
                            gtypes.Part.from_bytes(data=audio_bytes, mime_type="audio/mp3"),
                            "請忠實將這段短影音的中文/口播語音逐字聽打轉錄為繁體中文，保持高精確度，無贅字。"
                        ]
                    )
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
    temp_dir = tempfile.mkdtemp(prefix="omni_reel_")
    video_path = os.path.join(temp_dir, "reel.mp4")
    tile_path = os.path.join(temp_dir, "storyboard_tile.jpg")
    audio_path = os.path.join(temp_dir, "audio.mp3")

    try:
        # 1. Download short reel stream via yt-dlp with browser cookie bridge
        cookie_opts = get_ytdlp_cookie_opts()
        ydl_opts = {
            'format': 'b[ext=mp4]/best',
            'outtmpl': video_path,
            'quiet': True,
            'overwrites': True,
            'socket_timeout': 15,
            **cookie_opts
        }

        loop = asyncio.get_event_loop()
        def _download():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    return ydl.extract_info(url, download=True)
            except Exception as e:
                if "cookiesfrombrowser" in ydl_opts or "cookiefile" in ydl_opts:
                    logger.info(f"[Reel Analyzer] Cookie extraction notice ({e}), retrying without cookies...")
                    fallback_opts = {k: v for k, v in ydl_opts.items() if k not in ("cookiesfrombrowser", "cookiefile")}
                    with yt_dlp.YoutubeDL(fallback_opts) as ydl_fb:
                        return ydl_fb.extract_info(url, download=True)
                raise

        info = await loop.run_in_executor(None, _download)
        raw_title = info.get("title") or ""
        uploader = info.get("uploader") or ""
        description = info.get("description") or ""
        duration = float(info.get("duration") or 10.0)

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

        tile_ok, audio_ok = await loop.run_in_executor(None, _ffmpeg_dual_stream)

        # 3. Parallel Multimodal Ingestion: Single Vision Call + Audio Transcript
        vision_task = analyze_storyboard_vision(tile_path) if tile_ok else asyncio.sleep(0, result="")
        audio_task = transcribe_audio_stream(audio_path) if audio_ok else asyncio.sleep(0, result="")

        visual_content, audio_transcript = await asyncio.gather(vision_task, audio_task)

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
        logger.warning(f"[Reel Analyzer] Video extraction failed ({e}), falling back to page metadata...")
        return await parse_facebook_page(url)

    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception:
            pass
