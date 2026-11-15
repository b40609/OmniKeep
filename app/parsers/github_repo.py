"""A GitHub project's file list, for the architecture diagram in its deep analysis.

The project page itself (README) is fetched like any web page. The analysis prompt also gets the
repository's file paths, so the diagram's cards can point at real files, and app.arch_block keeps
only paths that exist, so a link on a card never leads to a 404.

Three public API calls: the default branch, its latest commit and the tree. GITHUB_TOKEN (in-app
settings) is sent when set; without it the anonymous limit is 60 calls an hour, plenty for links
saved by hand. Then up to CORE_FILES likely-central source files are read from raw.githubusercontent.com
(no API quota) and their first lines go into the page text with line numbers, so a card can point at
the lines that do the work, pinned to that commit (Archify does the same with "repo evidence").
Any failure just leaves the file list or the excerpts out.
"""
from __future__ import annotations

import logging
import re
import asyncio
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

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
EXCERPT_HEADING = "## 核心檔案摘錄"
CORE_FILES = 6
EXCERPT_LINES = 120
EXCERPT_LINE_CHARS = 160
EXCERPT_MAX_CHARS = 9000

_CODE_EXT = {".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs",
             ".swift", ".c", ".cc", ".cpp", ".h", ".hpp", ".vue", ".svelte", ".scala", ".ex", ".dart", ".lua", ".sh"}
_CORE_NAMES = {"main", "app", "server", "index", "cli", "__main__", "run", "manage", "api", "router", "routes",
               "bot", "worker", "agent", "core", "pipeline", "engine", "service", "handler", "handlers", "mod", "lib"}
_CORE_DIRS = {"src", "app", "cmd", "lib", "server", "backend", "core", "pkg", "internal", "api"}
_NOT_CORE = {"test", "tests", "spec", "__tests__", "examples", "example", "docs", "doc", "scripts", "benchmarks",
             "fixtures", "migrations", "e2e"}


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
    return (await fetch_repo(owner, repo))["paths"]


async def fetch_repo(owner: str, repo: str) -> Dict[str, Any]:
    """{"paths": file paths as fetch_repo_files gives them, "sha": the default branch's commit or "",
    "sizes": {path: bytes}}; empty values on any failure."""
    empty: Dict[str, Any] = {"paths": [], "sha": "", "sizes": {}}
    try:
        async with public_http_client(timeout=15.0, follow_redirects=True) as client:
            meta = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=_headers())
            if meta.status_code != 200:
                logger.info("[GitHub] %s/%s: repo lookup answered %s", owner, repo, meta.status_code)
                return []
            branch = meta.json().get("default_branch") or "main"
            sha = ""
            head = await client.get(f"https://api.github.com/repos/{owner}/{repo}/commits/{branch}",
                                    headers={**_headers(), "Accept": "application/vnd.github.sha"})
            if head.status_code == 200 and re.fullmatch(r"[0-9a-f]{40}", head.text.strip()):
                sha = head.text.strip()
            tree = await client.get(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{sha or branch}",
                                    params={"recursive": "1"}, headers=_headers())
            if tree.status_code != 200:
                logger.info("[GitHub] %s/%s: tree answered %s", owner, repo, tree.status_code)
                return empty
            entries = tree.json().get("tree") or []
    except Exception as exc:  # network, JSON: the analysis goes on without the file list
        logger.info("[GitHub] %s/%s: file list not fetched (%s)", owner, repo, exc)
        return empty
    blobs = [e for e in entries if e.get("type") == "blob" and isinstance(e.get("path"), str) and keep_path(e["path"])]
    paths = [e["path"] for e in blobs]
    paths.sort(key=lambda p: (p.count("/"), p.lower()))
    sizes = {e["path"]: int(e.get("size") or 0) for e in blobs}
    return {"paths": paths[:MAX_PATHS], "sha": sha, "sizes": sizes}


def core_files(paths: List[str], sizes: Dict[str, int], limit: int = CORE_FILES) -> List[str]:
    """The source files most likely to show how the project works: entry points and the main
    modules near the top, never tests, docs or examples; at most 2 from one folder."""
    scored = []
    for p in paths:
        segs = p.split("/")
        name = segs[-1]
        dot = name.rfind(".")
        if dot <= 0 or name[dot:].lower() not in _CODE_EXT:
            continue
        low = name.lower()
        if any(x.lower() in _NOT_CORE for x in segs[:-1]) or low.startswith(("test_", "setup.", "conftest")) \
                or ".test." in low or ".spec." in low or low.endswith(".d.ts"):
            continue
        size = sizes.get(p, 0)
        if size and not (150 <= size <= 80000):
            continue
        stem = low[:dot]
        if stem == "__init__" and size < 1500:
            continue
        score = (3 if stem in _CORE_NAMES else 0) + max(0, 2 - (len(segs) - 1)) \
            + (1 if len(segs) > 1 and segs[0].lower() in _CORE_DIRS else 0) + min(size / 8000, 2)
        scored.append((score, p))
    scored.sort(key=lambda x: (-x[0], x[1].lower()))
    out: List[str] = []
    per_dir: Dict[str, int] = {}
    for _, p in scored:
        d = p.rsplit("/", 1)[0] if "/" in p else ""
        if per_dir.get(d, 0) >= 2:
            continue
        per_dir[d] = per_dir.get(d, 0) + 1
        out.append(p)
        if len(out) >= limit:
            break
    return out


async def fetch_excerpts(owner: str, repo: str, info: Dict[str, Any]) -> str:
    """The first lines of the project's core files, numbered, as a section of the page text;
    '' without a commit to pin them to or when nothing could be read."""
    sha = info.get("sha") or ""
    picks = core_files(info.get("paths") or [], info.get("sizes") or {})
    if not sha or not picks:
        return ""

    async def one(client, path: str) -> Optional[Tuple[str, str]]:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{sha}/" + "/".join(quote(x) for x in path.split("/"))
        try:
            r = await client.get(url, headers={"User-Agent": "OmniKeep"})
        except Exception:
            return None
        if r.status_code != 200 or "\x00" in r.text[:2000]:
            return None
        return path, r.text

    try:
        async with public_http_client(timeout=15.0, follow_redirects=True) as client:
            got = await asyncio.gather(*(one(client, p) for p in picks))
    except Exception as exc:
        logger.info("[GitHub] %s/%s: excerpts not fetched (%s)", owner, repo, exc)
        return ""
    return excerpts_section(sha, [g for g in got if g])


def excerpts_section(sha: str, files: List[Tuple[str, str]]) -> str:
    """Numbered first lines of each file under one heading that names the commit; '' for none."""
    parts: List[str] = []
    size = 0
    for path, text in files:
        lines = text.splitlines()
        shown = lines[:EXCERPT_LINES]
        body = "\n".join(f"{i}| {ln[:EXCERPT_LINE_CHARS]}" for i, ln in enumerate(shown, 1) if ln.strip())
        block = f"### {path}（共 {len(lines)} 行，摘第 1 到 {len(shown)} 行）\n{body}"
        if size + len(block) > EXCERPT_MAX_CHARS:
            room = EXCERPT_MAX_CHARS - size
            if room < 600:
                break
            # keep whole lines only, and say how far the excerpt really goes
            cut = block[:room].rsplit("\n", 1)[0]
            last = re.findall(r"^(\d+)\| ", cut, re.M)
            if not last:
                break
            block = cut.replace(f"摘第 1 到 {len(shown)} 行", f"摘第 1 到 {last[-1]} 行", 1)
        parts.append(block)
        size += len(block)
    if not parts:
        return ""
    return f"{EXCERPT_HEADING}（版本 {sha}，行首是行號）\n" + "\n\n".join(parts)


_EXCERPT_HEAD = re.compile(r"^### (.+?)（共 (\d+) 行，摘第 1 到 (\d+) 行）$", re.M)


def excerpts_in(content: str) -> Tuple[str, Dict[str, int]]:
    """(commit, {path: lines shown}) of the excerpts inside stored page text: a card may cite only
    lines the analysis actually saw."""
    at = (content or "").find(EXCERPT_HEADING)
    if at < 0:
        return "", {}
    m = re.search(r"版本 ([0-9a-f]{40})", content[at:at + 200])
    return (m.group(1) if m else ""), {x.group(1): int(x.group(3)) for x in _EXCERPT_HEAD.finditer(content[at:])}


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
