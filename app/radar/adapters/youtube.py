import re
from app.network import public_http_client, validate_url
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.radar.adapters.base import BaseSourceAdapter, RawFeedItem
from app.database import update_radar_source_fetch_meta

class YouTubeAdapter(BaseSourceAdapter):
    source_type = "youtube"

    def _extract_channel_id(self, url: str) -> Optional[str]:
        # Direct channel_id URL
        m = re.search(r"channel/(UC[\w-]+)", url)
        if m:
            return m.group(1)
        m = re.search(r"channel_id=(UC[\w-]+)", url)
        if m:
            return m.group(1)
        return None

    async def _resolve_channel_rss_url(self, url: str) -> str:
        validate_url(url)
        cid = self._extract_channel_id(url)
        if cid:
            return f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
        
        # If given custom handle (e.g. https://www.youtube.com/@lexfridman)
        try:
            async with public_http_client(timeout=10.0, follow_redirects=True) as client:
                resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                if resp.status_code == 200:
                    m = re.search(r'<meta itemprop="channelId" content="(UC[\w-]+)"', resp.text)
                    if m:
                        return f"https://www.youtube.com/feeds/videos.xml?channel_id={m.group(1)}"
                    m2 = re.search(r"channel/(UC[\w-]+)", resp.text)
                    if m2:
                        return f"https://www.youtube.com/feeds/videos.xml?channel_id={m2.group(1)}"
        except Exception as e:
            print(f"[Radar:YouTube] Custom handle resolution notice ({url}): {e}")
            
        return url

    async def fetch_latest(self, source: Dict[str, Any]) -> List[RawFeedItem]:
        source_id = source["id"]
        source_url = source["url"]
        last_published_at = source.get("last_published_at")
        now_iso = datetime.now(timezone.utc).isoformat()

        rss_url = await self._resolve_channel_rss_url(source_url)
        
        headers = {"User-Agent": "Mozilla/5.0 (compatible; OmniKeepRadar/1.0)"}
        if source.get("etag"):
            headers["If-None-Match"] = source["etag"]

        async with public_http_client(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(rss_url, headers=headers)
            except Exception as e:
                print(f"[Radar:YouTube] Network error for {rss_url}: {e}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            if resp.status_code == 304:
                # Up to date
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            if resp.status_code != 200:
                print(f"[Radar:YouTube] HTTP {resp.status_code} for {source_url}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            etag = resp.headers.get("etag")
            try:
                root = ET.fromstring(resp.text)
            except Exception as e:
                print(f"[Radar:YouTube] XML parsing error for {source_url}: {e}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            ns = {
                "atom": "http://www.w3.org/2005/Atom",
                "yt": "http://www.youtube.com/xml/schemas/2015",
                "media": "http://search.yahoo.com/mrss/"
            }

            entries = root.findall("atom:entry", ns)
            items = []
            published_dates = []

            for entry in entries:
                video_id_el = entry.find("yt:videoId", ns)
                title_el = entry.find("atom:title", ns)
                link_el = entry.find("atom:link", ns)
                pub_el = entry.find("atom:published", ns)
                author_el = entry.find("atom:author/atom:name", ns)
                desc_el = entry.find("media:group/media:description", ns)

                video_id = video_id_el.text if video_id_el is not None else ""
                title = title_el.text if title_el is not None else "Untitled"
                link = link_el.attrib.get("href") if link_el is not None else f"https://www.youtube.com/watch?v={video_id}"
                pub_str = pub_el.text if pub_el is not None else ""
                author = author_el.text if author_el is not None else source["name"]
                desc = desc_el.text if desc_el is not None else ""

                if pub_str:
                    try:
                        # e.g. 2026-10-22T12:00:00+00:00
                        dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                        # convert to local time (Taiwan UTC+8 for rhythm matching)
                        local_dt = dt.astimezone()
                        published_dates.append(local_dt)
                    except Exception:
                        pass

                # Filter out already fetched videos
                if last_published_at and pub_str and pub_str <= last_published_at:
                    continue

                items.append(RawFeedItem(
                    url=link,
                    title=title,
                    content=f"頻道: {author}\n\n說明:\n{desc[:1000]}",
                    published_at=pub_str,
                    author=author,
                    source_id=source_id,
                    source_type="youtube",
                    tier=source.get("tier", 2)
                ))

            # Automatically learn hot publication hours (Rhythm Analysis)
            hot_hours = self.calculate_hot_hours(published_dates)
            newest_pub = items[0].published_at if items else last_published_at

            update_radar_source_fetch_meta(
                source_id=source_id,
                last_fetched_at=now_iso,
                last_published_at=newest_pub,
                etag=etag,
                hot_hours=hot_hours
            )

            return items
