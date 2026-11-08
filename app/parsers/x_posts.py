"""X (Twitter) posts, read through public JSON mirrors instead of x.com itself.

x.com answers a plain HTTP fetch with "JavaScript is disabled" and nothing else (since 2026-10-25,
24 saved posts held only that page). Independent sources are tried in order; any one is enough:

  1. FxTwitter API v2  api.fxtwitter.com/2   full text, the author's own follow-up posts (where the
                                              link often is) and the replies, links expanded
  2. FxTwitter API v1  api.fxtwitter.com      full text, no replies
  3. X syndication     cdn.syndication.twimg.com  X's own embed data; long posts only their opening
  4. vxTwitter API     api.vxtwitter.com      text sometimes cut short
  5. X oEmbed          publish.twitter.com    X's embed HTML; text only

When the replies could not be read the content says so (REPLIES_MISSING) and app.refetch tries
again later. When every source fails, parse_web_page falls back to its usual fetch, the pipeline
sees the error page and marks the item, and app.refetch tries that again too.
"""
import logging
import math
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
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
# Marks content whose replies could not be read this time; app.refetch looks for it.
REPLIES_MISSING = "（留言這次沒有讀到，OmniKeep 稍後會自動再試）"
FX = "https://api.fxtwitter.com"
MAX_REPLY_PAGES = 5
MAX_REPLIES = 100
LEADING_MENTIONS = re.compile(r"^(?:@[A-Za-z0-9_]{1,20}\s+)+")


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


def _count(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _post(text: str, name: str, screen: str, created: str = "", photos: Optional[List[str]] = None,
          videos: Optional[List[Tuple[str, str]]] = None, quote_post: Optional[Dict[str, Any]] = None,
          note: str = "", post_id: str = "", reply_count: Optional[int] = None,
          to: str = "") -> Optional[Dict[str, Any]]:
    text = (text or "").strip()
    if not text and not photos and not videos:
        return None
    return {"id": str(post_id or ""), "text": text, "name": (name or "").strip(), "screen": (screen or "").strip(),
            "created": _iso(created), "photos": [p for p in (photos or []) if p],
            "videos": [v for v in (videos or []) if v[0]], "quote": quote_post, "note": note,
            "reply_count": reply_count, "to": (to or "").strip(), "thread": [], "replies": [], "replies_note": ""}


def from_fxtwitter(data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """FxTwitter's answer: v1 {"tweet": ...} or v2 {"status": ...}."""
    tweet = (data.get("tweet") or data.get("status")) if isinstance(data, dict) else None
    if not isinstance(tweet, dict):
        return None
    author = tweet.get("author") or {}
    media = tweet.get("media") or {}
    photos = [p.get("url", "") for p in media.get("photos") or []]
    videos = [(v.get("url", ""), v.get("thumbnail_url", "")) for v in media.get("videos") or []]
    quoted = tweet.get("quote")
    to = tweet.get("replying_to")
    to = to.get("screen_name", "") if isinstance(to, dict) else (to or "")
    return _post(tweet.get("text") or "", author.get("name", ""), author.get("screen_name", ""),
                 tweet.get("created_at", ""), photos, videos,
                 from_fxtwitter({"tweet": quoted}) if isinstance(quoted, dict) else None,
                 post_id=tweet.get("id", ""), reply_count=_count(tweet.get("replies")), to=str(to))


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
                 LONG_POST_NOTE if data.get("note_tweet") else "", post_id=data.get("id_str", ""),
                 reply_count=_count(data.get("conversation_count")))


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
                 from_vxtwitter(quoted) if isinstance(quoted, dict) else None,
                 post_id=data.get("tweetID", ""), reply_count=_count(data.get("replies")))


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


async def _json(client, url: str, params: Optional[Dict[str, str]] = None) -> Any:
    resp = await (client.get(url, params=params) if params else client.get(url))
    if resp.status_code != 200:
        raise LookupError(f"HTTP {resp.status_code}")
    return resp.json()


async def fx_replies(client, post_id: str, skip: set) -> List[Dict[str, Any]]:
    """Replies under the post, page after page. A later page that fails keeps what came before."""
    replies: List[Dict[str, Any]] = []
    seen, cursor = set(skip), None
    for page in range(MAX_REPLY_PAGES):
        try:
            data = await _json(client, f"{FX}/2/conversation/{post_id}", {"cursor": cursor} if cursor else None)
        except Exception:
            if page == 0:
                raise
            break
        fresh = 0
        for raw in data.get("replies") or []:
            reply = from_fxtwitter({"status": raw}) if isinstance(raw, dict) else None
            if reply and reply["id"] not in seen:
                seen.add(reply["id"])
                replies.append(reply)
                fresh += 1
        cursor = (data.get("cursor") or {}).get("bottom")
        if not fresh or not cursor or len(replies) >= MAX_REPLIES:
            break
    return replies[:MAX_REPLIES]


async def fx_full(client, user: str, post_id: str) -> Optional[Dict[str, Any]]:
    """The post, the author's own follow-up posts and the replies (FxTwitter API v2)."""
    data = await _json(client, f"{FX}/2/thread/{post_id}")
    post = from_fxtwitter(data)
    if not post:
        return None
    author = post["screen"].lower()
    for raw in data.get("thread") or []:
        follow = from_fxtwitter({"status": raw}) if isinstance(raw, dict) else None
        if follow and follow["id"] != post["id"] and follow["screen"].lower() == author:
            post["thread"].append(follow)
    if post["reply_count"] == 0:
        return post
    try:
        post["replies"] = await fx_replies(client, post_id, {post["id"], *(t["id"] for t in post["thread"])})
    except Exception as exc:
        post["replies_note"] = REPLIES_MISSING
        logger.info("[X] replies of %s not read (%s: %s)", post_id, type(exc).__name__, exc)
    return post


def _simple(url: str, convert: Callable[[Any], Optional[Dict[str, Any]]]):
    async def fetch(client):
        return convert(await _json(client, url))
    return fetch


Source = Tuple[str, Callable[[Any], Awaitable[Optional[Dict[str, Any]]]]]


def sources(user: str, post_id: str) -> List[Source]:
    canonical = f"https://x.com/{user or 'i'}/status/{post_id}"
    return [
        ("FxTwitter", lambda client: fx_full(client, user, post_id)),
        ("FxTwitter v1", _simple(f"{FX}/{user or 'i'}/status/{post_id}", from_fxtwitter)),
        ("X syndication", _simple(f"https://cdn.syndication.twimg.com/tweet-result?id={post_id}&lang=en"
                                  f"&token={syndication_token(post_id)}", from_syndication)),
        ("vxTwitter", _simple(f"https://api.vxtwitter.com/{user or 'i'}/status/{post_id}", from_vxtwitter)),
        ("X oEmbed", _simple(f"https://publish.twitter.com/oembed?omit_script=1&dnt=true"
                             f"&url={quote(canonical, safe='')}", from_oembed)),
    ]


def _who(post: Dict[str, Any]) -> str:
    return f"{post['name']} (@{post['screen']})" if post["screen"] else post["name"]


def _media_lines(post: Dict[str, Any]) -> List[str]:
    lines: List[str] = []
    if post["photos"]:
        lines += ["", "圖片："] + [f"- {p}" for p in post["photos"]]
    if post["videos"]:
        lines += ["", "影片："] + [f"- {v}" for v, _ in post["videos"]]
    return lines


def render(post: Dict[str, Any], depth: int = 0) -> str:
    when = f" · {post['created'][:16].replace('T', ' ')} UTC" if post["created"] else ""
    lines = [f"{_who(post)} 在 X 發文{when}"]
    if post["text"]:
        lines += ["", post["text"]]
    if post["note"]:
        lines += ["", post["note"]]
    lines += _media_lines(post)
    if post["quote"] and depth == 0:
        quoted = render(post["quote"], depth + 1)
        lines += ["", "引用的貼文：", *(f"> {line}" if line else ">" for line in quoted.splitlines())]
    if depth:
        return "\n".join(lines)
    if post["thread"]:
        lines += ["", f"作者接著發的 {len(post['thread'])} 則貼文："]
        for n, follow in enumerate(post["thread"], 1):
            lines += ["", f"（{n}）{follow['text']}"] + _media_lines(follow)
    if post["replies"]:
        shown, total = len(post["replies"]), post["reply_count"]
        more = f"，貼文顯示共 {total} 則" if total and total > shown else ""
        lines += ["", f"留言（收錄 {shown} 則{more}）："]
        author = post["screen"].lower()
        for reply in post["replies"]:
            to = f" 回覆 @{reply['to']}" if reply["to"] and reply["to"].lower() != author else ""
            text = LEADING_MENTIONS.sub("", reply["text"]) or reply["text"]
            extra = " （附圖）" if reply["photos"] or reply["videos"] else ""
            lines.append(f"- {_who(reply)}{to}：{text}{extra}")
    if post["replies_note"]:
        lines += ["", post["replies_note"]]
    return "\n".join(lines)


async def parse_x_post(url: str) -> Optional[Dict[str, Any]]:
    """A post on X in parse_web_page's shape, or None when it is not a post URL or no source answered."""
    found = x_status(url)
    if not found:
        return None
    user, post_id = found
    errors = []
    async with public_http_client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        for name, fetch in sources(user, post_id):
            try:
                post = await fetch(client)
            except Exception as exc:
                errors.append(f"{name}: {type(exc).__name__} {exc}".strip())
                continue
            if not post:
                errors.append(f"{name}: no post in the answer")
                continue
            if errors:
                logger.info("[X] %s read through %s after %s", post_id, name, "; ".join(errors))
            if name != "FxTwitter" and post["reply_count"] != 0:
                post["replies_note"] = REPLIES_MISSING  # this source has no replies
            who = _who(post)
            media = post["photos"] + [thumb for _, thumb in post["videos"] if thumb]
            from app.parsers.transcript import attached_video_section
            spoken = await attached_video_section(post["videos"][0][0]) if post["videos"] else ""
            return {
                "url": url,
                "title": f"{who} on X" if who else "X 貼文",
                "content_raw": render(post)[:25000] + spoken,
                "cover_image": media[0] if media else "",
                "author": who,
                "published_date": post["created"],
                "raw_html": "",
                "http_status": 200,
                "source": name,
            }
    logger.warning("[X] every source failed for post %s: %s", post_id, "; ".join(errors))
    return None
