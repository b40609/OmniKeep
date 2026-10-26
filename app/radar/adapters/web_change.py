"""Web Change Detection Adapter for OmniKeep Radar

Monitors non-RSS web pages (changelogs, documentation, engineering blogs).
Extracts main text, computes content hash, and emits a raw item when content changes.
"""
from typing import List, Dict, Any, Optional
import hashlib
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from app.network import public_http_client
from app.radar.adapters.base import BaseSourceAdapter, RawFeedItem
from app.database import update_radar_source_fetch_meta


class WebChangeAdapter(BaseSourceAdapter):
    source_type = "web_change"

    async def fetch_latest(self, source: Dict[str, Any]) -> List[RawFeedItem]:
        source_id = source["id"]
        source_url = source["url"]
        prev_hash = source.get("etag")  # We reuse the etag field to store content hash
        now_iso = datetime.now(timezone.utc).isoformat()

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; OmniKeepRadar/1.0 WebMonitor)"
        }

        async with public_http_client(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(source_url, headers=headers)
            except Exception as e:
                print(f"[Radar:WebChange] Network error for {source_url}: {e}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            if resp.status_code != 200:
                print(f"[Radar:WebChange] HTTP {resp.status_code} for {source_url}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract clean page title
            page_title = ""
            if soup.title and soup.title.string:
                page_title = soup.title.string.strip()
            elif soup.find("h1"):
                page_title = soup.find("h1").get_text(strip=True)
            if not page_title:
                page_title = source.get("name", "Web Page Monitor")

            # Remove noise
            for elem in soup(["script", "style", "nav", "header", "footer", "aside"]):
                elem.decompose()

            text_content = soup.get_text(separator="\n", strip=True)
            if not text_content:
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            # Compute content hash
            current_hash = hashlib.sha256(text_content.encode("utf-8")).hexdigest()

            # If hash is identical to last seen, no change
            if prev_hash and prev_hash == current_hash:
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            # Content has changed or is newly registered
            update_radar_source_fetch_meta(
                source_id,
                etag=current_hash,
                last_fetched_at=now_iso,
                last_published_at=now_iso,
            )

            # Generate excerpt
            excerpt = text_content[:800]
            if len(text_content) > 800:
                excerpt += "\n\n...(內文後續已截斷)..."

            item = RawFeedItem(
                url=source_url,
                title=f"【網頁更新】{page_title}",
                content=f"偵測到頁面內容異動：\n\n{excerpt}",
                published_at=now_iso,
                author=source.get("name", "Web Monitor"),
                source_id=str(source_id),
                source_type="web_change",
                tier=source.get("tier", 2)
            )

            return [item]
