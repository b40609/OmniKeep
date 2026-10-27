import asyncio
import json
import logging
import os
import re
import tempfile
from typing import Dict, Any, Optional
from urllib.parse import urlparse

from app.network import public_http_client, validate_url
from app.parsers.reel import transcribe_local_whisper

logger = logging.getLogger("omnikeep.bilibili")

BILIBILI_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://www.bilibili.com/",
}

def is_bilibili_url(url: str) -> bool:
    """Returns True if the URL points to a Bilibili video or short link."""
    try:
        host = (urlparse(url).hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in ("bilibili.com", "b23.tv"))
    except Exception:
        return False

def extract_bvid(url: str) -> Optional[str]:
    """Extract BV identifier (e.g. BV1kMxM6FECM) or AV number from URL."""
    match = re.search(r"(BV[0-9A-Za-z]{10})", url)
    if match:
        return match.group(1)
    av_match = re.search(r"(av\d+)", url, re.IGNORECASE)
    if av_match:
        return av_match.group(1)
    return None

async def parse_bilibili_video(url: str) -> Dict[str, Any]:
    """
    Parses a Bilibili video URL and extracts comprehensive metadata and transcripts:
    1. Follows redirects for short b23.tv links.
    2. Extracts structured metadata (title, author, cover, description, duration) from INITIAL_STATE.
    3. Fetches official or AI-generated CC subtitles if available (fast, zero GPU/CPU cost).
    4. If subtitles are unavailable, extracts DASH audio stream and transcribes via local faster-whisper.
    5. Returns normalized dictionary matching OmniKeep pipeline contract.
    """
    validate_url(url)
    clean_url = url.strip()

    async with public_http_client(timeout=15.0) as client:
        # 1. Fetch video page with desktop Chrome headers to bypass 412 WAF
        resp = await client.get(clean_url, headers=BILIBILI_HEADERS, follow_redirects=True)
        if resp.status_code != 200:
            raise ValueError(f"Bilibili returned HTTP {resp.status_code} for {clean_url}")

        html = resp.text
        final_url = str(resp.url)

        # 2. Extract INITIAL_STATE
        state_match = re.search(r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\});", html)
        if not state_match:
            raise ValueError(f"Could not extract video metadata from Bilibili page: {clean_url}")

        try:
            state = json.loads(state_match.group(1))
        except Exception as e:
            raise ValueError(f"Failed to decode Bilibili INITIAL_STATE: {e}")

        vdata = state.get("videoData") or {}
        title = vdata.get("title") or "Bilibili 影片"
        author = (vdata.get("owner") or {}).get("name") or "UP主"
        duration = int(vdata.get("duration") or 0)
        cover_image = vdata.get("pic") or ""
        description = vdata.get("desc") or ""
        bvid = vdata.get("bvid") or extract_bvid(final_url) or ""
        canonical_url = f"https://www.bilibili.com/video/{bvid}" if bvid else final_url

        # 3. Try to fetch CC subtitles if available
        transcript_text = ""
        sub_list = (vdata.get("subtitle") or {}).get("list") or []
        for sub in sub_list:
            sub_url = sub.get("subtitle_url")
            if sub_url:
                if sub_url.startswith("//"):
                    sub_url = "https:" + sub_url
                try:
                    sub_resp = await client.get(sub_url, headers=BILIBILI_HEADERS)
                    if sub_resp.status_code == 200:
                        body = sub_resp.json().get("body", [])
                        lines = []
                        for line in body:
                            from_sec = int(line.get("from", 0))
                            mm = from_sec // 60
                            ss = from_sec % 60
                            txt = (line.get("content") or "").strip()
                            if txt:
                                lines.append(f"[{mm:02d}:{ss:02d}] {txt}")
                        if lines:
                            transcript_text = "\n".join(lines)
                            logger.info(f"[Bilibili] Successfully extracted {len(lines)} CC subtitle lines for {bvid}")
                            break
                except Exception as e:
                    logger.warning(f"[Bilibili] Failed to fetch subtitle file {sub_url}: {e}")

        # 4. If no subtitles, extract DASH audio stream and transcribe locally
        if not transcript_text:
            play_match = re.search(r"window\.__playinfo__\s*=\s*(\{.*?\})<\/script>", html)
            if play_match:
                try:
                    playinfo = json.loads(play_match.group(1))
                    dash = (playinfo.get("data") or {}).get("dash") or {}
                    audio_list = dash.get("audio") or []
                    if audio_list:
                        audio_url = audio_list[0].get("base_url")
                        if audio_url:
                            temp_dir = tempfile.mkdtemp(prefix="omni_bili_")
                            temp_audio = os.path.join(temp_dir, "audio.m4a")
                            try:
                                # Stream up to 15MB audio (~25 minutes of 64kbps speech)
                                audio_headers = {
                                    "User-Agent": BILIBILI_HEADERS["User-Agent"],
                                    "Referer": "https://www.bilibili.com/",
                                    "Range": "bytes=0-5242880",
                                }
                                a_resp = await client.get(audio_url, headers=audio_headers)
                                with open(temp_audio, "wb") as f:
                                    f.write(a_resp.content)

                                logger.info(f"[Bilibili] Transcribing audio snippet for {bvid} via local whisper...")
                                transcript_text = await asyncio.to_thread(transcribe_local_whisper, temp_audio, timeout=60, max_duration_sec=600)
                            finally:
                                try:
                                    if os.path.exists(temp_audio):
                                        os.remove(temp_audio)
                                    os.rmdir(temp_dir)
                                except Exception:
                                    pass
                except Exception as e:
                    logger.warning(f"[Bilibili] Audio extraction/transcription failed for {bvid}: {e}")

        # 5. Format comprehensive Markdown content
        duration_min = round(duration / 60, 1) if duration else 0
        content_raw = f"""# {title}
UP主: {author}
影片時長: 約 {duration_min} 分鐘
原始網址: {canonical_url}

## 影片簡介與說明
{description}

## 影片內容逐字稿與語音轉錄
{transcript_text if transcript_text else "(無可用字幕或語音內容)"}
"""

        return {
            "url": canonical_url,
            "title": title,
            "author": author,
            "duration": duration,
            "cover_image": cover_image,
            "content_raw": content_raw.strip(),
            "source_type": "bilibili"
        }
