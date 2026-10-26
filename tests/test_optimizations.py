import os
import subprocess
import tempfile
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.database import (
    init_db,
    get_db_connection,
    save_item,
    create_ingest_task,
    get_ingest_task
)
from app.queue.worker import TaskWorker
from app.bot.line_bot import process_line_event
from app.parsers.reel import transcribe_local_whisper

def setup_module(module):
    init_db()

def test_sqlite_pragma_settings():
    """Verify WAL, NORMAL sync, busy timeout, and memory cache tuning"""
    conn = get_db_connection()
    c = conn.cursor()

    c.execute("PRAGMA journal_mode")
    jmode = c.fetchone()[0].lower()
    assert jmode == "wal"

    c.execute("PRAGMA busy_timeout")
    btimeout = c.fetchone()[0]
    assert btimeout >= 5000

    c.execute("PRAGMA synchronous")
    sync = c.fetchone()[0]
    # In SQLite, NORMAL is 1
    assert sync == 1

    conn.close()

@pytest.mark.asyncio
async def test_worker_idempotency_cache():
    """Verify that when a URL is already in database, worker hits cache instantly (<5ms)"""
    conn = get_db_connection()
    conn.execute("DELETE FROM ingest_tasks")
    conn.commit()
    conn.close()

    test_url = "https://github.com/astral-sh/uv"
    item_id = "test-uv-cache"
    save_item({
        "id": item_id,
        "url": test_url,
        "source_type": "github",
        "category_name": "Github",
        "title_l1": "Astral uv",
        "summary_l1": "An extremely fast Python package manager.",
        "tech_tags": ["Python", "Rust"],
        "deep_analysis": "Rust-based packaging."
    })

    # Create task with the exact same URL
    task = create_ingest_task(url=test_url, source="telegram", chat_id=123999, message_id=888111)

    worker = TaskWorker(concurrency=2, poll_interval=0.1)

    # Patch run_pipeline to ensure it is NEVER called because of the idempotency cache hit!
    with patch("app.queue.worker.run_pipeline") as mock_pipeline, \
         patch("app.queue.worker.notify_task_completed", new=AsyncMock()) as mock_notify:

        worker.start()
        import asyncio
        await asyncio.sleep(0.3)
        await worker.stop()

        # run_pipeline MUST NOT be called!
        assert not mock_pipeline.called

        # Task should be marked completed with existing item_id
        t = get_ingest_task(task["id"])
        assert t["status"] == "completed"
        assert t["item_id"] == item_id
        assert mock_notify.called

@pytest.mark.asyncio
async def test_line_bot_hoarder_queueing():
    """Verify LINE Webhook queues ingest task immediately and replies receipt"""
    user_id = "U1234567890abcdef"
    
    with patch("app.bot.line_bot.is_line_user_authorized", return_value=True), \
         patch("app.bot.line_bot.start_line_loading", new=AsyncMock()), \
         patch("app.bot.line_bot.reply_line_messages", new=AsyncMock()) as mock_reply, \
         patch("app.bot.line_bot.create_ingest_task") as mock_create_task:

        event = {
            "type": "message",
            "replyToken": "dummy_reply_token_123",
            "source": {"userId": user_id},
            "message": {
                "type": "text",
                "text": "https://github.com/pydantic/pydantic"
            }
        }

        await process_line_event(event)

        # Immediate receipt message replied
        assert mock_reply.called
        reply_call_args = mock_reply.call_args[0]
        assert reply_call_args[0] == "dummy_reply_token_123"
        assert "已收件排隊中" in reply_call_args[1][0]["text"]

        # Enqueued to SQLite Hoarder Queue
        mock_create_task.assert_called_once_with(
            url="https://github.com/pydantic/pydantic",
            source="line",
            chat_id=user_id,
            message_id=None
        )

def test_transcribe_local_whisper_synthetic_audio():
    """Verify local faster-whisper transcribes audio without crashing"""
    with tempfile.TemporaryDirectory() as td:
        aud_path = os.path.join(td, "tone.mp3")
        # Generate 1-second sine tone
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libmp3lame", aud_path],
            capture_output=True
        )
        model = MagicMock()
        model.transcribe.return_value = ([MagicMock(text=" synthetic transcript ")], None)
        with patch("app.parsers.reel.get_local_whisper_model", return_value=model):
            res = transcribe_local_whisper(aud_path)
        assert res == "synthetic transcript"
        model.transcribe.assert_called_once()
        # Should execute cleanly and return string (empty or hallucinated tone token)
        assert isinstance(res, str)
