"""Regression tests for repo identity and durable completion delivery."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app import database as db
from app.bot import line_bot, telegram_bot
from app.queue.worker import TaskWorker


def _item(identifier, url):
    return {
        "id": identifier,
        "url": url,
        "source_type": "github",
        "category_name": "Github",
        "title_l1": identifier,
        "summary_l1": "Summary",
        "tech_tags": ["Python"],
        "deep_analysis": "Analysis",
    }


def test_exact_github_repository_identity_does_not_match_prefix_or_sql_wildcards():
    db.save_item(_item("toolbox", "https://github.com/ACME/toolbox"))
    db.save_item(_item("repo-x", "https://github.com/acme/repo-x"))
    db.save_item(_item("repo_1", "https://github.com/acme/repo_1"))

    assert db.find_item_by_canonical_or_url("https://github.com/acme/tool") is None
    assert db.find_item_by_canonical_or_url("https://github.com/acme/repo%") is None
    assert db.find_item_by_canonical_or_url("https://github.com/acme/repo_2") is None
    assert db.find_item_by_canonical_or_url("https://github.com/acme/toolbox.git?tab=readme")["id"] == "toolbox"
    assert db.find_item_by_canonical_or_url("https://www.github.com/Acme/repo_1#main")["id"] == "repo_1"


def test_completed_tasks_atomically_enqueue_only_addressable_notifications():
    addressed = db.create_ingest_task("https://example.com/a", chat_id=123, message_id=456)
    silent = db.create_ingest_task("https://example.com/b", chat_id=None, message_id=None)
    db.update_task_status(addressed["id"], status="completed", item_id="item-a")
    db.update_task_status(silent["id"], status="completed", item_id="item-b")

    assert db.get_ingest_task(addressed["id"])["error_message"] == db.NOTIFICATION_PENDING
    assert db.get_ingest_task(silent["id"])["error_message"] is None
    claimed = db.claim_completion_notification(addressed["id"])
    assert claimed["item_id"] == "item-a"
    assert db.claim_completion_notification(addressed["id"]) is None
    assert db.finish_completion_notification(addressed["id"], claimed["error_message"])
    assert db.get_ingest_task(addressed["id"])["error_message"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["telegram", "line"])
async def test_notification_429_is_durable_without_ingestion_retry_or_llm_cooldown(source):
    item = _item(f"saved-{source}", f"https://example.com/source-{source}")
    db.save_item(item)
    # Force pipeline path, rather than a cache hit.
    task = db.create_ingest_task(f"https://example.com/request-{source}", source=source,
                                 chat_id="12345", message_id=778 if source == "telegram" else None)
    worker = TaskWorker(poll_interval=0.01)
    notify_name = "notify_task_completed" if source == "telegram" else "notify_line_completed"
    with patch("app.queue.worker.run_pipeline", new=AsyncMock(return_value=item)) as pipeline, \
         patch(f"app.queue.worker.{notify_name}", new=AsyncMock(side_effect=RuntimeError("429 send quota"))) as notify:
        await worker._process_task(task)
        await asyncio.gather(*worker.active_tasks)
        assert pipeline.await_count == 1
        notify.assert_awaited_once()

    stored = db.get_ingest_task(task["id"])
    assert stored["status"] == "completed"
    assert stored["retry_count"] == 0
    assert stored["error_message"].startswith("notify_v1:retry:1:")
    assert db.claim_completion_notification(task["id"]) is None
    assert worker._rate_limit_until == 0

    # Simulate the elapsed backoff in this isolated test database, then restart.
    with db.get_db_connection() as conn:
        conn.execute("UPDATE ingest_tasks SET error_message = ? WHERE id = ?",
                     ("notify_v1:retry:1:0:429", task["id"]))

    restored = TaskWorker(poll_interval=0.01)
    restored._rate_limit_until = time.monotonic() + 120
    delivered = asyncio.Event()

    async def recovered_send(*args, **kwargs):
        delivered.set()

    with patch("app.queue.worker.run_pipeline", new=AsyncMock()) as unexpected_pipeline, \
         patch(f"app.queue.worker.{notify_name}", new=recovered_send):
        restored.start()
        try:
            await asyncio.wait_for(delivered.wait(), timeout=2)
        finally:
            await restored.stop()
        unexpected_pipeline.assert_not_awaited()

    complete = db.get_ingest_task(task["id"])
    assert complete["status"] == "completed"
    assert complete["retry_count"] == 0
    assert complete["error_message"] is None


@pytest.mark.asyncio
async def test_cached_completion_uses_same_durable_delivery():
    item = _item("cached", "https://github.com/acme/cache")
    db.save_item(item)
    task = db.create_ingest_task("https://github.com/ACME/cache.git", chat_id=34, message_id=45)
    worker = TaskWorker()
    with patch("app.queue.worker.run_pipeline", new=AsyncMock()) as pipeline, \
         patch("app.queue.worker.notify_task_completed", new=AsyncMock()) as notify:
        await worker._process_task(task)
        await asyncio.gather(*worker.active_tasks)
        pipeline.assert_not_awaited()
        notify.assert_awaited_once()
    assert db.get_ingest_task(task["id"])["error_message"] is None


@pytest.mark.asyncio
async def test_cancelled_notification_remains_recoverable():
    item = _item("cancelled", "https://example.com/cancelled")
    db.save_item(item)
    task = db.create_ingest_task("https://example.com/cancel-me", chat_id=34, message_id=45)
    db.update_task_status(task["id"], status="completed", item_id=item["id"])
    worker = TaskWorker()
    entered = asyncio.Event()

    async def stalled_send(*args, **kwargs):
        entered.set()
        await asyncio.Event().wait()

    with patch("app.queue.worker.notify_task_completed", new=stalled_send):
        await worker._schedule_completion_notification(task["id"])
        await asyncio.wait_for(entered.wait(), timeout=2)
        for pending in worker.active_tasks:
            pending.cancel()
        await asyncio.gather(*worker.active_tasks, return_exceptions=True)

    assert db.get_ingest_task(task["id"])["error_message"].startswith("notify_v1:inflight:")
    db.reset_stale_tasks()
    assert db.get_ingest_task(task["id"])["error_message"].startswith("notify_v1:pending:")


def test_restart_reclaims_delivery_inflight_but_not_completed_ingestion():
    task = db.create_ingest_task("https://example.com/durable", chat_id=111, message_id=222)
    db.update_task_status(task["id"], status="completed", item_id="some-item")
    claimed = db.claim_completion_notification(task["id"])
    assert claimed["error_message"] == "notify_v1:inflight:0"
    assert db.reset_stale_tasks() == 0
    recovered = db.get_ingest_task(task["id"])
    assert recovered["status"] == "completed"
    assert recovered["retry_count"] == 0
    assert recovered["error_message"] == "notify_v1:pending:0"
    assert db.claim_completion_notification(task["id"]) is not None


@pytest.mark.asyncio
async def test_strict_telegram_completion_detects_api_failure_but_allows_already_updated():
    bot = MagicMock()
    bot.build_item_card_html.return_value = "card"
    bot.build_item_keyboard.return_value = {}
    bot.edit_message_text = AsyncMock(return_value={"ok": False, "description": "Too Many Requests: retry after 30"})
    with patch.object(telegram_bot, "get_telegram_bot", return_value=bot):
        with pytest.raises(RuntimeError, match="Too Many Requests"):
            await telegram_bot.notify_task_completed(12, 23, {}, strict=True)
        bot.edit_message_text.return_value = {"ok": False, "description": "Bad Request: message is not modified"}
        await telegram_bot.notify_task_completed(12, 23, {}, strict=True)


@pytest.mark.asyncio
async def test_strict_line_completion_detects_send_failure_and_http_429():
    with patch.object(line_bot.settings, "LINE_CHANNEL_ACCESS_TOKEN", "placeholder"), \
         patch.object(line_bot, "push_line_messages", new=AsyncMock(side_effect=RuntimeError("429"))):
        with pytest.raises(RuntimeError, match="429"):
            await line_bot.notify_line_completed("some-user", _item("a", "https://example.com"), strict=True)

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            return httpx.Response(429, request=httpx.Request("POST", url), json={"message": "rate limited"})

    with patch.object(line_bot.settings, "LINE_CHANNEL_ACCESS_TOKEN", "placeholder"), \
         patch.object(line_bot.httpx, "AsyncClient", return_value=Client()):
        with pytest.raises(httpx.HTTPStatusError):
            await line_bot.send_line_api("message/push", {"to": "test", "messages": []})
