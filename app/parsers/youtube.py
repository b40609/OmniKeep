import re
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs
from app.network import public_http_client, validate_url

def is_youtube_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in ("youtube.com", "youtu.be"))

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
    Fetch oEmbed info for YouTube video (fast, official, no API key required).
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
    }

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
