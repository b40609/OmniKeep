import re
import httpx
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.radar.adapters.base import BaseSourceAdapter, RawFeedItem
from app.database import update_radar_source_fetch_meta

class GitHubAdapter(BaseSourceAdapter):
    source_type = "github"

    def _extract_repo_slug(self, url: str) -> Optional[str]:
        m = re.search(r"github\.com/([\w.-]+/[\w.-]+)", url)
        if m:
            slug = m.group(1).rstrip("/")
            if slug.startswith("trending"):
                return None
            return slug
        return None

    async def fetch_latest(self, source: Dict[str, Any]) -> List[RawFeedItem]:
        source_id = source["id"]
        source_url = source["url"]
        last_published_at = source.get("last_published_at")
        repo_slug = self._extract_repo_slug(source_url)

        headers = {
            "User-Agent": "OmniKeep-Radar/1.0",
            "Accept": "application/vnd.github.v3+json"
        }
        if source.get("etag"):
            headers["If-None-Match"] = source["etag"]

        # Case 1: Specific Repo Releases / Tags
        if repo_slug:
            api_url = f"https://api.github.com/repos/{repo_slug}/releases"
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
                try:
                    resp = await client.get(api_url, headers=headers)
                except Exception as e:
                    print(f"[Radar:GitHub] Network error for {repo_slug}: {e}")
                    update_radar_source_fetch_meta(source_id, last_fetched_at=datetime.utcnow().isoformat())
                    return []

                if resp.status_code == 304:
                    update_radar_source_fetch_meta(source_id, last_fetched_at=datetime.utcnow().isoformat())
                    return []

                if resp.status_code != 200:
                    print(f"[Radar:GitHub] API returned {resp.status_code} for {repo_slug}")
                    update_radar_source_fetch_meta(source_id, last_fetched_at=datetime.utcnow().isoformat())
                    return []

                etag = resp.headers.get("etag")
                releases = resp.json()
                items = []

                for r in releases:
                    tag_name = r.get("tag_name") or r.get("name")
                    pub_str = r.get("published_at") or ""
                    html_url = r.get("html_url")
                    body = r.get("body") or ""

                    if last_published_at and pub_str and pub_str <= last_published_at:
                        continue

                    items.append(RawFeedItem(
                        url=html_url,
                        title=f"{repo_slug} {tag_name}: {r.get('name') or 'New Release'}",
                        content=f"倉庫: {repo_slug}\n版本: {tag_name}\n\n更新日誌:\n{body[:2500]}",
                        published_at=pub_str,
                        author=repo_slug.split("/")[0],
                        source_id=source_id,
                        source_type="github",
                        tier=source.get("tier", 1)  # Releases from tracked repos default to Tier 1
                    ))

                newest_pub = items[0].published_at if items else last_published_at
                update_radar_source_fetch_meta(
                    source_id=source_id,
                    last_fetched_at=datetime.utcnow().isoformat(),
                    last_published_at=newest_pub,
                    etag=etag
                )
                return items

        # Case 2: GitHub Trending
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(source_url, headers={"User-Agent": "Mozilla/5.0"})
            except Exception as e:
                print(f"[Radar:GitHub] Trending error: {e}")
                return []

            if resp.status_code != 200:
                return []

            # Extract repository rows from trending HTML
            pattern = r'<h2 class="h3 lh-condensed">[\s\S]*?<a href="/([^"]+)"'
            matches = re.findall(pattern, resp.text)
            items = []

            for slug in matches[:10]:
                slug = slug.strip().lstrip("/")
                item_url = f"https://github.com/{slug}"
                items.append(RawFeedItem(
                    url=item_url,
                    title=f"GitHub Trending: {slug}",
                    content=f"開源項目: {slug}\nGitHub Trending 今日熱門開源專案\nURL: {item_url}",
                    published_at=datetime.utcnow().isoformat(),
                    author=slug.split("/")[0],
                    source_id=source_id,
                    source_type="github",
                    tier=source.get("tier", 2)
                ))

            update_radar_source_fetch_meta(
                source_id=source_id,
                last_fetched_at=datetime.utcnow().isoformat(),
                last_published_at=datetime.utcnow().isoformat()
            )
            return items
