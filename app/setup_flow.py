"""First-run setup driven by the user's own agent (docs/agent_setup_skill_design.md).

The logic behind the eleven `omnikeep_*` MCP tools, shared by app.mcp_server and
app.routers.setup. The agent judges and drafts; this module validates and writes.

- Reading (scan, peek, check_sources, preview) works from any process: it reads
  the database and fetches public pages, never keys.
- Writing (apply, ingest, run_radar, import) always goes through the running
  OmniKeep service over HTTP, so a change takes effect at once (the radar
  scheduler wakes, the next analysis uses the new depth). Inside the service
  itself (the Streamable HTTP transport) the same routes are called in-process.
- Nothing here returns a credential: AI keys show only "configured" and the last
  four characters.

Heavy modules (the parsers, the radar adapters, httpx) are imported inside the
functions that need them, so a stdio MCP process starts fast.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from app.config import settings

# Mirrors app.radar.adapters.supported_source_types(); a test keeps them equal.
# Spelled out so validating answers does not import every adapter.
SOURCE_TYPES: Tuple[str, ...] = ("youtube", "github", "rss", "google_news", "web_change")
ANALYSIS_DEPTHS: Tuple[str, ...] = ("standard", "concise", "technical", "actionable")
NOTIFICATION_MODES: Tuple[str, ...] = ("silent", "daily_digest", "vip_alert")
CHANNELS: Tuple[str, ...] = ("web_push", "telegram", "line")
LAST_ANSWERS_KEY = "_meta.setup_answers"  # a row in app_settings; no schema change
MAX_CHECK_SOURCES = 20
MAX_IMPORT_BYTES = 20 * 1024 * 1024


class SetupError(Exception):
    """A problem the agent should read out to the user as it is."""


class ServiceUnavailable(SetupError):
    pass


class ServiceError(SetupError):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status


# ── The running service ─────────────────────────────────────────

_in_process_app = None


def bind_in_process(app) -> None:
    """Called by the service's lifespan: tools running inside it call its routes in-process."""
    global _in_process_app
    _in_process_app = app


def unbind_in_process() -> None:
    global _in_process_app
    _in_process_app = None


def service_base_url() -> str:
    return (os.environ.get("OMNIKEEP_SERVICE_URL") or f"http://127.0.0.1:{settings.PORT}").rstrip("/")


async def call_service(method: str, path: str, *, json_body: Any = None,
                       params: Optional[Dict[str, Any]] = None, timeout: float = 60.0) -> Any:
    """Call a route of the running OmniKeep service with its API key.

    The key comes from this process's own settings and only goes into the
    Authorization header; it is never returned or logged.
    """
    import httpx
    from app.security import configured_key

    key = configured_key()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    if _in_process_app is not None:
        transport, base = httpx.ASGITransport(app=_in_process_app), "http://127.0.0.1"
    else:
        transport, base = None, service_base_url()
    try:
        async with httpx.AsyncClient(base_url=base, transport=transport, timeout=timeout,
                                     trust_env=False) as client:
            resp = await client.request(method, path, json=json_body, params=params, headers=headers)
    except httpx.TimeoutException as exc:
        raise ServiceUnavailable(f"OmniKeep 服務在 {int(timeout)} 秒內沒有回應（{path}）") from exc
    except httpx.TransportError as exc:
        raise ServiceUnavailable(
            f"連不上 OmniKeep 服務（{base}）。請先啟動 OmniKeep（python run.py），再試一次。") from exc
    if resp.status_code >= 400:
        try:
            body = resp.json()
            detail = body.get("detail") or body.get("error") or resp.text[:300]
        except ValueError:
            detail = resp.text[:300]
        if resp.status_code == 401:
            detail = "OmniKeep 拒絕了存取金鑰：這個程式讀到的 API_KEY 跟服務不同"
        raise ServiceError(resp.status_code, str(detail))
    return resp.json()


async def service_running() -> bool:
    if _in_process_app is not None:
        return True
    try:
        await call_service("GET", "/health", timeout=3.0)
        return True
    except SetupError:
        return False


def refresh_settings() -> None:
    """Pick up values saved in the app by the service since this process started.

    Only outside the service: inside it the values are current already, and the
    settings router must see any change itself (a new Telegram token restarts polling).
    """
    if "app.main" in sys.modules:
        return
    from app import app_settings
    app_settings.apply_overrides()


# ── Local commands (gh, nvidia-smi, tailscale) ──────────────────

def _run(cmd: List[str], timeout: float = 10.0) -> Tuple[int, str]:
    """Run a local CLI; (exit code, stdout). Missing or hanging commands give (-1, "")."""
    exe = shutil.which(cmd[0])
    if not exe:
        return -1, ""
    try:
        done = subprocess.run([exe, *cmd[1:]], capture_output=True, timeout=timeout,
                              text=True, encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return -1, ""
    return done.returncode, done.stdout


# ── omnikeep_scan ───────────────────────────────────────────────

def _hardware() -> Dict[str, Any]:
    info: Dict[str, Any] = {"os": f"{platform.system()} {platform.release()}",
                            "cpu": platform.processor() or platform.machine(),
                            "logical_cores": os.cpu_count()}
    try:
        import psutil
        info["ram_gb"] = round(psutil.virtual_memory().total / 1024 ** 3, 1)
    except Exception:
        info["ram_gb"] = None
    code, out = _run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"], 5.0)
    gpus = []
    if code == 0:
        for line in out.strip().splitlines():
            name, _, mem = line.rpartition(",")
            try:
                gpus.append({"name": name.strip(), "vram_gb": round(float(mem) / 1024, 1)})
            except ValueError:
                continue
    info["gpus"] = gpus
    return info


def _bookmark_files() -> List[Tuple[str, str, Path]]:
    """(browser, profile, path) of Chrome and Edge bookmark files on this machine."""
    home = Path.home()
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
        roots = {"chrome": local / "Google" / "Chrome" / "User Data",
                 "edge": local / "Microsoft" / "Edge" / "User Data"}
    elif sys.platform == "darwin":
        support = home / "Library" / "Application Support"
        roots = {"chrome": support / "Google" / "Chrome", "edge": support / "Microsoft Edge"}
    else:
        roots = {"chrome": home / ".config" / "google-chrome", "edge": home / ".config" / "microsoft-edge"}
    found = []
    for browser, root in roots.items():
        if not root.is_dir():
            continue
        for profile in sorted(root.iterdir()):
            path = profile / "Bookmarks"
            if path.is_file():
                found.append((browser, profile.name, path))
    return found


def _count_bookmarks(path: Path) -> Optional[int]:
    """How many links a Chrome-format bookmark file holds; titles and URLs are not kept."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    count = 0
    stack = list((data.get("roots") or {}).values())
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if node.get("type") == "url":
            count += 1
        stack.extend(node.get("children") or [])
    return count


def _github_cli() -> Dict[str, Any]:
    if not shutil.which("gh"):
        return {"installed": False, "logged_in": False, "starred": None}
    code, _ = _run(["gh", "auth", "status"], 10.0)
    if code != 0:
        return {"installed": True, "logged_in": False, "starred": None}
    code, out = _run(["gh", "api", "graphql", "-f",
                      "query={viewer{starredRepositories{totalCount}}}",
                      "--jq", ".data.viewer.starredRepositories.totalCount"], 15.0)
    starred = int(out.strip()) if code == 0 and out.strip().isdigit() else None
    return {"installed": True, "logged_in": True, "starred": starred}


def _omnikit_profiles() -> Dict[str, Any]:
    """Where the user's OmniKit profiles are (design §8); the agent reads them itself."""
    candidates = [os.environ.get("OMNIKIT_HOME"), Path.home() / "Desktop" / "OmniKit", Path.home() / "OmniKit"]
    for root in (Path(c) for c in candidates if c):
        profiles_dir = root / "data" / "profiles"
        if profiles_dir.is_dir():
            profiles = [{"name": p.name, "path": str(p / "AGENTS.md")}
                        for p in sorted(profiles_dir.iterdir()) if (p / "AGENTS.md").is_file()]
            return {"found": True, "root": str(root), "profiles": profiles}
    return {"found": False, "root": None, "profiles": []}


def ai_summary() -> Dict[str, Any]:
    """AI connections and task slots in effect. Keys appear only as configured + last four."""
    from app import ai_connections
    refresh_settings()
    connections = []
    for conn in ai_connections.list_connections():
        d = ai_connections.describe_connection(conn)
        state = d.get("status") or {}
        connections.append({
            "id": d["id"], "card": d["card"], "label": d["label"], "model": d["model"],
            "base_url": d["base_url"], "enabled": d["enabled"], "used_in": d["used_in"],
            "api_key": {"configured": d["key_configured"], "hint": d["key_hint"],
                        "undecryptable": d["key_undecryptable"]},
            "status": {k: state.get(k) for k in ("ok", "at", "status", "message")} if state else None,
            "usage": d.get("usage") or {},
        })
    labels = {c["id"]: c["label"] for c in connections}
    slots = {slot: [labels.get(e["connection_id"], str(e["connection_id"])) for e in entries]
             for slot, entries in ai_connections.slots().items()}
    return {"connections": connections, "slots": slots, "needs_setup": ai_connections.needs_setup()}


async def _local_inference() -> Dict[str, Any]:
    import httpx
    base = (settings.OLLAMA_BASE_URL or settings.BRAIN_BASE_URL or "http://127.0.0.1:11434").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            resp = await client.get(f"{base}/api/tags")
        models = [m.get("name", "") for m in resp.json().get("models", [])] if resp.status_code == 200 else []
        return {"ollama": {"url": base, "running": resp.status_code == 200, "models": models[:20]}}
    except Exception:
        return {"ollama": {"url": base, "running": False, "models": []}}


def read_last_answers() -> Optional[Dict[str, Any]]:
    from contextlib import closing
    from app.database import get_db_connection
    with closing(get_db_connection()) as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (LAST_ANSWERS_KEY,)).fetchone()
    if not row:
        return None
    try:
        return json.loads(row["value"])
    except ValueError:
        return None


def _write_last_answers(answers: Dict[str, Any]) -> None:
    from contextlib import closing
    from app.database import get_db_connection
    now = datetime.now(timezone.utc).isoformat()
    with closing(get_db_connection()) as conn, conn:
        conn.execute(
            "INSERT INTO app_settings (key, value, is_secret, updated_at) VALUES (?, ?, 0, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (LAST_ANSWERS_KEY, json.dumps(answers, ensure_ascii=False), now))


async def scan() -> Dict[str, Any]:
    from app import __version__
    from app.database import get_all_radar_sources, get_radar_settings, get_status_counts

    hardware, bookmark_files, github, running, local = await asyncio.gather(
        asyncio.to_thread(_hardware),
        asyncio.to_thread(_bookmark_files),
        asyncio.to_thread(_github_cli),
        service_running(),
        _local_inference(),
    )
    bookmarks = []
    for browser, profile, path in bookmark_files:
        bookmarks.append({"browser": browser, "profile": profile,
                          "count": await asyncio.to_thread(_count_bookmarks, path)})
    sources = get_all_radar_sources()
    radar = get_radar_settings()
    return {
        "hardware": hardware,
        "omnikeep": {
            "version": __version__,
            "service_running": running,
            "service_url": service_base_url(),
            "items": get_status_counts(),
            "radar_sources": {"total": len(sources), "active": sum(1 for s in sources if s.get("is_active"))},
            "radar": {k: radar[k] for k in ("enabled", "interval_minutes", "notification_mode",
                                            "daily_digest_hour", "vip_threshold")},
            "analysis_depth": settings.ANALYSIS_DEPTH,
            "about_you_set": bool((settings.USER_BACKGROUND or "").strip()),
        },
        "ai": ai_summary(),
        "local_inference": local,
        "last_answers": read_last_answers(),
        "omnikit": _omnikit_profiles(),
        "bookmarks": bookmarks,
        "github": github,
    }


# ── omnikeep_peek ───────────────────────────────────────────────

async def peek(url: str, max_chars: int = 3000) -> Dict[str, Any]:
    """Fetch and parse one link without AI and without saving it."""
    from app.network import UnsafeURL
    from app.pipeline import parse_url

    url = (url or "").strip()
    if not url.lower().startswith(("http://", "https://")):
        raise SetupError("請給 http:// 或 https:// 開頭的網址")
    max_chars = max(200, min(int(max_chars), 12000))
    try:
        parsed = await parse_url(url, light=True)
    except UnsafeURL as exc:
        raise SetupError(str(exc)) from exc
    text = parsed.get("content_raw") or ""
    return {
        "url": parsed["url"],
        "source_type": parsed["source_type"],
        "title": parsed.get("title") or "",
        "author": parsed.get("author") or "",
        "excerpt": text[:max_chars],
        "length": len(text),
        "truncated": len(text) > max_chars,
    }


# ── omnikeep_check_sources ──────────────────────────────────────

class SourceCandidate(BaseModel):
    model_config = ConfigDict(extra="ignore")
    url: str = Field(min_length=1, max_length=2000)
    source_type: Optional[str] = None
    name: Optional[str] = Field(default=None, max_length=120)


def guess_source_type(url: str) -> str:
    lowered = url.strip().lower()
    if not lowered.startswith(("http://", "https://")):
        return "google_news"  # a bare keyword
    host = lowered.split("/", 3)[2] if lowered.count("/") >= 2 else ""
    if host.endswith(("youtube.com", "youtu.be")):
        return "youtube"
    if host == "github.com" or host.endswith(".github.com"):
        return "github"
    if host == "news.google.com":
        return "google_news"
    return "rss"


_FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/feed+json", "application/xml", "text/xml")
_COMMON_FEED_PATHS = ("/feed", "/rss.xml", "/atom.xml", "/feed.xml", "/index.xml", "/rss", "/feed/")
_UA = {"User-Agent": "Mozilla/5.0 (compatible; OmniKeepRadar/1.0)",
       "Accept": "application/rss+xml, application/atom+xml, text/xml, application/xml, text/html;q=0.8"}


def _as_feed(text: str):
    import feedparser
    feed = feedparser.parse(text)
    return feed if feed.entries and feed.version else None


async def discover_feed(url: str) -> Tuple[Optional[str], str]:
    """(feed URL, feed title) for a feed or a site's home page; (None, "") when none is found.

    Order: the URL itself, the page's <link rel="alternate"> feeds, then common paths.
    """
    from urllib.parse import urljoin
    from bs4 import BeautifulSoup
    from app.network import public_http_client

    async with public_http_client(timeout=15.0, follow_redirects=True) as client:
        async def fetch(target: str):
            try:
                resp = await client.get(target, headers=_UA)
            except Exception:
                return None
            return resp if resp.status_code == 200 else None

        page = await fetch(url)
        if page is None:
            return None, ""
        feed = _as_feed(page.text)
        if feed is not None:
            return str(page.url), feed.feed.get("title", "")

        candidates: List[str] = []
        soup = BeautifulSoup(page.text, "html.parser")
        for link in soup.find_all("link", href=True):
            rel = " ".join(link.get("rel") or []).lower()
            kind = (link.get("type") or "").lower()
            if "alternate" in rel and kind in _FEED_TYPES:
                candidates.append(urljoin(str(page.url), link["href"]))
        candidates += [urljoin(str(page.url), path) for path in _COMMON_FEED_PATHS]
        seen = set()
        for target in candidates:
            if target in seen:
                continue
            seen.add(target)
            if len(seen) > 8:
                break
            resp = await fetch(target)
            if resp is None:
                continue
            feed = _as_feed(resp.text)
            if feed is not None:
                return str(resp.url), feed.feed.get("title", "")
    return None, ""


def _parse_when(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        when = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _feed_stats(items: List[Any], recent: int) -> Dict[str, Any]:
    dated = [(_parse_when(getattr(i, "published_at", None)), i) for i in items]
    dated.sort(key=lambda pair: pair[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    dates = [d for d, _ in dated if d]
    latest = dates[0] if dates else None
    per_week = None
    if dates:
        cutoff = datetime.now(timezone.utc) - timedelta(days=28)
        recent_count = sum(1 for d in dates if d >= cutoff)
        if recent_count:
            per_week = round(recent_count / 4, 1)
        else:  # quieter feeds: average over the span the feed shows
            span_days = max((dates[0] - dates[-1]).days, 7)
            per_week = round(len(dates) / (span_days / 7), 2)
    return {
        "item_count": len(items),
        "latest_date": latest.date().isoformat() if latest else None,
        "per_week": per_week,
        "recent_titles": [i.title for _, i in dated[:recent]],
    }


async def check_source(candidate: SourceCandidate, recent: int = 3) -> Dict[str, Any]:
    from app.database import radar_fetch_meta_disabled
    from app.radar.adapters import get_adapter

    source_type = (candidate.source_type or guess_source_type(candidate.url)).lower()
    result: Dict[str, Any] = {"input_url": candidate.url, "source_type": source_type,
                              "url": candidate.url, "name": candidate.name or "", "ok": False}
    adapter = get_adapter(source_type)
    if adapter is None:
        result["error"] = f"不支援的來源類型 {source_type}；可用：{', '.join(SOURCE_TYPES)}"
        return result
    url = candidate.url.strip()
    if source_type == "rss":
        feed_url, feed_title = await discover_feed(url)
        if not feed_url:
            result["error"] = "找不到 RSS 或 Atom；可以改用 web_change（網頁變動）追蹤這個網址"
            result["suggested_source_type"] = "web_change"
            return result
        url = feed_url
        result["name"] = result["name"] or feed_title
        result["discovered_feed"] = feed_url != candidate.url.strip()
    result["url"] = url
    source = {"id": "check-" + hashlib.sha1(f"{source_type}:{url}".encode()).hexdigest()[:10],
              "name": result["name"] or url, "source_type": source_type, "url": url, "tier": 2}
    try:
        with radar_fetch_meta_disabled():  # a trial fetch: no bookkeeping in radar_sources
            items = await adapter.fetch_latest(source)
    except Exception as exc:
        result["error"] = f"抓取失敗：{type(exc).__name__}"
        return result
    result.update(_feed_stats(items or [], recent))
    if not items:
        result["error"] = "沒有抓到任何項目：網址可能有誤、被擋，或最近沒有更新"
        return result
    result["ok"] = True
    if source_type == "web_change":
        result["note"] = "網頁變動：內容改了才會出現新項目，沒有每週篇數"
    if not result["name"]:
        # A keyword query's items come from many outlets; name it after the keyword instead.
        result["name"] = f"Google News：{url}" if source_type == "google_news" else (items[0].author or url)
    return result


async def check_sources(candidates: List[Dict[str, Any]], recent: int = 3) -> Dict[str, Any]:
    if not candidates:
        raise SetupError("請至少給一個候選來源")
    if len(candidates) > MAX_CHECK_SOURCES:
        raise SetupError(f"一次最多驗證 {MAX_CHECK_SOURCES} 個來源")
    try:
        parsed = [SourceCandidate.model_validate(c if isinstance(c, dict) else {"url": str(c)})
                  for c in candidates]
    except ValidationError as exc:
        raise SetupError(_validation_message(exc)) from exc
    gate = asyncio.Semaphore(5)

    async def one(candidate: SourceCandidate) -> Dict[str, Any]:
        async with gate:
            try:
                return await check_source(candidate, recent=max(1, min(recent, 10)))
            except Exception as exc:  # one bad source must not sink the rest
                return {"input_url": candidate.url, "ok": False, "error": f"驗證失敗：{type(exc).__name__}"}

    results = await asyncio.gather(*(one(c) for c in parsed))
    return {"checked": len(results), "ok_count": sum(1 for r in results if r.get("ok")), "results": results}


# ── AI services ─────────────────────────────────────────────
# The cards come from app/provider_catalog.py and the saved connections from
# app/ai_connections.py, read in-process like the rest of the read-only tools.

async def list_provider_options() -> Dict[str, Any]:
    from app import provider_catalog
    catalog = provider_catalog.catalog()
    return {
        "verified": catalog["verified"],
        "note": "選項只說明，不替使用者決定（docs/ai_provider_options_2026-11.md）。"
                "不提供會消耗 Claude、Antigravity 或 ChatGPT 訂閱額度的選項。",
        "options": catalog["cards"],
        "current": ai_summary(),
    }


def _remote_hosts() -> List[str]:
    try:
        from app.mcp_http import remote_hosts
        return remote_hosts()
    except Exception:
        return []


def open_settings(card: str = "", tab: str = "ai") -> Dict[str, Any]:
    """A link that opens OmniKeep's settings on the right tab, where the user pastes the key."""
    from urllib.parse import urlencode
    tab = tab if tab.replace("_", "").isalnum() else "ai"
    fragment = {"settings": tab}
    if card:
        fragment["card"] = "".join(ch for ch in card if ch.isalnum() or ch in "-_")[:40]
    query = urlencode(fragment)
    links = {"url": f"{service_base_url()}/#{query}"}
    remote = _remote_hosts()
    if remote:
        links["remote_url"] = f"https://{remote[0]}/#{query}"
    links["instructions"] = ("請使用者打開這個連結，在設定頁自己貼上金鑰並儲存；"
                             "不要在聊天裡貼金鑰。存好後呼叫 omnikeep_test_provider。")
    return links


def _slot_connection(slot: str) -> Optional[int]:
    from app import ai_connections
    entries = ai_connections.slots().get(slot) or []
    return entries[0]["connection_id"] if entries else None


async def test_provider(service: str = "analysis", connection_id: str = "") -> Dict[str, Any]:
    """Test a saved AI connection (by id, or the first one in a task slot) with a real
    small Chinese JSON request, or a non-AI service (telegram, line, github) by name.
    The result never carries the key."""
    from app import ai_connections
    from app.connection_checks import CHECKS
    if service == "llm":
        service = "analysis"
    target: Optional[int] = None
    purpose = "embeddings" if service == "embeddings" else "chat"
    if connection_id:
        if not str(connection_id).isdigit():
            raise SetupError("connection_id 要是數字")
        target = int(connection_id)
    elif service in ai_connections.SLOTS:
        target = _slot_connection(service)
        if target is None:
            raise SetupError(f"「{service}」這個用途還沒接任何 AI 連線；先在設定頁新增一條")
    elif service not in CHECKS:
        raise SetupError(f"不認得的服務 {service}；可用：{', '.join(ai_connections.SLOTS + tuple(CHECKS))}")

    if target is not None:
        path = f"/api/ai/connections/{target}/test"
        try:
            return await call_service("POST", path, json_body={"purpose": purpose}, timeout=90.0)
        except ServiceUnavailable:
            from app.routers import ai as ai_router
            refresh_settings()
            result = await ai_router.test_connection(target, ai_router.TestBody(purpose=purpose))
            return {**result, "note": "OmniKeep 服務沒在跑，這次直接從本程式測試"}
    try:
        return await call_service("POST", f"/api/settings/check/{service}", json_body={"values": {}}, timeout=90.0)
    except ServiceUnavailable:
        from app.connection_checks import run_check
        refresh_settings()
        return {**await run_check(service, {}), "note": "OmniKeep 服務沒在跑，這次直接從本程式測試"}


# ── omnikeep_preview_setup / omnikeep_apply_setup ───────────────

class SourceAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    source_type: str
    url: str = Field(min_length=1, max_length=2000)
    pack: str = Field(default="", max_length=60)
    tier: int = Field(default=2, ge=1, le=3)

    @field_validator("source_type")
    @classmethod
    def _known_type(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in SOURCE_TYPES:
            raise ValueError(f"source_type 只能是 {', '.join(SOURCE_TYPES)}")
        return value

    @field_validator("name", "url")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("不能是空的")
        return value


class RadarAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Optional[bool] = None
    interval_minutes: Optional[int] = Field(default=None, ge=30, le=1440)


class NotificationAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["silent", "daily_digest", "vip_alert"]
    daily_digest_hour: Optional[int] = Field(default=None, ge=0, le=23)
    channels: List[Literal["web_push", "telegram", "line"]] = Field(default_factory=list, max_length=3)

    @model_validator(mode="after")
    def _hour_for_digest(self):
        if self.mode == "daily_digest" and self.daily_digest_hour is None:
            raise ValueError("選每日摘要時要給 daily_digest_hour（0 到 23）")
        return self


class SetupAnswers(BaseModel):
    """The agent's answers as JSON. stage "followup" is the second preview (design §2 step 9)."""
    model_config = ConfigDict(extra="forbid")
    stage: Literal["first", "followup"] = "first"
    about_you: Optional[str] = Field(default=None, max_length=1000)
    interest_profile: Optional[str] = Field(default=None, max_length=2000)
    topics: List[str] = Field(default_factory=list, max_length=8)
    seed_links: List[str] = Field(default_factory=list, max_length=3)
    sources: List[SourceAnswer] = Field(default_factory=list, max_length=40)
    radar: Optional[RadarAnswer] = None
    analysis_depth: Optional[Literal["standard", "concise", "technical", "actionable"]] = None
    notifications: Optional[NotificationAnswer] = None
    # Question 3: AI connection ids for analysis, primary first, then fallbacks. Ask Brain
    # and the radar follow the analysis slot unless the user set them apart.
    ai_order: Optional[List[int]] = Field(default=None, max_length=8)

    @field_validator("topics")
    @classmethod
    def _topics(cls, value: List[str]) -> List[str]:
        cleaned = [t.strip() for t in value if t and t.strip()]
        if any(len(t) > 60 for t in cleaned):
            raise ValueError("每個主題最多 60 字")
        return cleaned

    @model_validator(mode="after")
    def _followup_scope(self):
        if self.stage == "followup":
            extra = [name for name in ("about_you", "interest_profile", "radar", "ai_order")
                     if getattr(self, name) is not None]
            extra += [name for name in ("topics", "seed_links", "sources") if getattr(self, name)]
            if extra:
                raise ValueError("第二次套用只改分析深度與通知（analysis_depth、notifications），"
                                 f"不能帶 {', '.join(extra)}")
            if self.analysis_depth is None and self.notifications is None:
                raise ValueError("第二次套用至少要給 analysis_depth 或 notifications")
        return self


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:5]:
        where = ".".join(str(p) for p in err.get("loc", ()))
        msg = str(err.get("msg", "")).removeprefix("Value error, ")
        parts.append(f"{where}: {msg}" if where else msg)
    return "答案格式有誤：" + "；".join(parts)


def parse_answers(answers: Any) -> SetupAnswers:
    if isinstance(answers, str):
        try:
            answers = json.loads(answers)
        except ValueError as exc:
            raise SetupError("答案必須是 JSON 物件") from exc
    if not isinstance(answers, dict):
        raise SetupError("答案必須是 JSON 物件")
    try:
        return SetupAnswers.model_validate(answers)
    except ValidationError as exc:
        raise SetupError(_validation_message(exc)) from exc


def _url_key(source_type: str, url: str) -> Tuple[str, str]:
    return source_type.lower(), url.strip().rstrip("/").lower()


def _channel_state() -> Dict[str, bool]:
    from app.database import get_db_connection
    from contextlib import closing
    try:
        with closing(get_db_connection()) as conn:
            subscriptions = conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]
    except Exception:
        subscriptions = 0
    return {"telegram": bool(settings.TELEGRAM_BOT_TOKEN),
            "line": bool(settings.LINE_CHANNEL_ACCESS_TOKEN),
            "web_push": subscriptions > 0}


def build_plan(answers: SetupAnswers) -> Dict[str, Any]:
    """What applying these answers would change, against the current state; nothing is written."""
    from app import app_settings
    from app.database import get_all_radar_sources, get_interest_profile, get_radar_settings

    changes: List[Dict[str, Any]] = []
    settings_values: Dict[str, Any] = {}

    def setting(key: str, label: str, value: Any) -> None:
        spec = app_settings.SPEC_BY_KEY[key]
        try:
            new = app_settings.normalize(spec, value)
        except ValueError as exc:
            raise SetupError(f"{label}：{exc}") from exc
        old = getattr(settings, spec.field)
        if new != old:
            settings_values[key] = new
            changes.append({"key": key, "label": label, "before": old, "after": new})

    if answers.about_you is not None:
        # The setting is one line; the agent may have written several.
        setting("USER_BACKGROUND", "關於你", " ".join(answers.about_you.split()))
    profile_after = None
    if answers.interest_profile is not None:
        before = get_interest_profile()
        after = answers.interest_profile.strip()
        if after != before.strip():
            profile_after = after
            changes.append({"key": "interest_profile", "label": "興趣設定檔", "before": before, "after": after})
    if answers.analysis_depth is not None:
        setting("ANALYSIS_DEPTH", "分析深度", answers.analysis_depth)

    existing = {_url_key(s["source_type"], s["url"]): s for s in get_all_radar_sources()}
    add, reactivate, unchanged, seen = [], [], [], set()
    for src in answers.sources:
        key = _url_key(src.source_type, src.url)
        if key in seen:
            continue
        seen.add(key)
        entry = {"name": src.name, "source_type": src.source_type, "url": src.url, "pack": src.pack, "tier": src.tier}
        current = existing.get(key)
        if current is None:
            add.append(entry)
        elif not current.get("is_active"):
            reactivate.append({**entry, "id": current["id"]})
        else:
            unchanged.append({**entry, "id": current["id"]})

    radar_before = get_radar_settings()
    radar_after: Dict[str, Any] = {}
    if answers.stage == "first":
        enabled = answers.radar.enabled if answers.radar and answers.radar.enabled is not None else None
        if enabled is None and (add or reactivate or unchanged):
            enabled = True  # picked a pack: the radar starts (design §2 step 6)
        if enabled is not None:
            radar_after["enabled"] = enabled
        if answers.radar and answers.radar.interval_minutes is not None:
            radar_after["interval_minutes"] = answers.radar.interval_minutes
    if answers.notifications is not None:
        radar_after["notification_mode"] = answers.notifications.mode
        if answers.notifications.daily_digest_hour is not None:
            radar_after["daily_digest_hour"] = answers.notifications.daily_digest_hour
    labels = {"enabled": "雷達開關", "interval_minutes": "巡檢間隔（分鐘）",
              "notification_mode": "通知方式", "daily_digest_hour": "每日摘要時間（點）"}
    radar_changes = {}
    for key, value in radar_after.items():
        if radar_before.get(key) != value:
            radar_changes[key] = value
            changes.append({"key": f"radar.{key}", "label": labels[key], "before": radar_before.get(key), "after": value})

    ai_order = None
    if answers.ai_order is not None:
        from app import ai_connections
        labels_by_id = {c.id: c.label for c in ai_connections.list_connections()}
        unknown = [i for i in answers.ai_order if i not in labels_by_id]
        if unknown:
            raise SetupError(f"ai_order 裡的連線不存在：{unknown}；先用 omnikeep_list_provider_options 看 current.connections")
        if len(set(answers.ai_order)) != len(answers.ai_order):
            raise SetupError("ai_order 裡有重複的連線")
        before_ids = [e["connection_id"] for e in ai_connections.slots()["analysis"]]
        if answers.ai_order and answers.ai_order != before_ids:
            ai_order = list(answers.ai_order)
            changes.append({"key": "ai.analysis", "label": "分析用的 AI 管道（主要，再依序備援）",
                            "before": [labels_by_id.get(i, str(i)) for i in before_ids],
                            "after": [labels_by_id[i] for i in ai_order]})

    warnings: List[str] = []
    if answers.notifications is not None:
        state = _channel_state()
        chosen = answers.notifications.channels
        if answers.notifications.mode != "silent" and not chosen:
            warnings.append("選了要送通知但沒選管道（web_push、telegram、line）")
        if "telegram" in chosen and not state["telegram"]:
            warnings.append("Telegram 還沒設定 Bot Token：請使用者到設定頁的 Telegram 分頁貼上，再用配對連結綁定")
        if "line" in chosen and not state["line"]:
            warnings.append("LINE 還沒設定 Channel Access Token：請使用者到設定頁的 LINE 分頁貼上")
        if "web_push" in chosen and not state["web_push"]:
            warnings.append("網頁推播還沒有裝置訂閱：請使用者打開 OmniKeep，在推播設定按「允許」")
    if add:
        changes.append({"key": "radar.sources", "label": "新增雷達來源", "before": None,
                        "after": [f"{s['name']}（{s['source_type']}）" for s in add]})
    if reactivate:
        changes.append({"key": "radar.sources.reactivate", "label": "重新啟用雷達來源", "before": None,
                        "after": [f"{s['name']}（{s['source_type']}）" for s in reactivate]})

    plan = {
        "stage": answers.stage,
        "changes": changes,
        "sources": {"add": add, "reactivate": reactivate, "unchanged": unchanged},
        "warnings": warnings,
        "_apply": {"settings": settings_values, "profile": profile_after, "radar": radar_changes,
                   "ai_order": ai_order},
    }
    # Same answers against the same state give the same code; any change in between does not.
    digest = hashlib.sha256(json.dumps({"answers": answers.model_dump(mode="json"), "plan": plan},
                                       ensure_ascii=False, sort_keys=True, default=str).encode()).hexdigest()
    plan["confirm_code"] = digest[:6].upper()
    return plan


def _public_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    out = {k: v for k, v in plan.items() if not k.startswith("_")}
    out["has_changes"] = bool(plan["changes"])
    return out


def preview(answers: Any) -> Dict[str, Any]:
    refresh_settings()
    parsed = parse_answers(answers)
    plan = _public_plan(build_plan(parsed))
    plan["ai"] = ai_summary() if parsed.stage == "first" else None
    plan["next"] = ("把 changes 原樣給使用者看，問「照這樣設定嗎？」；同意後呼叫 omnikeep_apply_setup，"
                    f"帶同一份答案與確認碼 {plan['confirm_code']}。")
    return plan


def apply(answers: Any, confirm_code: str) -> Dict[str, Any]:
    """Write the previewed plan. Runs inside the service (routers/setup.py)."""
    from app import app_settings
    from app.database import save_radar_source, set_interest_profile, toggle_radar_source_active, update_radar_settings

    parsed = parse_answers(answers)
    plan = build_plan(parsed)
    if (confirm_code or "").strip().upper() != plan["confirm_code"]:
        raise SetupError("確認碼不符：答案跟預覽時不同，或設定在預覽後改過了。請重新呼叫 omnikeep_preview_setup。")
    todo = plan["_apply"]
    if todo["settings"]:
        try:
            app_settings.save(todo["settings"])
        except app_settings.SettingsError as exc:
            raise SetupError("；".join(exc.errors.values()) or "設定有誤") from exc
    if todo["profile"] is not None:
        set_interest_profile(todo["profile"])
    added = []
    for src in plan["sources"]["add"]:
        added.append(save_radar_source({"name": src["name"], "source_type": src["source_type"], "url": src["url"],
                                        "tier": src["tier"], "check_interval_minutes": 60, "is_active": 1}))
    for src in plan["sources"]["reactivate"]:
        toggle_radar_source_active(src["id"], is_active=True)
    if todo["radar"]:
        update_radar_settings(**todo["radar"])
    if todo["ai_order"]:
        from app import ai_connections
        try:
            ai_connections.set_slots({"analysis": todo["ai_order"]})
        except ai_connections.AIConfigError as exc:
            raise SetupError("；".join(exc.errors.values()) or "AI 管道順序有誤") from exc

    previous = read_last_answers() or {}
    record = parsed.model_dump(mode="json", exclude_none=True)
    if parsed.stage == "followup":
        record = {**previous, **{k: v for k, v in record.items() if k != "stage"}}
    record["applied_at"] = datetime.now(timezone.utc).isoformat()
    _write_last_answers(record)
    return {"applied": True, "stage": parsed.stage, "changes": plan["changes"],
            "added_source_ids": added, "warnings": plan["warnings"]}


# ── omnikeep_run_radar (service side) ───────────────────────────

async def run_radar_once(max_digest_items: int = 20) -> Dict[str, Any]:
    """One forced radar cycle, then a radar digest of what it found (design §2 step 8)."""
    from app.database import get_radar_items_updated_since
    from app.radar.digest import generate_radar_digest
    from app.radar.scheduler import run_radar_cycle

    result = await run_radar_cycle(force=True, auto_digest=False)
    ids = list(result.get("ranked_items") or result.get("new_items") or [])
    basis = "this_cycle"
    if not ids:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        ids = [item["id"] for item in get_radar_items_updated_since(since, limit=max_digest_items)]
        basis = "last_7_days"
    digest = None
    if ids:
        made = await generate_radar_digest(ids[:max_digest_items], digest_type="custom")
        if made.get("success"):
            digest = {k: made.get(k) for k in ("digest_id", "title", "markdown_content", "item_count")}
    return {
        "sources_scanned": result.get("sources_scanned", 0),
        "new_items_count": result.get("new_items_count", 0),
        "deferred_count": result.get("deferred_count", 0),
        "digest_basis": basis if digest else None,
        "digest": digest,
        "message": None if digest else "這次沒有抓到可整理的項目：確認雷達來源已啟用，或稍後再跑一次",
    }


# ── omnikeep_import ─────────────────────────────────────────────

def parse_opml(content: str, limit: int = 200) -> List[Dict[str, str]]:
    """Feeds listed in an OPML file: [{"name", "url"}], at most `limit`."""
    import xml.etree.ElementTree as ET
    if "<!DOCTYPE" in content.upper() or "<!ENTITY" in content.upper():
        raise SetupError("OPML 檔不能包含 DOCTYPE 或 ENTITY 宣告")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise SetupError(f"OPML 解析失敗：{exc}") from exc
    feeds, seen = [], set()
    for node in root.iter("outline"):
        url = (node.get("xmlUrl") or "").strip()
        if not url.lower().startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        feeds.append({"name": (node.get("title") or node.get("text") or url).strip()[:120], "url": url})
        if len(feeds) >= limit:
            break
    return feeds


def import_opml(content: str) -> Dict[str, Any]:
    """Save an OPML file's feeds as RSS radar sources (service side); existing URLs are skipped."""
    from app.database import get_all_radar_sources, get_radar_settings, save_radar_source
    feeds = parse_opml(content)
    existing = {_url_key(s["source_type"], s["url"]) for s in get_all_radar_sources()}
    added, skipped = [], 0
    for feed in feeds:
        if _url_key("rss", feed["url"]) in existing:
            skipped += 1
            continue
        added.append(save_radar_source({"name": feed["name"], "source_type": "rss", "url": feed["url"],
                                        "tier": 2, "check_interval_minutes": 60, "is_active": 1}))
    return {"kind": "opml", "total_parsed": len(feeds), "added_count": len(added), "skipped_count": skipped,
            "note": "來源已加入雷達，但雷達目前關閉，不會巡檢" if added and not get_radar_settings()["enabled"] else None}


def _read_file(path: str) -> Tuple[str, str]:
    file = Path(path).expanduser()
    if not file.is_file():
        raise SetupError(f"找不到檔案：{file}")
    if file.stat().st_size > MAX_IMPORT_BYTES:
        raise SetupError("檔案超過 20 MB")
    raw = file.read_bytes()
    try:
        return raw.decode("utf-8-sig"), file.name
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace"), file.name


def _browser_bookmarks(browser: str, profile: str = "") -> Tuple[str, str]:
    files = [f for f in _bookmark_files() if f[0] == browser]
    if profile:
        files = [f for f in files if f[1] == profile]
    if not files:
        raise SetupError(f"這台電腦找不到 {browser} 的書籤檔" + (f"（設定檔 {profile}）" if profile else ""))
    chosen = next((f for f in files if f[1] == "Default"), files[0])
    return chosen[2].read_text(encoding="utf-8"), f"{browser}-{chosen[1]}-bookmarks.json"


def _github_stars(limit: int) -> List[Dict[str, Any]]:
    gh = _github_cli()
    if not gh["installed"]:
        raise SetupError("沒有安裝 GitHub CLI（gh）")
    if not gh["logged_in"]:
        raise SetupError("GitHub CLI 還沒登入：請使用者在終端機執行 gh auth login")
    code, out = _run(["gh", "api", "user/starred", "--paginate", "--jq",
                      ".[] | {title: .full_name, url: .html_url, tags: .topics}"], 120.0)
    if code != 0:
        raise SetupError("讀取 GitHub 星標失敗（gh api user/starred）")
    stars = []
    for line in out.splitlines():
        try:
            star = json.loads(line)
        except ValueError:
            continue
        stars.append({**star, "folder": "GitHub Stars"})
        if len(stars) >= limit:
            break
    return stars


async def import_data(kind: str, path: str = "", browser: str = "", profile: str = "",
                      enqueue_ai: bool = False, limit: int = 1000) -> Dict[str, Any]:
    """Bookmarks, GitHub stars or OPML; reads locally, writes through the service."""
    kind = (kind or "").strip().lower()
    limit = max(1, min(int(limit), 5000))
    if kind == "opml":
        if not path:
            raise SetupError("OPML 要給檔案路徑 path")
        content, _ = await asyncio.to_thread(_read_file, path)
        return await call_service("POST", "/api/setup/import-opml", json_body={"content": content}, timeout=60.0)
    if kind == "bookmarks":
        if path:
            content, filename = await asyncio.to_thread(_read_file, path)
        elif browser in ("chrome", "edge"):
            content, filename = await asyncio.to_thread(_browser_bookmarks, browser, profile)
        else:
            raise SetupError("書籤要給檔案路徑 path，或 browser=chrome／edge")
    elif kind == "github_stars":
        stars = await asyncio.to_thread(_github_stars, limit)
        content, filename = json.dumps({"bookmarks": stars}, ensure_ascii=False), "github-stars.json"
    else:
        raise SetupError("kind 只能是 bookmarks、github_stars、opml")
    result = await call_service("POST", "/api/items/import/bookmarks",
                                json_body={"content": content, "filename": filename, "enqueue_ai": bool(enqueue_ai)},
                                timeout=300.0)
    result.pop("sample_ids", None)
    return {"kind": kind, **result}


# ── omnikeep_ingest ─────────────────────────────────────────────

async def ingest(url: str) -> Dict[str, Any]:
    url = (url or "").strip()
    if not url:
        raise SetupError("請給要分析的網址")
    result = await call_service("POST", "/api/ingest", json_body={"url": url}, timeout=600.0)
    item = result.get("item") or {}
    analysis = item.get("deep_analysis") or ""
    return {
        "id": item.get("id"),
        "url": item.get("url"),
        "title": item.get("title_l1"),
        "category": item.get("category_name"),
        "tags": item.get("tech_tags") or [],
        "summary": item.get("summary_l1"),
        "deep_analysis": analysis[:6000],
        "deep_analysis_truncated": len(analysis) > 6000,
    }
