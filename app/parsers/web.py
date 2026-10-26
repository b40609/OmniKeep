import re
import asyncio
from typing import Dict, Any, Optional
from urllib.parse import urlparse, urljoin
import httpx
import trafilatura
from bs4 import BeautifulSoup
from app.parsers.cookie_manager import get_cookie_jar, inject_playwright_cookies
from app.network import public_http_client, validate_url

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

FB_HEADERS = {
    "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
}

def is_facebook_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in ("facebook.com", "fb.watch", "fb.com"))

async def fetch_page_with_playwright(url: str) -> Optional[str]:
    """
    Fallback headless rendering via system Chrome with injected cookies.
    Used for JavaScript-heavy single-page applications or access-restricted pages.
    """
    validate_url(url)
    from app.config import settings
    if not settings.ENABLE_BROWSER_FALLBACK:
        return None
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(channel="chrome", headless=True)
            try:
                ctx = await browser.new_context(
                    user_agent=BROWSER_HEADERS["User-Agent"],
                    locale="zh-TW", service_workers="block"
                )
                # Every browser resource is fetched through the pinned public-only
                # HTTP transport. Chromium never connects to a destination directly.
                async def guarded_route(route):
                    try:
                        req = route.request
                        validate_url(req.url)
                        async with public_http_client(timeout=20, follow_redirects=False) as client:
                            response = await client.request(req.method, req.url,
                                                            headers=req.headers, content=req.post_data_buffer)
                        headers = {k: v for k, v in response.headers.items()
                                   if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")}
                        await route.fulfill(status=response.status_code, headers=headers, body=response.content)
                    except Exception:
                        await route.abort()
                await ctx.route("**/*", guarded_route)
                async def reject_socket(ws):
                    await ws.close()
                await ctx.route_web_socket("**/*", reject_socket)
                await inject_playwright_cookies(ctx)
                page = await ctx.new_page()
                await page.goto(url, timeout=20000, wait_until="domcontentloaded")
                await asyncio.sleep(1.5)  # brief grace period for DOM hydration
                content = await page.content()
                return content
            finally:
                await browser.close()
    except Exception as e:
        print(f"[Web Parser] Playwright dynamic render fallback notice: {e}")
        return None

async def parse_facebook_page(url: str) -> Dict[str, Any]:
    """
    Extract Facebook post/reel information with automatic Chrome session injection:
    1. Tries user-authenticated session (with Chrome cookies) to fetch full text and comments.
    2. Falls back to facebookexternalhit crawler User-Agent for OpenGraph metadata if unauthenticated.
    """
    validate_url(url)
    html_text = ""
    used_session = False
    jar = get_cookie_jar()

    # 1. Try authenticated request using bridged session cookies
    if jar:
        try:
            async with public_http_client(headers=BROWSER_HEADERS, cookies=jar, timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(url)
                # Confirm we didn't get bounced to login / checkpoint
                if resp.status_code == 200 and "login" not in str(resp.url).lower() and "checkpoint" not in str(resp.url).lower():
                    html_text = resp.text
                    used_session = True
        except Exception as e:
            print(f"[Facebook Parser] Session request notice: {e}")

    # 2. Fallback to Facebook crawler UA for public OpenGraph metadata
    if not html_text:
        try:
            async with public_http_client(headers=FB_HEADERS, timeout=20.0, follow_redirects=True) as client:
                resp = await client.get(url)
                html_text = resp.text
        except Exception as e:
            print(f"[Facebook Parser] Crawler fallback request error: {e}")
            html_text = ""

    soup = BeautifulSoup(html_text, "html.parser") if html_text else BeautifulSoup("", "html.parser")

    # Extract OpenGraph tags
    og_title_tag = soup.find("meta", property="og:title")
    raw_title = og_title_tag["content"].strip() if og_title_tag and og_title_tag.get("content") else ""

    og_desc_tag = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
    raw_desc = og_desc_tag["content"].strip() if og_desc_tag and og_desc_tag.get("content") else ""

    cover_image = extract_meta_image(soup, url)

    # Clean title and author
    author = ""
    cleaned_title = raw_title
    if "|" in raw_title:
        parts = [p.strip() for p in raw_title.split("|") if p.strip()]
        if len(parts) >= 2:
            author = parts[-1]
    
    # Strip count metrics like "142 個心情 · 48 次分享 | "
    cleaned_title = re.sub(r'^\d+\s*reactions.*?[\|·]\s*', '', cleaned_title)
    cleaned_title = re.sub(r'^\d+\s*個心情.*?\|\s*', '', cleaned_title)
    if "|" in cleaned_title:
        cleaned_title = cleaned_title.rsplit("|", 1)[0].strip()
    if len(cleaned_title) > 60:
        cleaned_title = cleaned_title[:60].strip() + "..."

    final_title = cleaned_title or (raw_desc.splitlines()[0][:40] if raw_desc else "Facebook 貼文")

    content_body = raw_desc or "（Facebook 貼文未提供公開文字說明）"

    # 3. If authenticated session was used, extract any discussion / comment blocks from DOM
    if used_session and soup:
        extracted_comments = []
        for c_node in soup.select("div[role='article'] div[dir='auto'], ul li div[dir='auto']"):
            txt = c_node.get_text(strip=True)
            if txt and len(txt) > 4 and txt not in extracted_comments and txt != raw_desc:
                extracted_comments.append(txt)

        if extracted_comments:
            comment_block = "\n\n### 貼文留言與討論串摘要\n" + "\n".join(f"- {c}" for c in extracted_comments[:12])
            content_body += comment_block

    return {
        "url": url,
        "title": final_title,
        "content_raw": content_body,
        "cover_image": cover_image,
        "author": author or "Facebook",
        "published_date": "",
    }

def extract_meta_image(soup: BeautifulSoup, base_url: str) -> str:
    # 1. og:image
    og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if og and og.get("content"):
        return urljoin(base_url, og["content"].strip())

    # 2. twitter:image
    tw = soup.find("meta", property="twitter:image") or soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return urljoin(base_url, tw["content"].strip())

    # 3. favicon via google
    p = urlparse(base_url)
    return f"https://www.google.com/s2/favicons?sz=128&domain_url={p.scheme}://{p.netloc}"

async def parse_web_page(url: str) -> Dict[str, Any]:
    """
    Fetch web page and extract clean reader-view text and metadata.
    Automatically injects browser cookies and falls back to Playwright if needed.
    """
    validate_url(url)
    if is_facebook_url(url):
        return await parse_facebook_page(url)

    html = ""
    jar = get_cookie_jar()
    try:
        async with public_http_client(headers=BROWSER_HEADERS, cookies=jar, timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                html = resp.text
    except Exception as e:
        print(f"[Web Parser] HTTP fetch failed ({e}), attempting Playwright fallback...")

    # Extract structured article using trafilatura
    extracted_text = ""
    if html:
        extracted_text = trafilatura.extract(
            html,
            include_links=True,
            include_images=False,
            output_format="txt"
        ) or ""

    soup = BeautifulSoup(html, "html.parser") if html else None

    # Fallback to BeautifulSoup if trafilatura missed
    if not extracted_text or len(extracted_text.strip()) < 50:
        if soup:
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                tag.decompose()
            extracted_text = soup.get_text(separator="\n\n", strip=True)

    # Dynamic fallback to Playwright if page is empty or JavaScript protected
    if not extracted_text or len(extracted_text.strip()) < 50:
        pw_html = await fetch_page_with_playwright(url)
        if pw_html:
            html = pw_html
            soup = BeautifulSoup(pw_html, "html.parser")
            extracted_text = trafilatura.extract(
                pw_html,
                include_links=True,
                include_images=False,
                output_format="txt"
            ) or ""
            if not extracted_text or len(extracted_text.strip()) < 50:
                for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                    tag.decompose()
                extracted_text = soup.get_text(separator="\n\n", strip=True)

    title = ""
    if soup:
        if soup.title and soup.title.string:
            title = soup.title.string.strip()
        if not title:
            og_title = soup.find("meta", property="og:title")
            if og_title and og_title.get("content"):
                title = og_title["content"].strip()

    cover_image = extract_meta_image(soup, url) if soup else ""

    # Limit to first 25,000 characters to prevent token explosion
    clean_content = extracted_text[:25000].strip()

    return {
        "url": url,
        "title": title or "未知標題",
        "content_raw": clean_content or "（未能擷取到網頁內文）",
        "cover_image": cover_image,
        "author": "",
        "published_date": "",
        "raw_html": html or "",
    }
