"""A fresh install has no AI connection: a link is still saved, as "not analysed yet".

Before: the ingest API answered 502 "AI 分析失敗：金鑰無效…" and saved nothing, because the
pipeline called the default OpenAI address with an empty key (which also sent the page's text
to a third party). Now nothing is sent to any AI; title, address, cover and the fetched text
are stored, tagged "（尚未分析）", and analysed once a connection exists.

An AI that is set up but fails (rate limit, timeout) is a different case and keeps its old
behaviour: nothing is saved, the caller is told why, the queue retries.
"""
from unittest.mock import AsyncMock, patch

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app import ai_connections, database as db, error_translate, pipeline, providers, refetch
from app.config import settings
from app.main import app
from app.providers.base import NoAIConnectionError, UnconfiguredProvider
from app.queue.worker import TaskWorker

URL = "https://example.com/article"
HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}
TEXT = "Retry queues keep a failed job and run it again later. " * 30
PAGE = {"url": URL, "title": "Retry queues explained", "content_raw": f"# Retry queues explained\n\n{TEXT}",
        "cover_image": "https://example.com/cover.png", "author": "", "published_date": "", "raw_html": "",
        "http_status": 200}
GOOD = {"category": "Inbox", "title_l1": "佇列的重試機制", "summary_l1": "這篇在講佇列的重試。", "tech_tags": ["Queue"],
        "deep_analysis": "## 重點\n- 重試", "is_composite": False, "sub_entities": []}


@pytest.fixture(autouse=True)
def fresh_install(monkeypatch):
    """The settings of a new install: the default OpenAI address, no key, no connection."""
    monkeypatch.setattr(settings, "PRIMARY_LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS_RAW", "")
    providers.reset_providers()
    refetch._analysis_failures.clear()
    yield
    providers.reset_providers()
    refetch._analysis_failures.clear()


@pytest.fixture
def web_page():
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=dict(PAGE))):
        yield


@pytest.fixture
def no_ai_requests(monkeypatch):
    """Any request an AI client would send fails the test (the conftest guard also refuses
    the connection itself; this names the call that tried)."""
    from app.providers.gemini import GeminiProvider
    from app.providers.openai_compatible import OpenAICompatibleProvider
    calls = []

    async def refuse(self, *args, **kwargs):
        calls.append(type(self).__name__)
        raise AssertionError("an AI provider was called on an install with no AI connection")

    for cls in (OpenAICompatibleProvider, GeminiProvider):
        monkeypatch.setattr(cls, "generate_json", refuse)
        monkeypatch.setattr(cls, "generate_text", refuse)
    monkeypatch.setattr(OpenAICompatibleProvider, "_chat", refuse)
    monkeypatch.setattr("app.vector._remote_embedding", AsyncMock(side_effect=AssertionError("embeddings request")))
    yield calls
    assert calls == []


def _connect_ai(result=None, error=None):
    """An analysis provider that is set up: answers `result`, or raises `error`."""
    provider = AsyncMock()
    provider.generate_json = AsyncMock(side_effect=error) if error else AsyncMock(return_value=dict(result or GOOD))
    return patch("app.pipeline.get_primary_provider", return_value=provider), provider


# ── No AI at all ─────────────────────────────────────────────────

def test_a_fresh_install_has_no_provider_that_could_call_anyone():
    assert ai_connections.needs_setup() is True
    provider = providers.get_primary_provider()
    assert isinstance(provider, UnconfiguredProvider) and providers.ai_connected() is False
    for slot in ("brain", "radar"):  # they follow the analysis chain
        assert isinstance(providers.get_provider(slot), UnconfiguredProvider)


async def test_the_stand_in_provider_raises_without_sending_anything():
    provider = providers.get_primary_provider()
    with pytest.raises(NoAIConnectionError):
        await provider.generate_json("x")
    with pytest.raises(NoAIConnectionError):
        await provider.generate_text("x")


def test_pasting_a_link_saves_it_as_not_analysed(web_page, no_ai_requests):
    with TestClient(app) as client:
        res = client.post("/api/ingest", headers=HEADERS, json={"url": URL})
        assert res.status_code == 200, res.text
        item = res.json()["item"]
        assert item["analysis_status"] == "pending"
        stored = client.get(f"/api/items/{item['id']}", headers=HEADERS).json()
        found = client.get("/api/items", headers=HEADERS, params={"q": "Retry queues"}).json()
    assert stored["title_l1"] == "Retry queues explained" and stored["url"] == URL
    assert stored["cover_image"] == "https://example.com/cover.png"
    assert stored["content_raw"] == PAGE["content_raw"]
    assert stored["summary_l1"].startswith(pipeline.NOT_ANALYSED_TAG + "Retry queues keep a failed job")
    assert stored["deep_analysis"] == "" and stored["tech_tags"] == []
    assert stored["analysis_status"] == "pending" and pipeline.is_not_analysed(stored)
    assert [i["id"] for i in found] == [item["id"]]  # found by its text afterwards


async def test_the_browser_s_title_and_description_are_kept(no_ai_requests):
    wall = {"title": "未知標題", "content_raw": "（未能擷取到網頁內文）", "cover_image": "", "author": "",
            "published_date": "", "raw_html": ""}
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=wall)):
        item = await pipeline.run_pipeline(URL, page_title="會員限定：Rust 非同步實戰", page_description="從 Tokio 到 io_uring")
    stored = db.get_item_by_id(item["id"])
    assert stored["title_l1"] == "會員限定：Rust 非同步實戰"
    assert stored["summary_l1"] == pipeline.NOT_ANALYSED_TAG + "從 Tokio 到 io_uring"
    assert stored["analysis_status"] == "pending"


async def test_a_note_is_kept_too(no_ai_requests):
    item = await pipeline.run_pipeline("今天學到：佇列重試要有上限\n不然壞掉的工作會一直排第一個", as_note=True)
    stored = db.get_item_by_id(item["id"])
    assert stored["source_type"] == "snippet" and stored["title_l1"].startswith("今天學到")
    assert stored["summary_l1"].startswith(pipeline.NOT_ANALYSED_TAG) and stored["analysis_status"] == "pending"


async def test_a_link_from_telegram_goes_through_the_queue_and_is_kept(web_page, no_ai_requests, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:test-token-for-the-card")
    task = db.create_ingest_task(URL, source="telegram", chat_id=4242, message_id=77)
    sent = AsyncMock(return_value={"ok": True})
    with patch("app.bot.telegram_bot.TelegramBot.edit_message_text", new=sent), \
         patch("app.bot.telegram_bot.TelegramBot.set_message_reaction", new=AsyncMock()), \
         patch("app.queue.worker.notify_task_failed", new=AsyncMock()) as failed:
        worker = TaskWorker()
        await worker._process_task(task)
        for pending in list(worker.active_tasks):
            await pending
    stored = db.get_ingest_task(task["id"])
    assert stored["status"] == "completed" and stored["item_id"]
    assert db.get_item_by_id(stored["item_id"])["analysis_status"] == "pending"
    failed.assert_not_awaited()
    card = sent.await_args.args[2]
    assert "尚未分析" in card and "設定 › AI" in card


@pytest.mark.parametrize("source", ["api", "line", "import"])  # phone share sheet, LINE, bookmark import with analysis
async def test_every_queued_entry_point_keeps_the_link(web_page, no_ai_requests, source):
    task = db.create_ingest_task(URL, source=source)
    with patch("app.queue.worker.notify_line_completed", new=AsyncMock()):
        await TaskWorker()._process_task(task)
    stored = db.get_ingest_task(task["id"])
    assert stored["status"] == "completed"
    assert db.get_item_by_id(stored["item_id"])["analysis_status"] == "pending"


async def test_an_agent_saving_through_mcp_is_told_it_was_not_analysed(web_page, no_ai_requests):
    from app.mcp_server import save_to_brain
    answer = await save_to_brain(URL)
    assert "尚未分析" in answer and "設定 › AI" in answer
    assert len(db.get_items(limit=10)) == 1


async def test_the_setup_tool_says_the_link_was_kept_without_analysis(web_page, no_ai_requests):
    from app import setup_flow
    setup_flow.bind_in_process(app)
    try:
        result = await setup_flow.ingest(URL)
    finally:
        setup_flow.unbind_in_process()
    assert result["analysed"] is False and "接上 AI" in result["note"]


# ── What people are told ─────────────────────────────────────────

def test_nobody_without_a_key_is_told_to_paste_it_again():
    message = error_translate.failure_message(NoAIConnectionError())
    assert "設定 › AI" in message and "金鑰" not in message
    assert error_translate.classify(NoAIConnectionError())["kind"] == "no_ai"
    for status in (401, 403):
        assert "重新貼上" not in error_translate.translate(status, "")["hint"]
    assert "重新貼上" not in error_translate.translate(401, "Incorrect API key provided")["hint"]


# ── Once an AI is connected ──────────────────────────────────────

async def _kept_item():
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=dict(PAGE))):
        item = await pipeline.run_pipeline(URL)
    db.update_item_field(item["id"], {"is_starred": 1})
    return db.get_item_by_id(item["id"])


async def test_the_stored_text_is_analysed_without_fetching_again():
    kept = await _kept_item()
    connected, provider = _connect_ai()
    with connected, patch("app.pipeline.parse_url", new=AsyncMock(side_effect=AssertionError("fetched again"))), \
         patch("app.research.tool_resolver.resolve_mentioned_tools", new=AsyncMock(return_value=[])), \
         patch("app.research.competitor_detector.detect_competitors_and_alternatives", new=AsyncMock()):
        await pipeline.analyse_saved_item(kept)
    stored = db.get_item_by_id(kept["id"])
    assert stored["analysis_status"] == "done" and stored["summary_l1"] == GOOD["summary_l1"]
    assert stored["deep_analysis"] == GOOD["deep_analysis"] and stored["title_l1"] == GOOD["title_l1"]
    assert stored["content_raw"] == PAGE["content_raw"] and stored["is_starred"] == 1
    assert len(db.get_items(limit=10)) == 1  # rewritten in place
    assert "Retry queues keep a failed job" in provider.generate_json.await_args.args[0]


async def test_a_failed_analysis_leaves_the_kept_item_waiting():
    kept = await _kept_item()
    limit = openai.RateLimitError("Too Many Requests", body=None, response=httpx.Response(
        429, request=httpx.Request("POST", "https://provider.example/v1/chat/completions")))
    connected, _ = _connect_ai(error=limit)
    with connected, pytest.raises(openai.RateLimitError):
        await pipeline.analyse_saved_item(kept)
    stored = db.get_item_by_id(kept["id"])
    assert stored["analysis_status"] == "pending" and stored["content_raw"] == PAGE["content_raw"]


async def test_the_background_loop_waits_for_a_connection_then_analyses():
    kept = await _kept_item()
    assert await refetch.analyse_waiting() == {"waiting": 0, "analysed": 0, "failed": 0}  # still no AI
    assert db.get_item_by_id(kept["id"])["analysis_status"] == "pending"
    connected, _ = _connect_ai()
    with connected, patch("app.providers.ai_connected", return_value=True), \
         patch("app.research.tool_resolver.resolve_mentioned_tools", new=AsyncMock(return_value=[])), \
         patch("app.research.competitor_detector.detect_competitors_and_alternatives", new=AsyncMock()):
        stats = await refetch.analyse_waiting()
    assert stats == {"waiting": 1, "analysed": 1, "failed": 0}
    assert db.get_item_by_id(kept["id"])["analysis_status"] == "done"
    assert refetch.waiting_for_analysis() == []


async def test_radar_stubs_are_left_to_the_radar():
    db.save_item({"url": "https://example.com/radar", "title_l1": "stub", "origin": "radar", "analysis_status": "pending"})
    assert refetch.waiting_for_analysis() == []


async def test_the_analyse_button_needs_a_connection_then_works():
    kept = await _kept_item()
    with TestClient(app) as client:
        refused = client.post(f"/api/items/{kept['id']}/analyze", headers=HEADERS)
        assert refused.status_code == 409 and "設定 › AI" in refused.json()["detail"]
        connected, _ = _connect_ai()
        with connected, patch("app.providers.ai_connected", return_value=True), \
             patch("app.research.tool_resolver.resolve_mentioned_tools", new=AsyncMock(return_value=[])), \
             patch("app.research.competitor_detector.detect_competitors_and_alternatives", new=AsyncMock()):
            done = client.post(f"/api/items/{kept['id']}/analyze", headers=HEADERS)
            again = client.post(f"/api/items/{kept['id']}/analyze", headers=HEADERS)
        assert done.status_code == 200 and done.json()["item"]["analysis_status"] == "done"
        assert again.status_code == 409  # analysed already
        assert client.post("/api/items/nope/analyze", headers=HEADERS).status_code == 404


# ── An AI that is set up but fails: unchanged ────────────────────

async def test_a_connected_ai_that_fails_still_saves_nothing(web_page):
    limit = openai.RateLimitError("Too Many Requests", body=None, response=httpx.Response(
        429, request=httpx.Request("POST", "https://provider.example/v1/chat/completions")))
    connected, _ = _connect_ai(error=limit)
    with connected, pytest.raises(openai.RateLimitError):
        await pipeline.run_pipeline(URL)
    assert db.get_items(limit=10) == []


async def test_a_real_connection_in_the_analysis_slot_is_used(web_page):
    ai_connections.create({"card": "groq", "key": "gsk_test_key_for_the_slot_0001"}, slot="analysis")
    assert providers.ai_connected() is True
    with patch("app.providers.chain.ChainProvider.generate_json", new=AsyncMock(return_value=dict(GOOD))), \
         patch("app.research.tool_resolver.resolve_mentioned_tools", new=AsyncMock(return_value=[])), \
         patch("app.research.competitor_detector.detect_competitors_and_alternatives", new=AsyncMock()):
        item = await pipeline.run_pipeline(URL)
    assert db.get_item_by_id(item["id"])["analysis_status"] == "done"
