import pytest
import sqlite3
import uuid
from app.database import (
    init_db,
    create_ingest_task,
    claim_next_task,
    update_task_status,
    get_ingest_task,
    reset_stale_tasks,
    get_user_setting,
    set_user_setting,
    get_db_connection
)

def setup_module(module):
    init_db()

def test_ingest_tasks_lifecycle():
    unique_url = f"https://example.com/item-{uuid.uuid4().hex[:8]}"
    task = create_ingest_task(url=unique_url, source="telegram", chat_id=12345, message_id=67890)
    assert task["id"] is not None
    assert task["url"] == unique_url
    assert task["status"] == "queued"
    assert task["chat_id"] == 12345
    assert task["message_id"] == 67890

    # Claim task
    claimed = claim_next_task()
    assert claimed is not None
    assert claimed["status"] == "processing"

    # Update status to completed
    success = update_task_status(claimed["id"], status="completed", item_id="item-test-123")
    assert success is True

    fetched = get_ingest_task(claimed["id"])
    assert fetched["status"] == "completed"
    assert fetched["item_id"] == "item-test-123"

def test_crash_recovery_reset():
    # Insert a task directly in 'processing' status
    conn = get_db_connection()
    c = conn.cursor()
    test_id = f"stale-{uuid.uuid4().hex[:6]}"
    c.execute(
        "INSERT INTO ingest_tasks (id, url, status) VALUES (?, ?, 'processing')",
        (test_id, "https://example.com/stale")
    )
    conn.commit()
    conn.close()

    # Run crash recovery
    reset_count = reset_stale_tasks()
    assert reset_count >= 1

    recovered = get_ingest_task(test_id)
    assert recovered["status"] == "queued"
    assert recovered["retry_count"] >= 1

def test_user_settings_modes():
    user_id = 987654321
    # Default is heartbeat
    assert get_user_setting(user_id) == "heartbeat"

    # Switch to quiet
    set_user_setting(user_id, "quiet")
    assert get_user_setting(user_id) == "quiet"

    # Switch back to heartbeat
    set_user_setting(user_id, "heartbeat")
    assert get_user_setting(user_id) == "heartbeat"
