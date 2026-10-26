"""Google News Search & Topic Adapter for OmniKeep Radar

Converts user search queries or direct Google News RSS URLs into raw feed items.
Extracts title, clean author/media name, publication date, and link.
"""
from typing import List, Dict, Any, Optional
import urllib.parse
from datetime import datetime, timezone
import feedparser
from app.network import public_http_client
from app.radar.adapters.base import BaseSourceAdapter, RawFeedItem
from app.database import update_radar_source_fetch_meta


class GoogleNewsAdapter(BaseSourceAdapter):
    source_type = "google_news"

    def _normalize_feed_url(self, raw_input: str) -> str:
        s = raw_input.strip()
        if s.startswith("http://") or s.startswith("https://"):
            return s
        # Treat as search query
        encoded = urllib.parse.quote(s)
        return f"https://news.google.com/rss/search?q={encoded}&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"

    async def fetch_latest(self, source: Dict[str, Any]) -> List[RawFeedItem]:
        source_id = source["id"]
        source_url = self._normalize_feed_url(source["url"])
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
                print(f"[Radar:GoogleNews] Network error for {source_url}: {e}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            if resp.status_code == 304:
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            if resp.status_code != 200:
                print(f"[Radar:GoogleNews] HTTP {resp.status_code} for {source_url}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            etag = resp.headers.get("etag")
            last_mod = resp.headers.get("last-modified")

            feed = feedparser.parse(resp.text)
            items = []
            published_dates = []

            for entry in feed.entries:
                raw_title = entry.get("title", "Untitled")
                link = entry.get("link", "")
                summary = entry.get("summary") or entry.get("description") or ""

                # Extract media name from Google News title trailing suffix ("Title - Publisher")
                author = source.get("name", "Google News")
                title = raw_title
                if " - " in raw_title:
                    parts = raw_title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    if parts[1].strip():
                        author = parts[1].strip()

                pub_dt = None
                pub_str = ""
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    try:
                        pub_dt = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                        pub_str = pub_dt.isoformat()
                        published_dates.append(pub_dt)
                    except Exception:
                        pass

                # Incremental cutoff check
                if last_published_at and pub_str and pub_str <= last_published_at:
                    continue

                if link and title:
                    items.append(RawFeedItem(
                        url=link,
                        title=title,
                        content=summary,
                        published_at=pub_str or now_iso,
                        author=author,
                        source_id=str(source_id),
                        source_type="google_news",
                        tier=source.get("tier", 2)
                    ))

            # Update fetch meta & calculate hot hours
            latest_pub = max([i.published_at for i in items]) if items else last_published_at
            hot_hours = self.calculate_hot_hours(published_dates)

            update_radar_source_fetch_meta(
                source_id,
                etag=etag,
                last_modified_header=last_mod,
                last_fetched_at=now_iso,
                last_published_at=latest_pub,
                hot_hours=hot_hours
            )

            return items
