import re
import json
import logging
from typing import Dict, Any, Optional, List, Tuple
from urllib.parse import urlsplit, urlunsplit
from bs4 import BeautifulSoup
from app.network import public_http_client, validate_url
from app.parsers.cookie_manager import get_cookie_jar

logger = logging.getLogger("omnikeep.threads")

THREADS_DOMAINS = ("threads.net", "threads.com")

CRAWLER_HEADERS = {
    "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}


def is_threads_url(url: str) -> bool:
    """Check if given URL points to Meta Threads service."""
    if not url:
        return False
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        return any(host == d or host.endswith("." + d) for d in THREADS_DOMAINS)
    except Exception:
        return False


def normalize_threads_canonical_url(url: str) -> str:
    """Standardize Threads post URL to https://www.threads.net/@user/post/POST_ID format."""
    if not url:
        return ""
    clean = url.strip()
    # Strip URL fragments and query parameters
    if "#" in clean:
        clean = clean.split("#", 1)[0]
    if "?" in clean:
        clean = clean.split("?", 1)[0]
    clean = clean.rstrip("/")

    # Match @username/post/POST_ID or /t/POST_ID
    m_post = re.search(r'threads\.(?:net|com)/(@[^/]+)/post/([^/?#]+)', clean, re.IGNORECASE)
    if m_post:
        user_slug = m_post.group(1).lower()
        post_id = m_post.group(2)
        return f"https://www.threads.net/{user_slug}/post/{post_id}"

    m_t = re.search(r'threads\.(?:net|com)/t/([^/?#]+)', clean, re.IGNORECASE)
    if m_t:
        post_id = m_t.group(1)
        return f"https://www.threads.net/t/{post_id}"

    return clean


def extract_threads_title(raw_title: str, caption: str, author: str) -> str:
    """Generate high-density title instead of generic platform templates."""
    caption_clean = (caption or "").strip()
    if caption_clean:
        first_line = caption_clean.splitlines()[0].strip()
        first_line = re.sub(r'^[#＃]\S+\s*', '', first_line)  # strip leading hashtag if any
        if len(first_line) > 60:
            first_line = first_line[:60].rstrip() + "..."
        if len(first_line) >= 4:
            return first_line

    if raw_title:
        t = raw_title.strip()
        # Clean phrases like "Threads 上的王小明（@demo.author）" or "user on Threads"
        t_cleaned = re.sub(r'^Threads\s*(?:[•：:]|上的)\s*', '', t, flags=re.IGNORECASE).strip()
        t_cleaned = re.sub(r'\s+on\s+Threads\s*$', '', t_cleaned, flags=re.IGNORECASE).strip()
        if t_cleaned and t_cleaned.lower() != "threads":
            return t_cleaned

    return f"{author} 的 Threads 貼文" if author else "Threads 貼文"


def _extract_from_relay_scripts(soup: BeautifulSoup) -> Tuple[str, List[Dict[str, str]], Dict[str, Any], Dict[str, Any]]:
    """
    Parse SSR RelayPrefetchedStreamCache JSON payloads to extract:
    1. main_caption
    2. discussion comments/replies
    3. author profile (username, full_name)
    4. media attachments (images, video, taken_at)
    """
    main_caption = ""
    replies: List[Dict[str, str]] = []
    author_info = {"username": "", "full_name": ""}
    media_info = {"images": [], "video_url": "", "taken_at": None, "like_count": None}

    for s in soup.find_all("script"):
        scontent = s.string or ""
        if "RelayPrefetchedStreamCache" not in scontent or "data" not in scontent:
            continue
        try:
            payload = json.loads(scontent)

            def walk(obj: Any):
                nonlocal main_caption
                if isinstance(obj, dict):
                    # 1. Media node
                    if "media" in obj and isinstance(obj["media"], dict):
                        m = obj["media"]
                        u = m.get("user") or {}
                        if u.get("username") and not author_info["username"]:
                            author_info["username"] = u.get("username")
                            author_info["full_name"] = u.get("full_name") or ""
                        cap = m.get("caption") or {}
                        if cap.get("text") and not main_caption:
                            main_caption = cap.get("text")

                        if m.get("taken_at") and not media_info["taken_at"]:
                            media_info["taken_at"] = m.get("taken_at")
                        if m.get("like_count") is not None and media_info["like_count"] is None:
                            media_info["like_count"] = m.get("like_count")

                        # Images
                        cands = m.get("image_versions2", {}).get("candidates", [])
                        if cands and cands[0].get("url") and cands[0]["url"] not in media_info["images"]:
                            media_info["images"].append(cands[0]["url"])

                        # Carousel
                        carousel = m.get("carousel_media") or []
                        for cm in carousel:
                            cm_cands = cm.get("image_versions2", {}).get("candidates", [])
                            if cm_cands and cm_cands[0].get("url") and cm_cands[0]["url"] not in media_info["images"]:
                                media_info["images"].append(cm_cands[0]["url"])
                            cm_vids = cm.get("video_versions", [])
                            if cm_vids and not media_info["video_url"]:
                                media_info["video_url"] = cm_vids[0].get("url")

                        # Video
                        video_vids = m.get("video_versions", [])
                        if video_vids and not media_info["video_url"]:
                            media_info["video_url"] = video_vids[0].get("url")

                    # 2. Edges / thread items for comments & replies
                    if "edges" in obj and isinstance(obj["edges"], list):
                        for edge in obj["edges"]:
                            node = edge.get("node", {})
                            text = (node.get("caption") or {}).get("text") or node.get("text")
                            uname = (node.get("user") or {}).get("username") or ""
                            if text:
                                replies.append({"user": uname, "text": text.strip()})

                    if "thread_items" in obj and isinstance(obj["thread_items"], list):
                        for t in obj["thread_items"]:
                            post = t.get("post") or {}
                            cap = post.get("caption") or {}
                            txt = cap.get("text")
                            uname = (post.get("user") or {}).get("username") or ""
                            if txt:
                                replies.append({"user": uname, "text": txt.strip()})

                    for v in obj.values():
                        walk(v)
                elif isinstance(obj, list):
                    for item in obj:
                        walk(item)

            walk(payload)
        except Exception:
            continue

    return main_caption, replies, author_info, media_info


async def parse_threads_page(url: str) -> Dict[str, Any]:
    """
    Fetch and parse Meta Threads post with full metadata, high-resolution media,
    author info, and thread discussions.
    """
    validate_url(url)
    html_text = ""
    used_session = False
    jar = get_cookie_jar()

    # 1. First attempt: Authenticated session or direct crawler UA
    # Threads serves complete SSR markup when crawler User-Agent is presented
    try:
        async with public_http_client(headers=CRAWLER_HEADERS, cookies=jar, timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                html_text = resp.text
                final_url = str(resp.url)
                used_session = True
            else:
                final_url = url
    except Exception as e:
        logger.warning(f"[Threads Parser] First fetch attempt error: {e}")
        final_url = url

    # 2. Fallback: If session had expired cookies, retry without cookies
    if not html_text:
        try:
            async with public_http_client(headers=CRAWLER_HEADERS, timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(url)
                if resp.status_code == 200:
                    html_text = resp.text
                    final_url = str(resp.url)
        except Exception as e:
            logger.error(f"[Threads Parser] Crawler fallback request error: {e}")

    if not html_text:
        return {
            "url": url,
            "title": "Threads 貼文（無法擷取內容）",
            "content_raw": "（未能取得 Threads 頁面內容）",
            "cover_image": "",
            "author": "Threads",
            "published_date": "",
            "raw_html": "",
            "source_type": "threads",
            "meta": {}
        }

    soup = BeautifulSoup(html_text, "html.parser")

    # 3. Extract OpenGraph and Twitter tags
    og_title_tag = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "twitter:title"})
    raw_title = og_title_tag["content"].strip() if og_title_tag and og_title_tag.get("content") else ""

    og_desc_tag = (
        soup.find("meta", property="og:description")
        or soup.find("meta", attrs={"name": "description"})
        or soup.find("meta", attrs={"name": "twitter:description"})
    )
    og_desc = og_desc_tag["content"].strip() if og_desc_tag and og_desc_tag.get("content") else ""

    og_image_tag = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "twitter:image"})
    cover_image = og_image_tag["content"].strip() if og_image_tag and og_image_tag.get("content") else ""

    og_url_tag = soup.find("meta", property="og:url")
    canonical_raw = og_url_tag["content"].strip() if og_url_tag and og_url_tag.get("content") else final_url
    canonical_url = normalize_threads_canonical_url(canonical_raw)

    # 4. Extract structured data from Relay scripts
    caption_text, raw_replies, author_info, media_info = _extract_from_relay_scripts(soup)

    # Resolve author
    author = ""
    target_username = author_info.get("username", "")
    if author_info.get("full_name") and target_username:
        author = f"{author_info['full_name']} (@{target_username})"
    elif target_username:
        author = f"@{target_username}"
    elif author_info.get("full_name"):
        author = author_info["full_name"]

    if not author and raw_title:
        m = re.search(r'Threads 上的\s*(.+)', raw_title)
        if m:
            author = m.group(1).strip()
        else:
            m2 = re.search(r'(.+?)\s+on Threads', raw_title, re.IGNORECASE)
            if m2:
                author = m2.group(1).strip()

    # Resolve main content body
    main_body = caption_text or og_desc
    content_raw = main_body

    # Format discussion / replies (prioritizing author's follow-up thread messages)
    if raw_replies:
        seen_replies = set()
        author_replies: List[str] = []
        community_replies: List[str] = []

        for r in raw_replies:
            txt = r["text"]
            uname = r["user"]
            if not txt or txt in seen_replies or txt == main_body:
                continue
            seen_replies.add(txt)

            if uname and target_username and uname.lower() == target_username.lower():
                author_replies.append(f"- @{uname}（作者補充）: {txt}")
            elif uname:
                community_replies.append(f"- @{uname}: {txt}")
            else:
                community_replies.append(f"- {txt}")

        formatted_thread: List[str] = []
        if author_replies:
            formatted_thread.extend(author_replies[:8])
        if community_replies:
            formatted_thread.extend(community_replies[:8])

        if formatted_thread:
            content_raw += "\n\n### 貼文補充與留言討論\n" + "\n".join(formatted_thread)

    # Resolve cover image
    if not cover_image and media_info["images"]:
        cover_image = media_info["images"][0]

    # Resolve published date
    published_date = ""
    if media_info.get("taken_at"):
        try:
            from datetime import datetime, timezone
            published_date = datetime.fromtimestamp(media_info["taken_at"], tz=timezone.utc).isoformat()
        except Exception:
            pass

    # Clean title
    final_title = extract_threads_title(raw_title, main_body, author)

    from app.parsers.transcript import attached_video_section
    spoken = await attached_video_section(media_info.get("video_url", ""))
    return {
        "url": canonical_url or url,
        "title": final_title,
        "content_raw": (content_raw or "（Threads 貼文未提供公開文字說明）") + spoken,
        "cover_image": cover_image,
        "author": author or "Threads",
        "published_date": published_date,
        "source_type": "threads",
        "raw_html": html_text[:60000],
        "meta": {
            "canonical_url": canonical_url,
            "images": media_info.get("images", []),
            "video_url": media_info.get("video_url", ""),
            "like_count": media_info.get("like_count"),
        }
    }
