import re
from typing import Dict, Any, Optional
import httpx
import trafilatura
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin

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
    return "facebook.com" in parsed.netloc or "fb.watch" in parsed.netloc or "fb.com" in parsed.netloc

async def parse_facebook_page(url: str) -> Dict[str, Any]:
    """Extract clean title, caption, author, and cover image from Facebook posts/reels using crawler UA"""
    async with httpx.AsyncClient(headers=FB_HEADERS, timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url)
        html_text = resp.text

    soup = BeautifulSoup(html_text, "html.parser")

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
    cleaned_title = re.sub(r'^\d+\s*個心情.*?\|\s*', '', cleaned_title)
    if "|" in cleaned_title:
        cleaned_title = cleaned_title.rsplit("|", 1)[0].strip()
    if len(cleaned_title) > 60:
        cleaned_title = cleaned_title[:60].strip() + "..."

    final_title = cleaned_title or (raw_desc.splitlines()[0][:40] if raw_desc else "Facebook 貼文")

    return {
        "url": url,
        "title": final_title,
        "content_raw": raw_desc or "（Facebook 貼文未提供公開文字說明）",
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
    """
    if is_facebook_url(url):
        return await parse_facebook_page(url)

    async with httpx.AsyncClient(headers=BROWSER_HEADERS, timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url)
        html = resp.text

    # Extract structured article using trafilatura
    extracted_text = trafilatura.extract(
        html,
        include_links=True,
        include_images=False,
        output_format="txt"
    )

    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    
    # Meta title fallback
    if not title:
        og_title = soup.find("meta", property="og:title")
        if og_title and og_title.get("content"):
            title = og_title["content"].strip()

    cover_image = extract_meta_image(soup, url)

    # Fallback to BeautifulSoup if trafilatura missed
    if not extracted_text or len(extracted_text.strip()) < 50:
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        extracted_text = soup.get_text(separator="\n\n", strip=True)

    # Limit to first 25,000 characters to prevent token explosion
    clean_content = extracted_text[:25000].strip()

    return {
        "url": url,
        "title": title or "未知標題",
        "content_raw": clean_content,
        "cover_image": cover_image,
        "author": "",
        "published_date": "",
    }
