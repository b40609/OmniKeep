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
