"""X (Twitter) posts, read through public JSON mirrors instead of x.com itself.

x.com answers a plain HTTP fetch with "JavaScript is disabled" and nothing else (since 2026-10-25,
24 saved posts held only that page). Four independent sources are tried in order; any one is enough:

  1. FxTwitter API   api.fxtwitter.com      full text, long posts too, links expanded
  2. X syndication   cdn.syndication.twimg.com  X's own embed data; long posts only their opening
  3. vxTwitter API   api.vxtwitter.com      text sometimes cut short
  4. X oEmbed        publish.twitter.com    X's embed HTML; text only

When all four fail, parse_web_page falls back to its usual fetch, the pipeline sees the error page
and marks the item, and app.refetch tries it again later.
"""
import logging
import math
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

from bs4 import BeautifulSoup

from app.network import public_http_client

logger = logging.getLogger("omnikeep.x")

X_HOSTS = ("x.com", "twitter.com", "fxtwitter.com", "vxtwitter.com", "fixupx.com", "fixvx.com",
           "twittpr.com", "nitter.net")
STATUS_PATH = re.compile(r"/(?:([A-Za-z0-9_]{1,20})/)?(?:i/(?:web/)?)?status(?:es)?/(\d{5,25})")
# FxTwitter answers an empty body to httpx's default User-Agent.
HEADERS = {"User-Agent": "OmniKeep/1.5", "Accept": "application/json"}
TIMEOUT = 15.0
LONG_POST_NOTE = "（這是長文，這個來源只給了開頭，完整內容請看原文）"


def is_x_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == d or host.endswith("." + d) for d in X_HOSTS)


def x_status(url: str) -> Optional[Tuple[str, str]]:
    """(screen name or "", post id) for a post URL on X or one of its mirrors, else None."""
    if not is_x_url(url):
        return None
    match = STATUS_PATH.search(urlparse(url).path)
    if not match:
        return None
    user = match.group(1) or ""
    return ("" if user.lower() == "i" else user), match.group(2)


DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"


def js_radix(value: float, radix: int = 36) -> str:
    """JavaScript's Number.prototype.toString(radix) for a positive double (V8's DoubleToRadixCString):
    fraction digits only up to the double's precision, rounded half to even."""
    integer = math.floor(value)
    fraction = value - integer
    delta = max(math.nextafter(0.0, 1.0), 0.5 * (math.nextafter(value, math.inf) - value))
    frac: List[int] = []
    if fraction >= delta:
        while True:
            fraction *= radix
            delta *= radix
            digit = int(fraction)
            frac.append(digit)
            fraction -= digit
            if (fraction > 0.5 or (fraction == 0.5 and digit & 1)) and fraction + delta > 1:
                while True:  # round up, carrying into earlier digits
                    if not frac:
                        integer += 1
                        break
                    last = frac.pop() + 1
                    if last < radix:
                        frac.append(last)
                        break
                break
            if fraction < delta:
                break
    head = ""
    integer = int(integer)
    while True:
        head = DIGITS[integer % radix] + head
        integer //= radix
        if not integer:
            break
    return head + ("." + "".join(DIGITS[d] for d in frac) if frac else "")


def syndication_token(post_id: str) -> str:
    """The token X's embed script sends (react-tweet's getToken):
    ((Number(id) / 1e15) * Math.PI).toString(36).replace(/(0+|\\.)/g, '')."""
    return re.sub(r"0+|\.", "", js_radix((int(post_id) / 1e15) * math.pi))


def _iso(text: str) -> str:
    for fmt in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return datetime.strptime((text or "").replace("Z", "+0000"), fmt).astimezone(timezone.utc).isoformat()
        except ValueError:
            continue
    return ""


def _post(text: str, name: str, screen: str, created: str = "", photos: Optional[List[str]] = None,
          videos: Optional[List[Tuple[str, str]]] = None, quote_post: Optional[Dict[str, Any]] = None,
          note: str = "") -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text and not photos and not videos:
        return None
    return {"text": text, "name": (name or "").strip(), "screen": (screen or "").strip(), "created": _iso(created),
            "photos": [p for p in (photos or []) if p], "videos": [v for v in (videos or []) if v[0]],
            "quote": quote_post, "note": note}


def from_fxtwitter(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    tweet = data.get("tweet") if isinstance(data, dict) else None
    if not isinstance(tweet, dict):
        return None
    author = tweet.get("author") or {}
    media = tweet.get("media") or {}
    photos = [p.get("url", "") for p in media.get("photos") or []]
    videos = [(v.get("url", ""), v.get("thumbnail_url", "")) for v in media.get("videos") or []]
    quoted = tweet.get("quote")
    return _post(tweet.get("text") or "", author.get("name", ""), author.get("screen_name", ""),
                 tweet.get("created_at", ""), photos, videos,
                 from_fxtwitter({"tweet": quoted}) if isinstance(quoted, dict) else None)


def _expand_tco(text: str, entities: Dict[str, Any], media: List[Dict[str, Any]]) -> str:
    for link in (entities or {}).get("urls") or []:
        if link.get("url") and link.get("expanded_url"):
            text = text.replace(link["url"], link["expanded_url"])
    for item in media or []:  # the photo / video link at the end says nothing
        if item.get("url"):
            text = text.replace(item["url"], "")
    return text


def from_syndication(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict) or not data.get("text"):
        return None
    user = data.get("user") or {}
    media = data.get("mediaDetails") or []
    photos = [m.get("media_url_https", "") for m in media if m.get("type") == "photo"]
    videos = []
    for m in media:
        if m.get("type") in ("video", "animated_gif"):
            variants = [v for v in (m.get("video_info") or {}).get("variants") or []
                        if v.get("content_type") == "video/mp4"]
            best = max(variants, key=lambda v: v.get("bitrate") or 0)["url"] if variants else ""
            videos.append((best or m.get("expanded_url", ""), m.get("media_url_https", "")))
    quoted = data.get("quoted_tweet")
    return _post(_expand_tco(data["text"], data.get("entities") or {}, media), user.get("name", ""),
                 user.get("screen_name", ""), data.get("created_at", ""), photos, videos,
                 from_syndication(quoted) if isinstance(quoted, dict) else None,
                 LONG_POST_NOTE if data.get("note_tweet") else "")


def from_vxtwitter(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict) or "text" not in data:
        return None
    photos, videos = [], []
    for m in data.get("media_extended") or []:
        if m.get("type") == "image":
            photos.append(m.get("url", ""))
        elif m.get("type") in ("video", "gif"):
            videos.append((m.get("url", ""), m.get("thumbnail_url", "")))
    if not photos and not videos:
        photos = list(data.get("mediaURLs") or [])
    quoted = data.get("qrt")
    return _post(data.get("text") or "", data.get("user_name", ""), data.get("user_screen_name", ""),
                 data.get("date", ""), photos, videos,
                 from_vxtwitter(quoted) if isinstance(quoted, dict) else None)


def from_oembed(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(data, dict) or not data.get("html"):
        return None
    soup = BeautifulSoup(data["html"], "html.parser")
    para = soup.find("p")
    if para is None:
        return None
    for br in para.find_all("br"):
        br.replace_with("\n")
    for link in para.find_all("a"):
        if (link.get_text() or "").startswith("pic.twitter.com"):
            link.decompose()
    name = data.get("author_name", "")
    screen = (data.get("author_url") or "").rstrip("/").rsplit("/", 1)[-1]
    return _post(unescape(para.get_text()), name, screen)


def sources(user: str, post_id: str) -> List[Tuple[str, str, Callable[[Dict[str, Any]], Any]]]:
    canonical = f"https://x.com/{user or 'i'}/status/{post_id}"
    return [
        ("FxTwitter", f"https://api.fxtwitter.com/{user or 'i'}/status/{post_id}", from_fxtwitter),
        ("X syndication", f"https://cdn.syndication.twimg.com/tweet-result?id={post_id}&lang=en"
                          f"&token={syndication_token(post_id)}", from_syndication),
        ("vxTwitter", f"https://api.vxtwitter.com/{user or 'i'}/status/{post_id}", from_vxtwitter),
        ("X oEmbed", f"https://publish.twitter.com/oembed?omit_script=1&dnt=true&url={quote(canonical, safe='')}",
         from_oembed),
    ]


def render(post: Dict[str, Any], depth: int = 0) -> str:
    who = f"{post['name']} (@{post['screen']})" if post["screen"] else post["name"]
    lines = [f"{who} 在 X 發文" + (f" · {post['created'][:16].replace('T', ' ')} UTC" if post["created"] else "")]
    if post["text"]:
        lines += ["", post["text"]]
    if post["note"]:
        lines += ["", post["note"]]
    if post["photos"]:
        lines += ["", "圖片："] + [f"- {p}" for p in post["photos"]]
    if post["videos"]:
        lines += ["", "影片："] + [f"- {v}" for v, _ in post["videos"]]
    if post["quote"] and depth == 0:
        quoted = render(post["quote"], depth + 1)
        lines += ["", "引用的貼文：", *(f"> {line}" if line else ">" for line in quoted.splitlines())]
    return "\n".join(lines)


async def parse_x_post(url: str) -> Optional[Dict[str, Any]]:
    """A post on X in parse_web_page's shape, or None when it is not a post URL or no source answered."""
    found = x_status(url)
    if not found:
        return None
    user, post_id = found
    errors = []
    async with public_http_client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        for name, source_url, convert in sources(user, post_id):
            try:
                resp = await client.get(source_url)
                if resp.status_code != 200:
                    errors.append(f"{name}: HTTP {resp.status_code}")
                    continue
                post = convert(resp.json())
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__}")
                continue
            if not post:
                errors.append(f"{name}: no post in the answer")
                continue
            if errors:
                logger.info("[X] %s read through %s after %s", post_id, name, "; ".join(errors))
            who = f"{post['name']} (@{post['screen']})" if post["screen"] else post["name"]
            media = post["photos"] + [thumb for _, thumb in post["videos"] if thumb]
            return {
                "url": url,
                "title": f"{who} on X" if who else "X 貼文",
                "content_raw": render(post)[:25000],
                "cover_image": media[0] if media else "",
                "author": who,
                "published_date": post["created"],
                "raw_html": "",
                "http_status": 200,
                "source": name,
            }
    logger.warning("[X] every source failed for post %s: %s", post_id, "; ".join(errors))
    return None
