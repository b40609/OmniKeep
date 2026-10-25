import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.database import (
    init_db,
    create_ingest_task,
    get_ingest_task,
    get_user_setting,
    set_user_setting,
    update_task_status
)
from app.queue.worker import TaskWorker
from app.bot.telegram_bot import TelegramBot, build_mode_keyboard

def setup_module(module):
    init_db()

@pytest.mark.asyncio
async def test_worker_task_lifecycle_success():
    worker = TaskWorker(concurrency=2, poll_interval=0.1)

    # Mock pipeline execution
    fake_item = {
        "id": "item-worker-1",
        "title_l1": "測試情報",
        "summary_l1": "摘要",
        "tech_tags": ["Python"],
        "category_name": "AI"
    }

    with patch("app.queue.worker.run_pipeline", new=AsyncMock(return_value=fake_item)), \
         patch("app.queue.worker.notify_task_heartbeat", new=AsyncMock()) as mock_hb, \
         patch("app.queue.worker.notify_task_completed", new=AsyncMock()) as mock_comp:

        # 1. Create a task with chat_id and message_id
        task = create_ingest_task(
            url="https://example.com/worker-test",
            source="telegram",
            chat_id=111222,
            message_id=333444
        )
        set_user_setting(111222, "heartbeat")

        # 2. Run worker for a brief window
        loop_task = worker.start()
        await asyncio.sleep(0.3)
        await worker.stop()

        # 3. Verify task completed
        t = get_ingest_task(task["id"])
        assert t["status"] == "completed"
        assert t["item_id"] == "item-worker-1"

        # Verify heartbeat and completion notifications were dispatched
        assert mock_hb.called
        assert mock_comp.called

@pytest.mark.asyncio
async def test_worker_task_quiet_mode():
    worker = TaskWorker(concurrency=2, poll_interval=0.1)

    fake_item = {
        "id": "item-quiet-1",
        "title_l1": "安靜測試情報",
        "summary_l1": "摘要",
        "tech_tags": ["FastAPI"],
        "category_name": "AI"
    }

    with patch("app.queue.worker.run_pipeline", new=AsyncMock(return_value=fake_item)), \
         patch("app.queue.worker.notify_task_heartbeat", new=AsyncMock()) as mock_hb, \
         patch("app.queue.worker.notify_task_completed", new=AsyncMock()) as mock_comp:

        task = create_ingest_task(
            url="https://example.com/quiet-test",
            source="telegram",
            chat_id=999888,
            message_id=777666
        )
        set_user_setting(999888, "quiet")

        loop_task = worker.start()
        await asyncio.sleep(0.3)
        await worker.stop()

        t = get_ingest_task(task["id"])
        assert t["status"] == "completed"

        # In quiet mode, heartbeat should NOT be called
        assert not mock_hb.called
        # Completion card should still be called
        assert mock_comp.called

@pytest.mark.asyncio
async def test_worker_task_failure():
    worker = TaskWorker(concurrency=2, poll_interval=0.1, max_retries=0)

    with patch("app.queue.worker.run_pipeline", new=AsyncMock(side_effect=RuntimeError("AI 解析逾時"))), \
         patch("app.queue.worker.notify_task_failed", new=AsyncMock()) as mock_fail:

        task = create_ingest_task(
            url="https://example.com/fail-test",
            source="telegram",
            chat_id=555444,
            message_id=333222
        )

        loop_task = worker.start()
        await asyncio.sleep(0.3)
        await worker.stop()

        t = get_ingest_task(task["id"])
        assert t["status"] == "failed"
        assert "AI 解析逾時" in (t["error_message"] or "")
        assert mock_fail.called

@pytest.mark.asyncio
async def test_telegram_bot_mode_command():
    bot = TelegramBot(token="123456:dummy-token-for-test")
    bot.is_authorized = MagicMock(return_value=True)
    bot.send_message = AsyncMock(return_value={"result": {"message_id": 999}})

    # Test /mode command
    chat_id = 777111
    await bot.handle_update({
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": 123},
            "message_id": 1,
            "text": "/mode quiet"
        }
    })
    assert get_user_setting(chat_id) == "quiet"

    # Test switching back to heartbeat via command
    await bot.handle_update({
        "message": {
            "chat": {"id": chat_id},
            "from": {"id": 123},
            "message_id": 2,
            "text": "/mode heartbeat"
        }
    })
    assert get_user_setting(chat_id) == "heartbeat"

@pytest.mark.asyncio
async def test_telegram_bot_fast_ingestion():
    bot = TelegramBot(token="123456:dummy-token-for-test")
    bot.is_authorized = MagicMock(return_value=True)
    bot.send_message = AsyncMock(return_value={"result": {"message_id": 1001}})

    chat_id = 888222
    # Ingest URL with mock on create_ingest_task to test fast non-blocking queueing
    with patch("app.bot.telegram_bot.create_ingest_task") as mock_create:
        await bot.handle_update({
            "message": {
                "chat": {"id": chat_id},
                "from": {"id": 123},
                "message_id": 50,
                "text": "https://github.com/fastapi/fastapi"
            }
        })

        # Ensure initial message was sent immediately
        assert bot.send_message.called

        # Ensure task was queued via create_ingest_task with chat_id and message_id
        mock_create.assert_called_once_with(
            url="https://github.com/fastapi/fastapi",
            source="telegram",
            chat_id=chat_id,
            message_id=1001
        )
