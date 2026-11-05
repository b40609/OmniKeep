"""Agent-driven setup (app/setup_flow.py, routers/setup.py, the omnikeep_* MCP tools).

HTTP is stubbed throughout: the in-process service runs on httpx.ASGITransport and
public fetches on httpx.MockTransport, so the conftest network guard never fires.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app import setup_flow
from app.config import settings
from app.database import (get_all_radar_sources, get_interest_profile, get_radar_settings,
                          get_radar_source, radar_fetch_meta_disabled, save_radar_source,
                          set_interest_profile, update_radar_source_fetch_meta)


@pytest.fixture
def service():
    """The setup tools call the app's routes in-process, as inside the running service."""
    from app.main import app
    setup_flow.bind_in_process(app)
    yield app
    setup_flow.unbind_in_process()


def _first_answers(**extra):
    answers = {
        "stage": "first",
        "about_you": "資料工程師\n在做個人記帳 App",
        "interest_profile": "關注本機 LLM 推論、資料工程與 Rust。",
        "topics": ["本機 LLM", "資料工程"],
        "sources": [
            {"name": "Example Blog", "source_type": "rss", "url": "https://blog.example/feed.xml", "pack": "資料工程"},
            {"name": "ollama", "source_type": "github", "url": "https://github.com/ollama/ollama", "pack": "本機 LLM"},
        ],
    }
    answers.update(extra)
    return answers


# ── pipeline.parse_url: parse without analyzing ─────────────────

async def test_parse_url_light_keeps_reels_to_metadata(monkeypatch):
    from app import pipeline

    async def no_reel(url):
        raise AssertionError("light mode must not download the clip or call vision/STT")

    async def page(url):
        return {"title": "Reel page", "content_raw": "caption", "author": "someone", "meta": {}}

    monkeypatch.setattr(pipeline, "parse_video_reel", no_reel)
    monkeypatch.setattr(pipeline, "parse_web_page", page)
    parsed = await pipeline.parse_url("https://www.instagram.com/reel/abc123/", light=True)
    assert parsed["kind"] == "web" and parsed["source_type"] == "reel"
    assert parsed["title"] == "Reel page" and parsed["content_raw"] == "caption"


async def test_parse_url_prefers_the_browser_title_for_web_pages(monkeypatch):
    from app import pipeline

    async def page(url):
        return {"title": "未知標題", "content_raw": "body", "meta": {"raw_html": "<html></html>"}}

    monkeypatch.setattr(pipeline, "parse_web_page", page)
    parsed = await pipeline.parse_url("https://example.com/post", page_title="Real title",
                                      page_description="desc")
    assert parsed["title"] == "Real title" and parsed["original_title"] == "未知標題"
    assert parsed["fallback_summary"] == "desc" and parsed["raw_html"] == "<html></html>"


async def test_peek_returns_an_excerpt_without_ai_or_saving(monkeypatch):
    from app import pipeline
    from app.database import get_status_counts

    async def page(url):
        return {"title": "A post", "content_raw": "x" * 5000, "author": "Ann", "meta": {}}

    monkeypatch.setattr(pipeline, "parse_web_page", page)
    monkeypatch.setattr(pipeline, "get_primary_provider",
                        lambda: (_ for _ in ()).throw(AssertionError("no AI in peek")))
    before = get_status_counts()
    result = await setup_flow.peek("https://example.com/post", max_chars=1000)
    assert result["title"] == "A post" and result["author"] == "Ann"
    assert len(result["excerpt"]) == 1000 and result["truncated"] and result["length"] == 5000
    assert get_status_counts() == before
    with pytest.raises(setup_flow.SetupError):
        await setup_flow.peek("ftp://example.com/x")


# ── check_sources: trial fetch, RSS discovery, no bookkeeping ───

def _feed_xml(count=5):
    now = datetime.now(timezone.utc)
    entries = "".join(
        f"<item><title>Post {i}</title><link>https://blog.example/p{i}</link>"
        f"<pubDate>{(now - timedelta(days=3 * i)).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>"
        for i in range(count))
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>Example Blog</title>{entries}</channel></rss>"


@pytest.fixture
def public_web(monkeypatch):
    pages = {
        "https://blog.example/": (200, "text/html",
                                  "<html><head><link rel='alternate' type='application/rss+xml' "
                                  "href='/feed.xml'></head><body>home</body></html>"),
        "https://blog.example/feed.xml": (200, "application/rss+xml", _feed_xml()),
        "https://nofeed.example/": (200, "text/html", "<html><body>no feed here</body></html>"),
    }

    def handler(request):
        status, kind, body = pages.get(str(request.url), (404, "text/plain", "missing"))
        return httpx.Response(status, headers={"content-type": kind}, text=body)

    def client(**kwargs):
        kwargs.pop("transport", None)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)

    import app.network
    import app.radar.adapters.rss as rss
    monkeypatch.setattr(app.network, "public_http_client", client)
    monkeypatch.setattr(rss, "public_http_client", client)
    return pages


async def test_check_sources_finds_the_feed_from_a_home_page(public_web):
    before = len(get_all_radar_sources())
    result = await setup_flow.check_sources([{"url": "https://blog.example/"},
                                             {"url": "https://nofeed.example/"}])
    good, missing = result["results"]
    assert result["ok_count"] == 1
    assert good["ok"] and good["source_type"] == "rss" and good["discovered_feed"]
    assert good["url"] == "https://blog.example/feed.xml" and good["name"] == "Example Blog"
    assert good["recent_titles"] == ["Post 0", "Post 1", "Post 2"]
    assert good["latest_date"] and good["per_week"] > 0
    assert not missing["ok"] and missing["suggested_source_type"] == "web_change"
    assert len(get_all_radar_sources()) == before  # nothing saved


def test_fetch_bookkeeping_is_skipped_only_inside_the_check_context():
    source_id = save_radar_source({"name": "s", "source_type": "rss", "url": "https://x.example/feed"})
    with radar_fetch_meta_disabled():
        update_radar_source_fetch_meta(source_id, last_fetched_at="2026-01-01T00:00:00+00:00")
    assert get_radar_source(source_id)["last_fetched_at"] in (None, "")
    update_radar_source_fetch_meta(source_id, last_fetched_at="2026-01-02T00:00:00+00:00")
    assert get_radar_source(source_id)["last_fetched_at"] == "2026-01-02T00:00:00+00:00"


async def test_check_sources_limits_and_validates_input():
    with pytest.raises(setup_flow.SetupError):
        await setup_flow.check_sources([])
    with pytest.raises(setup_flow.SetupError):
        await setup_flow.check_sources([{"url": f"https://e{i}.example/"} for i in range(21)])
    result = await setup_flow.check_sources([{"url": "https://e.example/", "source_type": "telnet"}])
    assert not result["results"][0]["ok"] and "不支援" in result["results"][0]["error"]


def test_source_types_match_the_registered_adapters():
    from app.radar.adapters import supported_source_types
    assert set(setup_flow.SOURCE_TYPES) == set(supported_source_types())


def test_guess_source_type():
    assert setup_flow.guess_source_type("https://www.youtube.com/@chan") == "youtube"
    assert setup_flow.guess_source_type("https://github.com/ollama/ollama") == "github"
    assert setup_flow.guess_source_type("本機 LLM") == "google_news"
    assert setup_flow.guess_source_type("https://blog.example/") == "rss"


# ── preview and apply ───────────────────────────────────────────

async def test_preview_then_apply_writes_through_the_service(service):
    preview = await setup_flow.call_service("POST", "/api/setup/preview", json_body={"answers": _first_answers()})
    keys = {c["key"] for c in preview["changes"]}
    assert {"USER_BACKGROUND", "interest_profile", "radar.sources", "radar.enabled"} <= keys
    assert preview["has_changes"] and len(preview["confirm_code"]) == 6
    assert preview["ai"]["api_key"] == {"configured": False, "hint": ""}

    with pytest.raises(setup_flow.ServiceError) as wrong:
        await setup_flow.call_service("POST", "/api/setup/apply",
                                      json_body={"answers": _first_answers(), "confirm_code": "000000"})
    assert wrong.value.status == 400 and "確認碼" in str(wrong.value)
    assert not get_radar_settings()["enabled"]

    applied = await setup_flow.call_service("POST", "/api/setup/apply", json_body={
        "answers": _first_answers(), "confirm_code": preview["confirm_code"].lower()})
    assert applied["applied"] and len(applied["added_source_ids"]) == 2
    assert settings.USER_BACKGROUND == "資料工程師 在做個人記帳 App"  # one line, as the setting requires
    assert get_interest_profile() == "關注本機 LLM 推論、資料工程與 Rust。"
    assert get_radar_settings()["enabled"] is True
    urls = {s["url"] for s in get_all_radar_sources(only_active=True)}
    assert {"https://blog.example/feed.xml", "https://github.com/ollama/ollama"} <= urls

    again = await setup_flow.call_service("POST", "/api/setup/preview", json_body={"answers": _first_answers()})
    assert not again["has_changes"] and len(again["sources"]["unchanged"]) == 2
    assert setup_flow.read_last_answers()["topics"] == ["本機 LLM", "資料工程"]


async def test_apply_is_refused_when_the_state_changed_after_the_preview(service):
    preview = await setup_flow.call_service("POST", "/api/setup/preview", json_body={"answers": _first_answers()})
    set_interest_profile("改過了")
    with pytest.raises(setup_flow.ServiceError, match="重新呼叫"):
        await setup_flow.call_service("POST", "/api/setup/apply", json_body={
            "answers": _first_answers(), "confirm_code": preview["confirm_code"]})
    assert get_interest_profile() == "改過了"


async def test_second_run_changes_only_depth_and_notifications(service, monkeypatch):
    with pytest.raises(setup_flow.ServiceError, match="只改分析深度與通知"):
        await setup_flow.call_service("POST", "/api/setup/preview", json_body={"answers": {
            "stage": "followup", "analysis_depth": "concise", "sources": _first_answers()["sources"]}})
    with pytest.raises(setup_flow.ServiceError, match="daily_digest_hour"):
        await setup_flow.call_service("POST", "/api/setup/preview", json_body={"answers": {
            "stage": "followup", "notifications": {"mode": "daily_digest"}}})

    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "")
    answers = {"stage": "followup", "analysis_depth": "concise",
               "notifications": {"mode": "daily_digest", "daily_digest_hour": 21, "channels": ["telegram"]}}
    preview = await setup_flow.call_service("POST", "/api/setup/preview", json_body={"answers": answers})
    assert {c["key"] for c in preview["changes"]} == {"ANALYSIS_DEPTH", "radar.notification_mode",
                                                      "radar.daily_digest_hour"}
    assert any("Telegram" in w for w in preview["warnings"]) and preview["ai"] is None
    await setup_flow.call_service("POST", "/api/setup/apply",
                                  json_body={"answers": answers, "confirm_code": preview["confirm_code"]})
    assert settings.ANALYSIS_DEPTH == "concise"
    radar = get_radar_settings()
    assert radar["notification_mode"] == "daily_digest" and radar["daily_digest_hour"] == 21
    assert setup_flow.read_last_answers()["analysis_depth"] == "concise"


def test_answers_schema_rejects_unknown_fields_and_types():
    with pytest.raises(setup_flow.SetupError, match="答案格式有誤"):
        setup_flow.parse_answers({"stage": "first", "api_key": "x"})
    with pytest.raises(setup_flow.SetupError, match="source_type"):
        setup_flow.parse_answers({"sources": [{"name": "a", "source_type": "ftp", "url": "x"}]})
    with pytest.raises(setup_flow.SetupError):
        setup_flow.parse_answers("not json")


# ── MCP tools ───────────────────────────────────────────────────

async def test_mcp_preview_and_apply_tools(service):
    from app import mcp_server
    preview = json.loads(await mcp_server.omnikeep_preview_setup(_first_answers()))
    applied = json.loads(await mcp_server.omnikeep_apply_setup(_first_answers(), preview["confirm_code"]))
    assert applied["applied"] is True
    refused = json.loads(await mcp_server.omnikeep_apply_setup(_first_answers(), "ZZZZZZ"))
    assert refused["ok"] is False and "確認碼" in refused["error"]


async def test_writing_tools_need_the_running_service(monkeypatch):
    from app import mcp_server

    async def down(*args, **kwargs):
        raise setup_flow.ServiceUnavailable("連不上 OmniKeep 服務")

    monkeypatch.setattr(setup_flow, "call_service", down)
    for result in (await mcp_server.omnikeep_apply_setup(_first_answers(), "ABCDEF"),
                   await mcp_server.omnikeep_ingest("https://example.com/a"),
                   await mcp_server.omnikeep_run_radar()):
        assert json.loads(result) == {"ok": False, "error": "連不上 OmniKeep 服務"}
    # The read-only preview still works from the database.
    preview = json.loads(await mcp_server.omnikeep_preview_setup(_first_answers()))
    assert preview["confirm_code"] and "服務沒在跑" in preview["note"]


async def test_provider_tools_use_the_flat_settings_until_the_catalog_exists(service, monkeypatch):
    from app import mcp_server
    from app.connection_checks import CHECKS

    secret = "sk-test-not-a-real-key-WXYZ"
    monkeypatch.setattr(settings, "OPENAI_API_KEY", secret)

    async def fake_check(values):
        return {"ok": True, "status": 200, "message": "連線成功", "detail": ""}

    monkeypatch.setitem(CHECKS, "llm", fake_check)
    options = await mcp_server.omnikeep_list_provider_options()
    assert secret not in options
    parsed = json.loads(options)
    assert parsed["source"] == "builtin" and {o["id"] for o in parsed["options"]} >= {"agnes", "gemini", "ollama"}
    assert parsed["current"]["api_key"] == {"configured": True, "hint": "…WXYZ"}
    tested = json.loads(await mcp_server.omnikeep_test_provider("llm"))
    assert tested["ok"] is True
    unknown = json.loads(await mcp_server.omnikeep_test_provider("nope"))
    assert unknown["ok"] is False
    link = json.loads(await mcp_server.omnikeep_open_settings("agnes", "ai"))
    assert link["url"].endswith("/#settings=ai&card=agnes") and secret not in json.dumps(link)


async def test_scan_reports_counts_and_never_keys(service, monkeypatch, isolated_runtime):
    secret = "sk-test-not-a-real-key-WXYZ"
    monkeypatch.setattr(settings, "OPENAI_API_KEY", secret)
    bookmarks = isolated_runtime / "Bookmarks"
    bookmarks.write_text(json.dumps({"roots": {"bookmark_bar": {"children": [
        {"type": "url", "name": "private title", "url": "https://a.example"},
        {"type": "folder", "children": [{"type": "url", "name": "t2", "url": "https://b.example"}]}]}}}),
        encoding="utf-8")
    monkeypatch.setattr(setup_flow, "_bookmark_files", lambda: [("chrome", "Default", bookmarks)])

    def fake_run(cmd, timeout=10.0):
        if cmd[:3] == ["gh", "auth", "status"]:
            return 0, ""
        if cmd[:3] == ["gh", "api", "graphql"]:
            return 0, "42\n"
        return -1, ""

    async def no_ollama():
        return {"ollama": {"url": "http://127.0.0.1:11434", "running": False, "models": []}}

    monkeypatch.setattr(setup_flow, "_run", fake_run)
    monkeypatch.setattr(setup_flow.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(setup_flow, "_local_inference", no_ollama)
    result = await setup_flow.scan()
    text = json.dumps(result, ensure_ascii=False)
    assert secret not in text and "private title" not in text and "a.example" not in text
    assert result["bookmarks"] == [{"browser": "chrome", "profile": "Default", "count": 2}]
    assert result["github"] == {"installed": True, "logged_in": True, "starred": 42}
    assert result["omnikeep"]["service_running"] is True
    assert result["ai"]["api_key"]["hint"] == "…WXYZ"


# ── import, ingest, run_radar ───────────────────────────────────

OPML = """<?xml version="1.0"?><opml version="2.0"><body>
<outline text="Tech"><outline text="Example Blog" type="rss" xmlUrl="https://blog.example/feed.xml"/>
<outline title="Other" xmlUrl="https://other.example/rss"/></outline></body></opml>"""


async def test_import_opml_adds_radar_sources_once(service, isolated_runtime):
    path = isolated_runtime / "feeds.opml"
    path.write_text(OPML, encoding="utf-8")
    first = await setup_flow.import_data("opml", path=str(path))
    second = await setup_flow.import_data("opml", path=str(path))
    assert first["added_count"] == 2 and second == {**second, "added_count": 0, "skipped_count": 2}
    with pytest.raises(setup_flow.SetupError, match="DOCTYPE"):
        setup_flow.parse_opml('<!DOCTYPE x [<!ENTITY a "b">]><opml/>')


async def test_import_bookmarks_and_github_stars_store_links_only(service, monkeypatch, isolated_runtime):
    from app.database import get_items
    path = isolated_runtime / "bookmarks.json"
    path.write_text(json.dumps([{"title": "Saved", "url": "https://saved.example/a"}]), encoding="utf-8")
    result = await setup_flow.import_data("bookmarks", path=str(path))
    assert result["imported_count"] == 1 and result["queued_count"] == 0

    monkeypatch.setattr(setup_flow, "_github_cli", lambda: {"installed": True, "logged_in": True, "starred": 1})
    monkeypatch.setattr(setup_flow, "_run", lambda cmd, timeout=10.0: (
        0, json.dumps({"title": "ollama/ollama", "url": "https://github.com/ollama/ollama", "tags": ["llm"]}) + "\n"))
    stars = await setup_flow.import_data("github_stars")
    assert stars["kind"] == "github_stars" and stars["imported_count"] == 1
    urls = {i["url"] for i in get_items(limit=50)}
    assert {"https://saved.example/a", "https://github.com/ollama/ollama"} <= urls

    monkeypatch.setattr(setup_flow, "_github_cli", lambda: {"installed": True, "logged_in": False, "starred": None})
    with pytest.raises(setup_flow.SetupError, match="gh auth login"):
        await setup_flow.import_data("github_stars")


async def test_ingest_tool_goes_through_the_ingest_route(service, monkeypatch):
    import app.routers.ingest as ingest_route

    async def fake_pipeline(content, category=None, **kwargs):
        return {"id": "it_1", "url": content, "title_l1": "標題", "category_name": "Inbox",
                "tech_tags": ["LLM"], "summary_l1": "摘要", "deep_analysis": "## 分析"}

    monkeypatch.setattr(ingest_route, "run_pipeline", fake_pipeline)
    result = await setup_flow.ingest("https://example.com/post")
    assert result["id"] == "it_1" and result["deep_analysis"] == "## 分析"


async def test_run_radar_once_builds_a_digest(service, monkeypatch):
    import app.radar.digest as digest
    import app.radar.scheduler as scheduler
    calls = {}

    async def cycle(force=False, auto_digest=True):
        calls["cycle"] = (force, auto_digest)
        return {"sources_scanned": 3, "new_items_count": 2, "new_items": ["a", "b"],
                "ranked_items": ["b", "a"], "deferred_count": 1}

    async def make(ids, digest_type="evening"):
        calls["digest"] = (ids, digest_type)
        return {"success": True, "digest_id": "d1", "title": "雷達", "markdown_content": "# 摘要", "item_count": 2}

    monkeypatch.setattr(scheduler, "run_radar_cycle", cycle)
    monkeypatch.setattr(digest, "generate_radar_digest", make)
    result = await setup_flow.call_service("POST", "/api/setup/run-radar")
    assert calls == {"cycle": (True, False), "digest": (["b", "a"], "custom")}
    assert result["digest"]["markdown_content"] == "# 摘要" and result["digest_basis"] == "this_cycle"


# ── transports ──────────────────────────────────────────────────

def test_stdio_import_leaves_the_heavy_modules_unloaded():
    env = {**os.environ, "OMNIKEEP_TESTING": "1"}
    code = ("import sys, app.mcp_server; "
            "print([m for m in ('app.pipeline', 'app.providers', 'app.vector', 'openai', 'app.setup_flow') "
            "if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                         cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))), timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "[]"


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def test_streamable_http_needs_the_key_and_an_allowed_host(monkeypatch):
    from fastapi.testclient import TestClient
    from app import mcp_http
    from app.main import app

    security = mcp_http.mcp.settings.transport_security
    monkeypatch.setattr(security, "allowed_hosts", list(security.allowed_hosts))
    monkeypatch.setattr(security, "allowed_origins", list(security.allowed_origins))
    monkeypatch.setattr(mcp_http, "_remote", [])
    auth = {**MCP_HEADERS, "Authorization": f"Bearer {settings.API_KEY}"}
    with TestClient(app, base_url="http://127.0.0.1:5000") as client:
        assert client.post("/mcp-http", json=INIT, headers=MCP_HEADERS).status_code == 401
        ok = client.post("/mcp-http", json=INIT, headers=auth)
        assert ok.status_code == 200 and ok.headers.get("mcp-session-id")
        session = {**auth, "mcp-session-id": ok.headers["mcp-session-id"], "mcp-protocol-version": "2025-06-18"}
        client.post("/mcp-http", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers=session)
        listed = client.post("/mcp-http", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers=session)
        tools = {t["name"] for t in json.loads(listed.text.split("data: ", 1)[1])["result"]["tools"]}
        assert {"omnikeep_scan", "omnikeep_peek", "omnikeep_check_sources", "omnikeep_list_provider_options",
                "omnikeep_open_settings", "omnikeep_test_provider", "omnikeep_preview_setup",
                "omnikeep_apply_setup", "omnikeep_ingest", "omnikeep_run_radar", "omnikeep_import"} <= tools
    with TestClient(app, base_url="http://box.tail1234.ts.net") as client:
        assert client.post("/mcp-http", json=INIT, headers=auth).status_code == 421
        mcp_http.allow_hosts(["box.tail1234.ts.net."])
        assert client.post("/mcp-http", json=INIT, headers=auth).status_code == 200
    assert mcp_http.remote_hosts() == ["box.tail1234.ts.net"]


def test_streamable_http_without_a_running_session_manager_answers_503():
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app, base_url="http://127.0.0.1:5000")  # no lifespan
    resp = client.post("/mcp-http", json=INIT, headers={**MCP_HEADERS, "Authorization": f"Bearer {settings.API_KEY}"})
    assert resp.status_code == 503


async def test_stdio_server_answers_a_tool_that_loads_the_pipeline():
    """Windows: numpy imported lazily while the stdio reader blocks on stdin used to hang."""
    import asyncio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params = StdioServerParameters(command=sys.executable, args=[os.path.join(root, "mcp_server.py")],
                                   env={**os.environ, "OMNIKEEP_TESTING": "1"}, cwd=root)

    async def run():
        with open(os.devnull, "w") as quiet:
            async with stdio_client(params, errlog=quiet) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    # peek imports app.pipeline (and with it numpy) before rejecting the scheme.
                    result = await session.call_tool("omnikeep_peek", {"url": "ftp://example.com/x"})
                    return json.loads(result.content[0].text)

    answer = await asyncio.wait_for(run(), timeout=60)
    assert answer["ok"] is False and "http" in answer["error"]
