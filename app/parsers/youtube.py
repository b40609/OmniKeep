import re
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs
import httpx

def is_youtube_url(url: str) -> bool:
    nl = urlparse(url).netloc.lower()
    return "youtube.com" in nl or "youtu.be" in nl

def extract_video_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "youtu.be" in parsed.netloc:
        return parsed.path.lstrip("/").split("/")[0]
    if "v" in qs:
        return qs["v"][0]
    m = re.match(r"^/(?:shorts|embed|v|live)/([A-Za-z0-9_-]{11})", parsed.path)
    return m.group(1) if m else None

async def fetch_youtube_metadata(url: str) -> Dict[str, Any]:
    """
    Fetch oEmbed info for YouTube video (fast, official, no API key required).
    """
    video_id = extract_video_id(url)
    default_thumb = f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg" if video_id else ""
    
    data = {
        "url": url,
        "title": "YouTube Video",
        "author": "",
        "cover_image": default_thumb,
        "video_id": video_id or "",
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
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
