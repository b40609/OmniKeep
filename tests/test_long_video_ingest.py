"""A long YouTube video sent to the waiting ingest API is read in the queue (2026-11-18 trial: a
2-hour video took over 2 minutes and the caller gave up at 120 s)."""
import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.config import settings
from app.database import get_ingest_task, init_db
from app.main import app
from app.parsers import youtube
from app.routers import ingest


def setup_module(module):
    init_db()


def _post(content, duration, **extra):
    meta = AsyncMock(return_value={"title": "t", "duration": duration})
    run = AsyncMock(return_value={"id": "x", "title_l1": "t"})
    with patch.object(youtube, "fetch_youtube_metadata", new=meta), patch.object(ingest, "run_pipeline", new=run), \
         TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        res = client.post("/api/ingest", json={"content": content, **extra})
    return res, run, meta


def test_a_long_video_goes_to_the_queue_and_says_why():
    res, run, _ = _post("https://www.youtube.com/watch?v=kCc8FmEb1nY", 6960)
    body = res.json()
    assert res.status_code == 200 and body["status"] == "queued" and body["success"]
    assert "116 分鐘" in body["message"] and "收件匣" in body["message"]
    assert get_ingest_task(body["task_id"])["url"] == "https://www.youtube.com/watch?v=kCc8FmEb1nY"
    run.assert_not_awaited()


def test_a_short_video_or_another_link_is_read_while_the_caller_waits():
    res, run, _ = _post("https://www.youtube.com/watch?v=kJQP7kiw5Fk", 280)
    assert res.json()["status"] == "completed" and run.await_count == 1
    res, run, meta = _post("https://www.youtube.com/shorts/50p_iB9fXmc", 0)
    assert res.json()["status"] == "completed"
    meta.assert_not_awaited()  # Shorts are short
    res, run, meta = _post("https://example.com/article", 0)
    assert res.json()["status"] == "completed"
    meta.assert_not_awaited()


def test_metadata_read_a_moment_ago_is_not_read_again(monkeypatch):
    calls = []

    class Dl:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def extract_info(self, url, download=False):
            calls.append(url)
            return {"title": "Despacito", "duration": 280}

    monkeypatch.setattr("app.parsers.media_network.PublicYoutubeDL", Dl)
    monkeypatch.setattr(youtube, "_RECENT", {})
    url = "https://www.youtube.com/watch?v=kJQP7kiw5Fk"
    first = asyncio.run(youtube.fetch_youtube_metadata(url))
    first["title"] = "changed by a caller"
    second = asyncio.run(youtube.fetch_youtube_metadata(url))
    assert calls == [url] and second["title"] == "Despacito"
