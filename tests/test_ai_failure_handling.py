"""What happens when an AI call fails: nothing is saved as a finished, empty item.

Before: generate_structured_intelligence() swallowed every error (a rate limit like a bad
answer), retried three times and handed back an empty structure, which the pipeline saved
with a placeholder summary. A provider answering HTTP 400 returned None, an empty answer
became {}, and one hung task held a queue slot until the next restart.
"""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app import ai_status, database as db, error_translate, pipeline, setup_flow
from app.config import settings
from app.main import app
from app.parsers.transcript import Transcript
from app.providers.base import EmptyResponseError
from app.providers.chain import ChainProvider, Member
from app.providers.gemini import GeminiProvider
from app.providers.openai_compatible import OpenAICompatibleProvider
from app.queue import worker as worker_module
from app.queue.worker import TaskTimeoutError, TaskWorker
from app.schemas.intelligence import AnalysisFailedError, generate_structured_intelligence

URL = "https://example.com/article"
GOOD = {"category": "Inbox", "title_l1": "文章重點", "summary_l1": "這篇在講佇列的重試。", "tech_tags": ["Queue"],
        "deep_analysis": "## 重點\n- 重試", "is_composite": False, "sub_entities": []}
PAGE = {"url": URL, "title": "Queues", "content_raw": "A long article about retry queues. " * 40,
        "cover_image": "", "author": "", "published_date": "", "raw_html": "", "http_status": 200}
HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}


def _status_error(cls, status, message):
    response = httpx.Response(status, request=httpx.Request("POST", "https://provider.example/v1/chat/completions"))
    return cls(message, response=response, body=None)


def _rate_limit():
    return _status_error(openai.RateLimitError, 429, "Too Many Requests")


def _provider(*outcomes):
    """generate_json gives each outcome in turn (an exception is raised)."""
    provider = AsyncMock()
    provider.generate_json = AsyncMock(side_effect=list(outcomes))
    return provider


def _completion(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.fixture(autouse=True)
def clean_status():
    ai_status.forget()
    yield
    ai_status.forget()


@pytest.fixture
def web_page():
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=dict(PAGE))), \
         patch("app.research.tool_resolver.resolve_mentioned_tools", new=AsyncMock(return_value=[])), \
         patch("app.research.competitor_detector.detect_competitors_and_alternatives", new=AsyncMock()):
        yield


def _saved():
    return db.get_items(limit=50)


# ── generate_structured_intelligence ─────────────────────────────

async def test_a_rate_limit_goes_up_without_a_validation_retry():
    provider = _provider(_rate_limit())
    with pytest.raises(openai.RateLimitError):
        await generate_structured_intelligence(provider, "prompt", "system")
    assert provider.generate_json.await_count == 1  # not three calls into a two-a-minute quota


@pytest.mark.parametrize("failure", [
    _status_error(openai.AuthenticationError, 401, "Incorrect API key provided"),
    openai.APIConnectionError(request=httpx.Request("POST", "https://provider.example/v1")),
    _status_error(openai.InternalServerError, 503, "upstream overloaded"),
    EmptyResponseError("free"),
])
async def test_provider_failures_are_not_retried_or_swallowed(failure):
    provider = _provider(failure)
    with pytest.raises(type(failure)):
        await generate_structured_intelligence(provider, "prompt", "system")
    assert provider.generate_json.await_count == 1


async def test_an_answer_that_does_not_validate_is_retried_with_a_reminder():
    provider = _provider({"title": "wrong keys", "summary": "x"}, dict(GOOD))
    result = await generate_structured_intelligence(provider, "prompt", "system")
    assert result["summary_l1"] == GOOD["summary_l1"]
    first, second = (call.args[0] for call in provider.generate_json.await_args_list)
    assert first == "prompt"
    assert "驗證失敗提醒" in second and "summary_l1" in second and "title、summary" in second


async def test_text_that_is_not_json_is_retried_too():
    provider = _provider(json.JSONDecodeError("Expecting value", "好的，以下是分析", 0), dict(GOOD))
    assert (await generate_structured_intelligence(provider, "prompt", "system"))["title_l1"] == "文章重點"
    assert provider.generate_json.await_count == 2


async def test_validation_retries_used_up_raise_instead_of_an_empty_result():
    provider = _provider({}, None, {"category": "Inbox"})
    with pytest.raises(AnalysisFailedError) as caught:
        await generate_structured_intelligence(provider, "prompt", "system")
    assert provider.generate_json.await_count == 3
    assert caught.value.attempts == 3 and "summary_l1" in caught.value.reason


# ── run_pipeline: no finished, empty item ────────────────────────

async def test_pipeline_rate_limit_reaches_the_caller_and_saves_nothing(web_page):
    provider = _provider(_rate_limit())
    with patch("app.pipeline.get_primary_provider", return_value=provider):
        with pytest.raises(openai.RateLimitError) as caught:
            await pipeline.run_pipeline(URL)
    assert provider.generate_json.await_count == 1
    assert _saved() == []
    assert error_translate.is_ai_failure(caught.value)


async def test_pipeline_saves_normally_after_a_validation_retry(web_page):
    provider = _provider({}, dict(GOOD))
    with patch("app.pipeline.get_primary_provider", return_value=provider):
        item = await pipeline.run_pipeline(URL)
    stored = db.get_item_by_id(item["id"])
    assert stored["summary_l1"] == GOOD["summary_l1"] and stored["deep_analysis"] == GOOD["deep_analysis"]
    assert provider.generate_json.await_count == 2


async def test_pipeline_raises_when_no_answer_validates_and_saves_nothing(web_page):
    provider = _provider({}, {}, {})
    with patch("app.pipeline.get_primary_provider", return_value=provider):
        with pytest.raises(AnalysisFailedError):
            await pipeline.run_pipeline(URL)
    assert _saved() == []


async def test_a_failed_analysis_leaves_an_existing_item_as_it_was(web_page):
    item_id = db.save_item({"url": URL, "title_l1": "先前的分析", "summary_l1": "先前的摘要", "content_raw": "old"})
    with patch("app.pipeline.get_primary_provider", return_value=_provider(_rate_limit())):
        with pytest.raises(openai.RateLimitError):
            await pipeline.run_pipeline(URL)
    assert db.get_item_by_id(item_id)["summary_l1"] == "先前的摘要"


async def test_a_plain_error_in_the_ai_stage_is_still_told_from_a_failed_fetch(web_page):
    # google-genai lets transport errors through as plain httpx ones.
    provider = _provider(httpx.ConnectError("All connection attempts failed"))
    with patch("app.pipeline.get_primary_provider", return_value=provider):
        with pytest.raises(httpx.ConnectError) as caught:
            await pipeline.run_pipeline(URL)
    assert error_translate.is_ai_failure(caught.value)
    assert error_translate.failure_message(caught.value).startswith("AI 分析失敗：連不上 AI 服務")
    assert not error_translate.is_ai_failure(httpx.ConnectError("the page's own failure"))


async def test_the_browser_description_stands_in_and_says_so(web_page):
    provider = _provider({}, {}, {})
    with patch("app.pipeline.get_primary_provider", return_value=provider):
        item = await pipeline.run_pipeline(URL, page_title="瀏覽器標題", page_description="瀏覽器看到的描述")
    assert item["summary_l1"] == "瀏覽器看到的描述"
    assert "AI 沒有產生可用的分析" in item["deep_analysis"]
    # A provider failure is never papered over that way.
    with patch("app.pipeline.get_primary_provider", return_value=_provider(_rate_limit())):
        with pytest.raises(openai.RateLimitError):
            await pipeline.run_pipeline("https://example.com/other", page_description="描述")


# ── YouTube: an empty video-model answer falls back to the transcript ─

@pytest.mark.parametrize("video_answer", [{}, None, {"category": "Inbox"}])
async def test_an_empty_video_model_answer_uses_the_transcript(video_answer):
    meta = {"title": "測試影片", "author": "測試頻道", "description": "說明", "cover_image": ""}
    said = Transcript("ok", "今天談向量模型怎麼挑，第一是維度。", "stt", "zh")
    gemini = AsyncMock()
    gemini.analyze_youtube = AsyncMock(return_value=video_answer)
    provider = _provider(dict(GOOD))
    with patch("app.pipeline.fetch_youtube_metadata", new=AsyncMock(return_value=meta)), \
         patch("app.pipeline.get_transcript", new=AsyncMock(return_value=said)), \
         patch("app.pipeline.has_video_provider", return_value=True), \
         patch("app.pipeline.get_gemini_provider", return_value=gemini), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        item = await pipeline.run_pipeline("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    gemini.analyze_youtube.assert_awaited_once()
    assert "第一是維度" in provider.generate_json.await_args.args[0]
    assert item["summary_l1"] == GOOD["summary_l1"]


# ── OpenAI-compatible provider ───────────────────────────────────

async def test_http_400_is_retried_without_response_format():
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub")
    provider._chat = AsyncMock(side_effect=[
        _status_error(openai.BadRequestError, 400, "response_format is not supported"),
        _completion('```json\n{"summary_l1": "ok"}\n```')])
    assert await provider.generate_json("prompt") == {"summary_l1": "ok"}
    assert provider._chat.await_count == 2
    assert "response_format" not in provider._chat.await_args.kwargs


@pytest.mark.parametrize("status, cls", [(400, openai.BadRequestError), (422, openai.UnprocessableEntityError)])
async def test_a_400_that_stays_is_raised_never_returned_as_none(status, cls):
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub")
    provider._chat = AsyncMock(side_effect=[_status_error(cls, status, "prompt is too long")] * 2)
    with pytest.raises(cls):
        await provider.generate_json("prompt")
    assert provider._chat.await_count == 2


@pytest.mark.parametrize("failure", [
    _status_error(openai.AuthenticationError, 401, "bad key"),
    _status_error(openai.APIStatusError, 413, "too large"),
    _rate_limit(),
])
async def test_other_statuses_and_rate_limits_are_not_asked_twice(failure):
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub")
    provider._chat = AsyncMock(side_effect=[failure, _completion('{"summary_l1": "must not be reached"}')])
    with pytest.raises(type(failure)):
        await provider.generate_json("prompt")
    assert provider._chat.await_count == 1


@pytest.mark.parametrize("content", [None, "", "  \n"])
async def test_an_empty_answer_is_an_error_not_an_empty_object(content):
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub", status_key="c901", label="免費管道")
    provider._chat = AsyncMock(return_value=_completion(content))
    with pytest.raises(EmptyResponseError, match="空白內容"):
        await provider.generate_json("prompt")
    assert provider._chat.await_count == 1
    state = ai_status.get("c901")
    assert state["ok"] is False and state["kind"] == "empty" and "關閉推理" in state["hint"]


async def test_an_empty_answer_without_json_mode_is_an_error_too():
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub", json_mode=False)
    provider._chat = AsyncMock(return_value=_completion(""))
    with pytest.raises(EmptyResponseError):
        await provider.generate_json("prompt")


# ── Gemini provider ──────────────────────────────────────────────

@pytest.mark.parametrize("method, args", [("generate_json", ("prompt",)),
                                         ("analyze_youtube", ("https://youtu.be/abc", "prompt"))])
async def test_gemini_empty_answer_is_an_error(monkeypatch, method, args):
    from app.providers import gemini
    provider = GeminiProvider(api_keys=["k"], model="stub")
    monkeypatch.setattr(provider, "make_client", lambda key: object())
    monkeypatch.setattr(gemini, "_generate_content", AsyncMock(return_value=SimpleNamespace(text=None)))
    with pytest.raises(EmptyResponseError):
        await getattr(provider, method)(*args)


def test_a_gemini_rate_limit_is_not_taken_for_an_empty_balance():
    message = ("429 RESOURCE_EXHAUSTED. {'error': {'code': 429, 'message': 'You exceeded your current quota, "
               "please check your plan and billing details.', 'status': 'RESOURCE_EXHAUSTED'}}")
    info = error_translate.translate(429, message)
    assert info["kind"] == "rate_limit" and info["action_required"] is False
    billing = error_translate.translate(429, "You exceeded your current quota, please check your plan and billing details.")
    assert billing["kind"] == "quota" and billing["action_required"] is True


# ── The fallback chain ───────────────────────────────────────────

class Fake:
    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    async def generate_json(self, prompt, system_prompt=None):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _chain(primary, backup):
    return ChainProvider([Member(primary, "t-primary", "primary"), Member(backup, "t-backup", "backup")])


@pytest.mark.parametrize("first", [EmptyResponseError("primary"), None,
                                   json.JSONDecodeError("Expecting value", "text", 0),
                                   _status_error(openai.BadRequestError, 400, "prompt is too long")])
async def test_the_chain_moves_on_after_an_empty_or_unusable_answer(first):
    primary, backup = Fake(first), Fake({"from": "backup"})
    assert await _chain(primary, backup).generate_json("x") == {"from": "backup"}
    assert (primary.calls, backup.calls) == (1, 1)


async def test_the_chain_raises_the_empty_answer_when_every_member_gave_one():
    with pytest.raises(EmptyResponseError):
        await _chain(Fake(None), Fake(EmptyResponseError("backup"))).generate_json("x")


async def test_a_rate_limit_still_wins_over_an_empty_answer():
    with pytest.raises(openai.RateLimitError):
        await _chain(Fake(_rate_limit()), Fake(EmptyResponseError("backup"))).generate_json("x")


# ── Messages ─────────────────────────────────────────────────────

@pytest.mark.parametrize("exc, words", [
    (_rate_limit(), "AI 服務限流"),
    (_status_error(openai.AuthenticationError, 401, "Incorrect API key provided"), "金鑰錯誤"),
    (openai.APIConnectionError(request=httpx.Request("POST", "https://provider.example/v1")), "連不上 AI 服務"),
    (_status_error(openai.InternalServerError, 503, "overloaded"), "暫時故障"),
    (EmptyResponseError("x"), "空白內容"),
    (AnalysisFailedError("沒有 summary_l1 也沒有 deep_analysis", 3), "都不是可用的分析"),
])
def test_ai_failures_are_explained_in_chinese_without_promising_a_retry(exc, words):
    message = error_translate.failure_message(exc)
    assert message.startswith("AI 分析失敗：") and words in message
    assert "自動再試" not in message and "自動放慢" not in message


def test_other_failures_keep_their_own_message():
    assert error_translate.failure_message(RuntimeError("無法取得影片")) == "無法取得影片"
    assert error_translate.failure_message(httpx.ReadTimeout("")) == "ReadTimeout"


# ── POST /api/ingest and omnikeep_ingest ─────────────────────────

def test_ingest_api_answers_with_the_translated_reason(web_page):
    with patch("app.pipeline.get_primary_provider", return_value=_provider(_rate_limit())):
        with TestClient(app) as client:
            res = client.post("/api/ingest", headers=HEADERS, json={"url": URL})
    assert res.status_code == 503
    assert res.json()["detail"].startswith("AI 分析失敗：AI 服務限流")
    assert _saved() == []


@pytest.mark.parametrize("failure, status, words", [
    (_status_error(openai.AuthenticationError, 401, "Incorrect API key provided"), 502, "金鑰錯誤"),
    (AnalysisFailedError("輸出是空物件", 3), 502, "都不是可用的分析"),
    (RuntimeError("讀不到這個頁面"), 500, "讀不到這個頁面"),
])
def test_ingest_api_status_says_whose_failure_it_is(monkeypatch, failure, status, words):
    import app.routers.ingest as ingest_route
    monkeypatch.setattr(ingest_route, "run_pipeline", AsyncMock(side_effect=failure))
    with TestClient(app) as client:
        res = client.post("/api/ingest", headers=HEADERS, json={"url": URL})
    assert res.status_code == status and words in res.json()["detail"]


async def test_the_ingest_tool_hands_the_reason_to_the_agent(monkeypatch):
    import app.routers.ingest as ingest_route
    monkeypatch.setattr(ingest_route, "run_pipeline", AsyncMock(side_effect=_rate_limit()))
    setup_flow.bind_in_process(app)
    try:
        with pytest.raises(setup_flow.SetupError, match="沒有存檔.*AI 服務限流"):
            await setup_flow.ingest(URL)
    finally:
        setup_flow.unbind_in_process()


# ── The queue worker ─────────────────────────────────────────────

def _task(url=URL, **kwargs):
    return db.create_ingest_task(url, source="telegram", chat_id=4242, message_id=77, **kwargs)


@pytest.fixture
def notices():
    with patch("app.queue.worker.notify_task_failed", new=AsyncMock()) as failed, \
         patch("app.queue.worker.notify_task_heartbeat", new=AsyncMock()) as heartbeat:
        yield failed, heartbeat


async def test_an_ai_rate_limit_queues_the_task_again_and_cools_the_worker_down(notices):
    task = _task()
    worker = TaskWorker()
    with patch("app.queue.worker.run_pipeline", new=AsyncMock(side_effect=_rate_limit())):
        await worker._process_task(task)
    stored = db.get_ingest_task(task["id"])
    assert stored["status"] == "queued" and stored["retry_count"] == 1 and "限流" in stored["error_message"]
    assert worker._rate_limit_until > 0
    notices[0].assert_not_awaited()


@pytest.mark.parametrize("site_error", [
    httpx.HTTPStatusError("Client error '429 Too Many Requests'", request=httpx.Request("GET", URL),
                          response=httpx.Response(429, request=httpx.Request("GET", URL))),
    RuntimeError("ERROR: unable to download video data: HTTP Error 429: Too Many Requests"),
    RuntimeError("download quota exceeded for this file"),
])
async def test_a_fetched_site_s_own_429_does_not_cool_the_queue_down(notices, site_error):
    task = _task()
    worker = TaskWorker()
    with patch("app.queue.worker.run_pipeline", new=AsyncMock(side_effect=site_error)):
        await worker._process_task(task)
    stored = db.get_ingest_task(task["id"])
    assert stored["status"] == "queued" and stored["retry_count"] == 1
    assert stored["error_message"].startswith("第 1 次嘗試失敗")
    assert worker._rate_limit_until == 0


async def test_rate_limit_retries_used_up_fail_with_what_to_do(notices):
    task = _task()
    task["retry_count"] = worker_module._MAX_RATE_LIMIT_RETRIES
    with patch("app.queue.worker.run_pipeline", new=AsyncMock(side_effect=_rate_limit())):
        await TaskWorker()._process_task(task)
    stored = db.get_ingest_task(task["id"])
    assert stored["status"] == "failed" and "設定 › AI」" in stored["error_message"]
    assert ".env" not in stored["error_message"]
    notices[0].assert_awaited_once()


async def test_a_failure_after_the_last_retry_is_sent_in_chinese(notices):
    task = _task()
    failure = _status_error(openai.AuthenticationError, 401, "Incorrect API key provided")
    with patch("app.queue.worker.run_pipeline", new=AsyncMock(side_effect=failure)):
        await TaskWorker(max_retries=0)._process_task(task)
    stored = db.get_ingest_task(task["id"])
    assert stored["status"] == "failed" and stored["error_message"].startswith("AI 分析失敗：金鑰錯誤")
    notices[0].assert_awaited_once_with(4242, 77, stored["error_message"])


async def test_a_task_past_the_time_limit_is_retried_and_frees_its_slot(notices, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_TASK_TIMEOUT_SECONDS", 0.05)
    cancelled = asyncio.Event()

    async def hangs(url):
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    task = _task()
    worker = TaskWorker()
    with patch("app.queue.worker.run_pipeline", new=hangs):
        await asyncio.wait_for(worker._process_task(task), timeout=5)
    stored = db.get_ingest_task(task["id"])
    assert cancelled.is_set()
    assert stored["status"] == "queued" and stored["retry_count"] == 1
    assert "處理超過" in stored["error_message"] and "已中止" in stored["error_message"]
    assert not worker.abandoned_attempts


async def test_an_attempt_that_ignores_cancellation_still_gives_the_slot_back(notices, monkeypatch):
    monkeypatch.setattr(settings, "INGEST_TASK_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(worker_module, "_CANCEL_GRACE_SECONDS", 0.05)
    release = asyncio.Event()

    async def shielded(url):  # like the reel parser waiting for its native thread
        while not release.is_set():
            try:
                await release.wait()
            except asyncio.CancelledError:
                pass
        return {"id": "late"}

    task = _task()
    worker = TaskWorker(max_retries=0)
    with patch("app.queue.worker.run_pipeline", new=shielded):
        await asyncio.wait_for(worker._process_task(task), timeout=5)
        assert db.get_ingest_task(task["id"])["status"] == "failed"
        assert len(worker.abandoned_attempts) == 1
        release.set()
        await asyncio.gather(*worker.abandoned_attempts)
        await asyncio.sleep(0)
    assert not worker.abandoned_attempts
    notices[0].assert_awaited_once()


async def test_the_time_limit_can_be_turned_off(monkeypatch):
    monkeypatch.setattr(settings, "INGEST_TASK_TIMEOUT_SECONDS", 0)
    assert await TaskWorker()._run_with_timeout(asyncio.sleep(0.01, result="done"), 0) == "done"
    with pytest.raises(TaskTimeoutError, match="30 分鐘"):
        raise TaskTimeoutError(1800)


async def test_a_task_handed_out_too_often_is_failed_without_running(notices):
    task = _task()
    task["retry_count"] = worker_module._MAX_RATE_LIMIT_RETRIES + 1  # reset_stale_tasks() adds one per crash
    with patch("app.queue.worker.run_pipeline", new=AsyncMock()) as run:
        await TaskWorker()._process_task(task)
    run.assert_not_awaited()
    stored = db.get_ingest_task(task["id"])
    assert stored["status"] == "failed" and "已停止自動重試" in stored["error_message"]
    notices[0].assert_awaited_once()


async def test_a_task_at_the_last_allowed_retry_still_runs(notices):
    task = _task()
    task["retry_count"] = worker_module._MAX_RATE_LIMIT_RETRIES
    with patch("app.queue.worker.run_pipeline", new=AsyncMock(return_value={"id": "it"})) as run, \
         patch("app.queue.worker.notify_task_completed", new=AsyncMock()):
        worker = TaskWorker()
        await worker._process_task(task)
        await asyncio.gather(*worker.active_tasks)
    run.assert_awaited_once()
    assert db.get_ingest_task(task["id"])["status"] == "completed"


async def test_a_state_write_that_fails_once_is_tried_again(notices, monkeypatch):
    monkeypatch.setattr(worker_module, "_STATE_WRITE_PAUSES", (0.01, 0.01))
    real = worker_module.update_task_status
    calls = []

    def flaky(*args, **kwargs):
        calls.append(kwargs.get("status"))
        if len(calls) == 1:
            raise RuntimeError("database is locked")
        return real(*args, **kwargs)

    monkeypatch.setattr(worker_module, "update_task_status", flaky)
    task = _task()
    with patch("app.queue.worker.run_pipeline", new=AsyncMock(side_effect=RuntimeError("讀不到"))):
        await TaskWorker(max_retries=0)._process_task(task)
    assert calls == ["failed", "failed"]
    assert db.get_ingest_task(task["id"])["status"] == "failed"
    notices[0].assert_awaited_once()


async def test_a_state_write_that_never_lands_is_logged_and_the_person_still_hears(notices, monkeypatch, caplog):
    monkeypatch.setattr(worker_module, "_STATE_WRITE_PAUSES", (0.01,))

    def broken():
        raise RuntimeError("disk I/O error")

    task = _task()
    worker = TaskWorker(max_retries=0)
    monkeypatch.setattr(worker_module, "update_task_status",
                        lambda *a, **k: broken())
    with caplog.at_level("ERROR", logger="omnikeep.worker"), \
         patch("app.queue.worker.run_pipeline", new=AsyncMock(side_effect=RuntimeError("讀不到"))):
        await worker._process_task(task)  # does not raise
    assert "stays 'processing'" in caplog.text and "mark it failed" in caplog.text
    notices[0].assert_awaited_once()
