import re
import asyncio
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs
from app.network import public_http_client, validate_url

def is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ("youtube.com", "youtu.be"))

def is_youtube_shorts_url(url: str) -> bool:
    if not is_youtube_url(url):
        return False
    path = (urlparse(url).path or "").lower()
    return path.startswith("/shorts/")

def extract_video_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if (parsed.hostname or "").lower() == "youtu.be":
        return parsed.path.lstrip("/").split("/")[0]
    if "v" in qs:
        return qs["v"][0]
    m = re.match(r"^/(?:shorts|embed|v|live)/([A-Za-z0-9_-]{11})", parsed.path)
    return m.group(1) if m else None

async def fetch_youtube_metadata(url: str) -> Dict[str, Any]:
    """
    Fetch comprehensive YouTube metadata with fast fallback to oEmbed.
    Extracts title, author, description, tags, and thumbnail without heavy downloads.
    """
    validate_url(url)
    if not is_youtube_url(url):
        raise ValueError("Unsupported YouTube host")
    video_id = extract_video_id(url)
    default_thumb = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else ""
    
    data = {
        "url": url,
        "title": "YouTube Video",
        "author": "",
        "cover_image": default_thumb,
        "video_id": video_id or "",
        "description": "",
        "duration": 0,
        "tags": []
    }

    # 1. Primary: yt-dlp fast metadata extraction (skip-download)
    try:
        from app.parsers.media_network import PublicYoutubeDL
        ydl_opts = {
            'skip_download': True,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'socket_timeout': 8,
        }
        def _get_info():
            with PublicYoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)
        info = await asyncio.to_thread(_get_info)
        if info:
            data["title"] = info.get("title") or data["title"]
            data["author"] = info.get("uploader") or info.get("channel") or data["author"]
            data["cover_image"] = info.get("thumbnail") or data["cover_image"]
            data["description"] = info.get("description") or ""
            data["duration"] = int(info.get("duration") or 0)
            data["tags"] = info.get("tags") or []
            return data
    except Exception:
        pass

    # 2. Fallback: Official oEmbed if yt-dlp fails
    try:
        async with public_http_client(timeout=8.0) as client:
            resp = await client.get(
                "https://www.youtube.com/oembed",
                params={"url": url, "format": "json"}
            )
            if resp.status_code == 200:
                js = resp.json()
                data["title"] = js.get("title", data["title"])
                data["author"] = js.get("author_name", "")
                data["cover_image"] = js.get("thumbnail_url", default_thumb)
    except Exception:
        pass

    return data
