from app.network import public_http_client
import feedparser
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.radar.adapters.base import BaseSourceAdapter, RawFeedItem
from app.database import update_radar_source_fetch_meta

class RSSAdapter(BaseSourceAdapter):
    source_type = "rss"

    async def fetch_latest(self, source: Dict[str, Any]) -> List[RawFeedItem]:
        source_id = source["id"]
        source_url = source["url"]
        last_published_at = source.get("last_published_at")
        now_iso = datetime.now(timezone.utc).isoformat()

        headers = {
            "User-Agent": "Mozilla/5.0 (compatible; OmniKeepRadar/1.0)",
            "Accept": "application/rss+xml, application/atom+xml, text/xml, application/xml"
        }
        if source.get("etag"):
            headers["If-None-Match"] = source["etag"]
        if source.get("last_modified_header"):
            headers["If-Modified-Since"] = source["last_modified_header"]

        async with public_http_client(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(source_url, headers=headers)
            except Exception as e:
                print(f"[Radar:RSS] Network error for {source_url}: {e}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            if resp.status_code == 304:
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            if resp.status_code != 200:
                print(f"[Radar:RSS] HTTP {resp.status_code} for {source_url}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            etag = resp.headers.get("etag")
            last_mod = resp.headers.get("last-modified")

            feed = feedparser.parse(resp.text)
            items = []
            published_dates = []

            for entry in feed.entries:
                title = entry.get("title", "Untitled")
                link = entry.get("link", "")
                summary = entry.get("summary") or entry.get("description") or ""
                author = entry.get("author") or source.get("name", "RSS Feed")
                
                # Parse published datetime
                pub_dt = None
                pub_str = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).astimezone()
                    pub_str = pub_dt.isoformat()
                    published_dates.append(pub_dt)
                elif hasattr(entry, "updated_parsed") and entry.updated_parsed:
                    pub_dt = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc).astimezone()
                    pub_str = pub_dt.isoformat()
                    published_dates.append(pub_dt)

                if last_published_at and pub_str and pub_str <= last_published_at:
                    continue

                if not link:
                    continue

                items.append(RawFeedItem(
                    url=link,
                    title=title,
                    content=f"來源: {author}\n\n摘要:\n{summary[:2500]}",
                    published_at=pub_str,
                    author=author,
                    source_id=source_id,
                    source_type="rss",
                    tier=source.get("tier", 2)
                ))

            hot_hours = self.calculate_hot_hours(published_dates)
            newest_pub = items[0].published_at if items else last_published_at

            update_radar_source_fetch_meta(
                source_id=source_id,
                last_fetched_at=now_iso,
                last_published_at=newest_pub,
                etag=etag,
                last_modified_header=last_mod,
                hot_hours=hot_hours
            )

            return items
