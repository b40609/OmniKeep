"""The category picked in the 新增 panel reaches the item even when the link is read in the queue.

2026-11-22 前端巡檢 D1: several links at once (async_mode) and long YouTube videos go through
ingest_tasks, which had no category column, so the picked category was dropped.
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import create_ingest_task, get_db_connection, get_ingest_task, init_db
from app.main import app
from app.queue.worker import TaskWorker
from app.routers import ingest


def setup_module(module):
    init_db()


def test_ingest_tasks_has_a_category_column():
    conn = get_db_connection()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(ingest_tasks)").fetchall()}
    conn.close()
    assert "category" in cols


def test_a_task_keeps_the_picked_category_and_none_when_ai_chooses():
    picked = create_ingest_task(url="https://example.com/cat-picked", source="api", category="設計")
    auto = create_ingest_task(url="https://example.com/cat-auto", source="api")
    assert get_ingest_task(picked["id"])["category"] == "設計"
    assert get_ingest_task(auto["id"])["category"] is None


def test_queued_ingest_api_stores_the_category():
    with TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        res = client.post("/api/ingest", json={
            "content": "https://example.com/cat-queued", "category": "研究", "async_mode": True,
        })
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "queued"
    assert get_ingest_task(body["task_id"])["category"] == "研究"


def test_a_long_video_put_in_the_queue_keeps_the_category():
    with patch.object(ingest, "_long_video", new=AsyncMock(return_value=3600)), \
         TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        res = client.post("/api/ingest", json={
            "content": "https://www.youtube.com/watch?v=cat-long-video", "category": "影片",
        })
    body = res.json()
    assert body["status"] == "queued"
    assert get_ingest_task(body["task_id"])["category"] == "影片"


@pytest.mark.asyncio
async def test_the_worker_hands_the_category_to_the_pipeline():
    task = create_ingest_task(url="https://example.com/cat-worker", source="api", category="設計")
    fake_item = {"id": "item-cat-worker", "title_l1": "t", "summary_l1": "s", "category_name": "設計"}
    with patch("app.queue.worker.run_pipeline", new=AsyncMock(return_value=fake_item)) as run, \
         patch("app.queue.worker.notify_task_completed", new=AsyncMock()):
        await TaskWorker(concurrency=1, poll_interval=0.1)._process_task(get_ingest_task(task["id"]))
    run.assert_called_once()
    assert run.call_args.args[0] == "https://example.com/cat-worker"
    assert run.call_args.kwargs.get("manual_category") == "設計"
    assert get_ingest_task(task["id"])["status"] == "completed"
