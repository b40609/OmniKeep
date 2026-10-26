import re
from app.network import public_http_client
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs
from app.radar.adapters.base import BaseSourceAdapter, RawFeedItem
from app.database import update_radar_source_fetch_meta
from app.config import settings

class GitHubAdapter(BaseSourceAdapter):
    source_type = "github"

    def _extract_repo_slug(self, url: str) -> Optional[str]:
        m = re.search(r"github\.com/([\w.-]+/[\w.-]+)", url)
        if m:
            slug = m.group(1).rstrip("/")
            first_part = slug.split("/")[0].lower()
            if first_part in ("trending", "search", "topics", "collections", "explore", "features", "settings"):
                return None
            if slug.endswith("/stargazers") or slug.endswith("/watchers"):
                slug = slug.rsplit("/", 1)[0]
            return slug
        return None

    def _is_search_url(self, url: str) -> bool:
        parsed = urlparse(url)
        return "search" in parsed.path.lower() or "q=" in parsed.query

    def _get_headers(self, etag: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": "OmniKeep-Radar/1.0",
            "Accept": "application/vnd.github.v3+json"
        }
        if settings.GITHUB_TOKEN:
            headers["Authorization"] = f"Bearer {settings.GITHUB_TOKEN}"
        if etag:
            headers["If-None-Match"] = etag
        return headers

    async def fetch_latest(self, source: Dict[str, Any]) -> List[RawFeedItem]:
        source_id = source["id"]
        source_url = source["url"]
        last_published_at = source.get("last_published_at")
        repo_slug = self._extract_repo_slug(source_url)
        now_iso = datetime.now(timezone.utc).isoformat()

        # Case 1: Specific Repo Releases / Tags
        if repo_slug:
            api_url = f"https://api.github.com/repos/{repo_slug}/releases"
            headers = self._get_headers(etag=source.get("etag"))
            async with public_http_client(timeout=15.0, follow_redirects=True) as client:
                try:
                    resp = await client.get(api_url, headers=headers)
                except Exception as e:
                    print(f"[Radar:GitHub] Network error for {repo_slug}: {e}")
                    update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                    return []

                if resp.status_code == 304:
                    update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                    return []

                if resp.status_code != 200:
                    print(f"[Radar:GitHub] API returned {resp.status_code} for {repo_slug}")
                    update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
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
                    last_fetched_at=now_iso,
                    last_published_at=newest_pub,
                    etag=etag
                )
                return items

        # Case 2: GitHub Search
        if self._is_search_url(source_url):
            parsed = urlparse(source_url)
            qs = parse_qs(parsed.query)
            query_str = qs.get("q", [""])[0]
            if not query_str:
                query_str = source.get("name", "")

            sort_param = qs.get("s", qs.get("sort", ["updated"]))[0]
            order_param = qs.get("o", qs.get("order", ["desc"]))[0]

            api_url = f"https://api.github.com/search/repositories?q={query_str}&sort={sort_param}&order={order_param}&per_page=10"
            headers = self._get_headers(etag=source.get("etag"))

            async with public_http_client(timeout=15.0, follow_redirects=True) as client:
                try:
                    resp = await client.get(api_url, headers=headers)
                except Exception as e:
                    print(f"[Radar:GitHub] Search error for query '{query_str}': {e}")
                    update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                    return []

                if resp.status_code == 304:
                    update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                    return []

                if resp.status_code != 200:
                    print(f"[Radar:GitHub] Search API returned {resp.status_code} for query '{query_str}'")
                    update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                    return []

                etag = resp.headers.get("etag")
                data = resp.json()
                repo_list = data.get("items", [])
                items = []

                for repo in repo_list:
                    repo_name = repo.get("full_name") or ""
                    html_url = repo.get("html_url")
                    desc = repo.get("description") or "無專案描述"
                    stars = repo.get("stargazers_count", 0)
                    forks = repo.get("forks_count", 0)
                    pub_str = repo.get("pushed_at") or repo.get("updated_at") or now_iso

                    if last_published_at and pub_str and pub_str <= last_published_at:
                        continue

                    items.append(RawFeedItem(
                        url=html_url,
                        title=f"GitHub 探索: {repo_name} (★{stars})",
                        content=f"專案: {repo_name}\n星標: {stars} | 分叉: {forks}\n\n描述:\n{desc}\n網址: {html_url}",
                        published_at=pub_str,
                        author=repo_name.split("/")[0] if "/" in repo_name else repo_name,
                        source_id=source_id,
                        source_type="github",
                        tier=source.get("tier", 2)
                    ))

                newest_pub = items[0].published_at if items else last_published_at
                update_radar_source_fetch_meta(
                    source_id=source_id,
                    last_fetched_at=now_iso,
                    last_published_at=newest_pub,
                    etag=etag
                )
                return items

        # Case 3: GitHub Trending
        async with public_http_client(timeout=15.0, follow_redirects=True) as client:
            try:
                resp = await client.get(source_url, headers={"User-Agent": "Mozilla/5.0"})
            except Exception as e:
                print(f"[Radar:GitHub] Trending error: {e}")
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            if resp.status_code != 200:
                update_radar_source_fetch_meta(source_id, last_fetched_at=now_iso)
                return []

            # Extract repository slugs from trending HTML with robust Box-row pattern
            pattern = r'<article[^>]*class="[^"]*Box-row[^"]*"[\s\S]*?<h2[^>]*>[\s\S]*?<a[^>]*href="/([^"/]+/[^"/]+)"'
            matches = re.findall(pattern, resp.text)
            if not matches:
                # Fallback pattern
                pattern_fallback = r'<h2 class="h3 lh-condensed">[\s\S]*?<a href="/([^"]+)"'
                raw_matches = re.findall(pattern_fallback, resp.text)
                matches = [m.replace("/stargazers", "").strip("/") for m in raw_matches if "/" in m]

            items = []
            seen = set()

            for slug in matches[:10]:
                slug = slug.strip().lstrip("/")
                if slug in seen:
                    continue
                seen.add(slug)
                item_url = f"https://github.com/{slug}"
                items.append(RawFeedItem(
                    url=item_url,
                    title=f"GitHub Trending: {slug}",
                    content=f"開源項目: {slug}\nGitHub Trending 今日熱門開源專案\nURL: {item_url}",
                    published_at=now_iso,
                    author=slug.split("/")[0],
                    source_id=source_id,
                    source_type="github",
                    tier=source.get("tier", 2)
                ))

            update_radar_source_fetch_meta(
                source_id=source_id,
                last_fetched_at=now_iso,
                last_published_at=now_iso
            )
            return items
