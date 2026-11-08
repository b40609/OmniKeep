"""npm package pages, read from the npm registry and jsDelivr instead of npmjs.com.

www.npmjs.com answers a plain fetch with HTTP 403 (seen 2026-11-08). The registry's /latest manifest
is small (the full document of a popular package is several MB) and has no README, so the README
comes from the published package on jsDelivr.
"""
import logging
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote, urlparse

from app.network import public_http_client

logger = logging.getLogger("omnikeep.npm")

PACKAGE_PATH = re.compile(r"^/package/((?:@[^/]+/)?[^/@]+)(?:/v/([^/]+))?")
REGISTRY = "https://registry.npmjs.org"
JSDELIVR = "https://cdn.jsdelivr.net/npm"
HEADERS = {"User-Agent": "OmniKeep/1.5", "Accept": "application/json"}


def npm_package(url: str) -> Optional[Tuple[str, str]]:
    """(package name, version or "") for an npmjs.com package page, else None."""
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    if host not in ("npmjs.com", "www.npmjs.com"):
        return None
    match = PACKAGE_PATH.match(parts.path)
    if not match:
        return None
    return match.group(1), match.group(2) or ""


def _repo(manifest: Dict[str, Any]) -> str:
    repo = manifest.get("repository")
    url = repo.get("url", "") if isinstance(repo, dict) else (repo or "")
    return re.sub(r"^git\+|\.git$", "", url)


def render(manifest: Dict[str, Any], readme: str) -> str:
    lines = [f"{manifest.get('name', '')} {manifest.get('version', '')}".strip()]
    if manifest.get("description"):
        lines += ["", manifest["description"]]
    facts = [("關鍵字", "、".join(manifest.get("keywords") or [])), ("原始碼", _repo(manifest)),
             ("首頁", manifest.get("homepage") or ""), ("授權", manifest.get("license") or "")]
    facts = [f"{label}：{value}" for label, value in facts if isinstance(value, str) and value]
    if facts:
        lines += [""] + facts
    if readme.strip():
        lines += ["", "README：", "", readme.strip()]
    return "\n".join(lines)


async def parse_npm_package(url: str) -> Optional[Dict[str, Any]]:
    """An npm package page in parse_web_page's shape, or None (not a package page, or the registry failed)."""
    found = npm_package(url)
    if not found:
        return None
    name, version = found
    async with public_http_client(headers=HEADERS, timeout=20.0, follow_redirects=True) as client:
        try:
            resp = await client.get(f"{REGISTRY}/{quote(name, safe='@')}/{quote(version) or 'latest'}")
            if resp.status_code != 200:
                logger.warning("[npm] registry answered HTTP %s for %s", resp.status_code, name)
                return None
            manifest = resp.json()
        except Exception as exc:
            logger.warning("[npm] registry failed for %s (%s)", name, type(exc).__name__)
            return None
        readme = ""
        for filename in ("README.md", "readme.md", "Readme.md"):
            try:
                answer = await client.get(f"{JSDELIVR}/{name}@{manifest.get('version') or 'latest'}/{filename}")
            except Exception:
                break
            if answer.status_code == 200:
                readme = answer.text
                break
    return {
        "url": url,
        "title": f"{manifest.get('name') or name} - npm",
        "content_raw": render(manifest, readme)[:25000],
        "cover_image": "",
        "author": (manifest.get("author") or {}).get("name", "") if isinstance(manifest.get("author"), dict) else "",
        "published_date": "",
        "raw_html": "",
        "http_status": 200,
        "source": "npm registry",
    }
