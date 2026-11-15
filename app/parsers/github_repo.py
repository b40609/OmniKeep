"""A GitHub project's file list, for the architecture diagram in its deep analysis.

The project page itself (README) is fetched like any web page. The analysis prompt also gets the
repository's file paths, so the diagram's cards can point at real files, and app.arch_block keeps
only paths that exist, so a link on a card never leads to a 404.

One public API call for the default branch and one for the tree. GITHUB_TOKEN (in-app settings) is
sent when set; without it the anonymous limit is 60 calls an hour, plenty for links saved by hand.
Any failure just leaves the file list out.
"""
from __future__ import annotations

import logging
import re
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from app.config import settings
from app.network import public_http_client

logger = logging.getLogger("omnikeep.github_repo")

# github.com/<first part> pages that are not a user or organisation
_RESERVED = {
    "about", "apps", "blog", "collections", "contact", "customer-stories", "enterprise", "events", "explore",
    "features", "issues", "login", "marketplace", "new", "notifications", "orgs", "organizations", "pricing",
    "pulls", "search", "security", "settings", "sponsors", "topics", "trending", "site", "signup", "join",
}
_NAME = re.compile(r"^[A-Za-z0-9_.-]+$")

_SKIP_DIRS = {
    ".git", ".github", ".idea", ".vscode", "node_modules", "dist", "build", "out", "target", "vendor",
    "third_party", "__pycache__", ".venv", "venv", "env", "coverage", ".next", ".nuxt", ".cache",
    "site-packages", "bower_components", ".pytest_cache", ".mypy_cache",
}
_SKIP_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg", ".bmp", ".mp4", ".mov", ".webm", ".mp3", ".wav",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".zip", ".gz", ".tar", ".7z", ".pdf", ".map", ".lock",
    ".pyc", ".so", ".dll", ".exe", ".bin", ".onnx", ".pt", ".safetensors", ".parquet", ".db", ".sqlite",
}
_SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "uv.lock", "Cargo.lock", ".DS_Store"}

MAX_PATHS = 400
MAX_CHARS = 6000
TREE_HEADING = "## 專案檔案清單"


def repo_from_url(url: str) -> Optional[Tuple[str, str]]:
    """(owner, repo) of a github.com project address, or None for any other page."""
    try:
        parts = urlparse(url)
    except ValueError:
        return None
    if (parts.hostname or "").lower() not in ("github.com", "www.github.com"):
        return None
    segs = [s for s in parts.path.split("/") if s]
    if len(segs) < 2 or segs[0].lower() in _RESERVED:
        return None
    owner, repo = segs[0], segs[1].removesuffix(".git")
    if not (_NAME.match(owner) and _NAME.match(repo)):
        return None
    if len(segs) > 2 and segs[2] not in ("tree", "blob"):
        return None  # an issue, a pull request, a release page…
    return owner, repo


def keep_path(path: str) -> bool:
    segs = path.split("/")
    if any(s in _SKIP_DIRS for s in segs[:-1]):
        return False
    name = segs[-1]
    if name in _SKIP_FILES or name.endswith((".min.js", ".min.css")):
        return False
    dot = name.rfind(".")
    return not (dot > 0 and name[dot:].lower() in _SKIP_EXT)


def _headers() -> Dict[str, str]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "OmniKeep"}
    token = (settings.GITHUB_TOKEN or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


async def fetch_repo_files(owner: str, repo: str) -> List[str]:
    """The repository's file paths on its default branch, minus build output, media and lock files.
    Shallow paths first, so the cut at MAX_PATHS drops the deepest ones. Empty on any failure."""
    try:
        async with public_http_client(timeout=15.0, follow_redirects=True) as client:
            meta = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=_headers())
            if meta.status_code != 200:
                logger.info("[GitHub] %s/%s: repo lookup answered %s", owner, repo, meta.status_code)
                return []
            branch = meta.json().get("default_branch") or "main"
            tree = await client.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}",
                                    params={"recursive": "1"}, headers=_headers())
            if tree.status_code != 200:
                logger.info("[GitHub] %s/%s: tree answered %s", owner, repo, tree.status_code)
                return []
            entries = tree.json().get("tree") or []
    except Exception as exc:  # network, JSON: the analysis goes on without the file list
        logger.info("[GitHub] %s/%s: file list not fetched (%s)", owner, repo, exc)
        return []
    paths = [e["path"] for e in entries if e.get("type") == "blob" and isinstance(e.get("path"), str) and keep_path(e["path"])]
    paths.sort(key=lambda p: (p.count("/"), p.lower()))
    return paths[:MAX_PATHS]


def files_section(paths: List[str]) -> str:
    """The file list as a section of the page text the analysis reads; '' when there is none."""
    if not paths:
        return ""
    lines, size = [], 0
    for p in sorted(paths, key=str.lower):
        if size + len(p) + 1 > MAX_CHARS:
            break
        lines.append(p)
        size += len(p) + 1
    return f"{TREE_HEADING}（預設分支，共 {len(lines)} 個）\n" + "\n".join(lines)


def files_in(content: str) -> List[str]:
    """The file paths listed by files_section() inside stored page text."""
    at = (content or "").find(TREE_HEADING)
    if at < 0:
        return []
    out = []
    for line in content[at:].splitlines()[1:]:
        line = line.strip()
        if not line or line.startswith("#"):
            break
        out.append(line)
    return out
