"""The canonical form of a link, so the same page behind different links is spotted.

Used by app.database.normalize_canonical_url (item lookups, citations, the queue's
"already collected?" check) and the radar's dedupe. Rules, in the spirit of Miniflux's
urlcleaner and the ClearURLs rule set:

- Tracking parameters are dropped (utm_*, fbclid, gclid, igsh, si, ...); every other
  parameter is kept, sorted, so ?v=, ?id= and ?p= still tell pages apart.
- Platforms whose links carry the identity in a known place get one form each:
  YouTube https://www.youtube.com/watch?v=ID, X https://x.com/user/status/ID,
  Threads https://www.threads.net/@user/post/ID, GitHub https://github.com/owner/repo,
  Instagram and TikTok without any query.
- Scheme and host are lower-cased, default ports, fragments and a trailing slash go.

Short links (t.co, b23.tv, lnkd.in) are left as they are: telling where they lead
needs a request.
"""
import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit

TRACKING_PREFIXES = ("utm_", "mtm_", "pk_", "hsa_", "__hs")
TRACKING_PARAMS = frozenset({
    # ad and click ids
    "fbclid", "gclid", "gclsrc", "dclid", "gbraid", "wbraid", "yclid", "msclkid", "twclid", "ttclid",
    "li_fat_id", "rb_clickid", "s_cid", "cmpid", "_openstat",
    # newsletters and marketing tools
    "mc_cid", "mc_eid", "_hsenc", "_hsmi", "hsctatracking", "oly_anon_id", "oly_enc_id",
    "vero_conv", "vero_id", "wickedid", "ref", "ref_src", "ref_url",
    # share buttons of social apps (YouTube's own feature/pp go with its video-id rule)
    "igshid", "igsh", "mibextid", "rdid", "si",
    # Bilibili and Taobao-style share ids
    "spm", "scm", "spm_id_from", "from_spmid", "vd_source", "share_source", "share_medium",
    "share_plat", "share_session_id", "share_tag", "share_from", "unique_k", "bbid",
})

_YOUTUBE_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com", "youtu.be"}
_X_HOSTS = {"x.com", "twitter.com", "mobile.twitter.com", "mobile.x.com"}
_NO_QUERY_HOSTS = {"instagram.com", "tiktok.com", "threads.net", "threads.com"}
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_URL_IN_TEXT = re.compile(r'https?://[^\s()<>"]+')


def _bare(host: str) -> str:
    return host[4:] if host.startswith("www.") else host


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered in TRACKING_PARAMS or lowered.startswith(TRACKING_PREFIXES)


def _youtube_id(host: str, path: str, params: list) -> Optional[str]:
    if host == "youtu.be":
        candidate = path.lstrip("/").split("/")[0]
    else:
        candidate = next((v for k, v in params if k == "v"), "")
        if not candidate:
            m = re.match(r"^/(?:shorts|embed|v|live)/([^/?#]+)", path)
            candidate = m.group(1) if m else ""
    return candidate if _YOUTUBE_ID.match(candidate or "") else None


def canonical_url(url: str) -> str:
    """The canonical form of `url`; '' for empty input. Text around a link is ignored."""
    if not url:
        return ""
    clean = url.strip()
    found = _URL_IN_TEXT.search(clean)
    if found:
        clean = found.group(0)
    try:
        parts = urlsplit(clean)
    except ValueError:
        return clean
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        return clean.split("#", 1)[0].rstrip("/")
    host = parts.hostname.lower()
    bare = _bare(host)
    try:
        port = parts.port
    except ValueError:
        port = None
    netloc = host if port in (None, 80, 443) else f"{host}:{port}"
    path = parts.path or ""
    params = parse_qsl(parts.query, keep_blank_values=True)

    if bare in _YOUTUBE_HOSTS:
        video = _youtube_id(bare, path, params)
        if video:
            return f"https://www.youtube.com/watch?v={video}"
    if bare in _X_HOSTS:
        m = re.match(r"^/([^/]+)/status(?:es)?/(\d+)", path)
        if m:
            return f"https://x.com/{m.group(1).lower()}/status/{m.group(2)}"
    if bare in ("threads.net", "threads.com"):
        m = re.match(r"^/(@[^/]+)/post/([^/]+)", path)
        if m:
            return f"https://www.threads.net/{m.group(1).lower()}/post/{m.group(2)}"
    if bare == "github.com":
        m = re.match(r"^/([^/]+)/([^/]+)", path)
        if m:
            repo = m.group(2)[:-4] if m.group(2).lower().endswith(".git") else m.group(2)
            return f"https://github.com/{m.group(1).lower()}/{repo.lower()}"

    path = path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if bare in _NO_QUERY_HOSTS:
        params = []
    kept = sorted((k, v) for k, v in params if not _is_tracking(k))
    query = urlencode(kept, doseq=True)
    return f"{scheme}://{netloc}{path}" + (f"?{query}" if query else "")


def search_key(canon: str) -> str:
    """A piece of text every stored link with this canonical form contains (lower-cased),
    to narrow a LIKE search before comparing canonical forms exactly."""
    if not canon:
        return ""
    m = re.match(r"^https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})$", canon)
    if m:
        return m.group(1).lower()
    m = re.match(r"^https://x\.com/[^/]+/status/(\d+)$", canon)
    if m:
        return f"/status/{m.group(1)}"
    m = re.match(r"^https://www\.threads\.net/@[^/]+/post/([^/]+)$", canon)
    if m:
        return f"/post/{m.group(1).lower()}"
    try:
        parts = urlsplit(canon)
    except ValueError:
        return canon.lower()
    return (_bare((parts.hostname or "").lower()) + (parts.path or "")).lower()
