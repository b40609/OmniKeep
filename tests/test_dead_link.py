"""Addresses that cannot be opened for good are refused with the reason, not saved (app/parsers/dead_link.py).

2026-11-18 new-user trial: a GitHub 404 and a domain that does not exist were saved as empty items,
and two YouTube videos that do not exist were saved as "YouTube Video" with an empty summary.
"""
import asyncio
import socket
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import pipeline
from app.config import settings
from app.database import create_ingest_task, get_ingest_task, init_db
from app.main import app
from app.parsers import dead_link, youtube
from app.parsers.dead_link import DeadLinkError
from app.queue.worker import TaskWorker
from app.routers import ingest


def setup_module(module):
    init_db()


def test_a_name_that_does_not_resolve_is_told_from_other_failures():
    try:
        raise httpx.ConnectError("connection failed") from socket.gaierror(11001, "getaddrinfo failed")
    except httpx.ConnectError as exc:
        assert dead_link.is_dns_failure(exc)
    assert dead_link.is_dns_failure(OSError("[Errno -2] Name or service not known"))
    assert not dead_link.is_dns_failure(httpx.ConnectTimeout("timed out"))
    assert not dead_link.is_dns_failure(httpx.ConnectError("[WinError 10061] connection refused"))


def test_only_failures_that_last_are_dead():
    assert "404" in dead_link.page_message("https://a.example/x", 404)
    assert "410" in dead_link.page_message("https://a.example/x", 410)
    assert "a.example" in dead_link.page_message("https://a.example/x", None, "dns")
    for status in (None, 200, 401, 403, 429, 500, 503):
        assert dead_link.page_message("https://a.example/x", status) is None


def test_a_video_is_gone_only_when_youtube_itself_says_so():
    assert youtube.unavailable_reason(404, "ERROR: [youtube] x: This video is unavailable") == "影片不存在或已被移除"
    assert youtube.unavailable_reason(400, "") == "影片不存在或已被移除"  # an id YouTube does not accept
    assert youtube.unavailable_reason(401, "ERROR: Private video. Sign in") == "影片設為私人"
    # yt-dlp also fails for a bot check or a sign-in wall: oEmbed still answers then
    assert youtube.unavailable_reason(200, "Sign in to confirm you're not a bot") == ""
    assert youtube.unavailable_reason(401, "Sign in to confirm your age") == ""
    assert youtube.unavailable_reason(500, "This video is unavailable") == ""


def test_a_video_neither_tool_could_read_gets_a_title_with_its_id(monkeypatch):
    class Refused:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            raise RuntimeError("network down")

        def __exit__(self, *_a):
            return False

    class NoNetwork:
        async def __aenter__(self):
            raise httpx.ConnectError("offline")

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr("app.parsers.media_network.PublicYoutubeDL", Refused)
    monkeypatch.setattr(youtube, "public_http_client", lambda **_k: NoNetwork())
    meta = asyncio.run(youtube.fetch_youtube_metadata("https://www.youtube.com/shorts/50p_iB9fXmc"))
    assert meta["title"] == "YouTube 影片 50p_iB9fXmc"  # not the bare "YouTube Video" the trial saw
    assert "unavailable" not in meta  # it may open later: kept and fetched again


@pytest.mark.asyncio
async def test_a_youtube_video_that_is_gone_is_refused():
    meta = {"title": "YouTube 影片 0h9r1q9F4jA", "unavailable": "影片不存在或已被移除"}
    with patch.object(pipeline, "fetch_youtube_metadata", new=AsyncMock(return_value=meta)), \
         patch.object(pipeline, "get_transcript", new=AsyncMock()) as transcript:
        with pytest.raises(DeadLinkError, match="影片不存在或已被移除"):
            await pipeline.run_pipeline("https://www.youtube.com/watch?v=0h9r1q9F4jA")
    transcript.assert_not_awaited()  # nothing to wait for


def test_the_ingest_api_answers_422_with_the_reason():
    reason = dead_link.page_message("https://github.com/made/up", 404)
    with patch.object(ingest, "run_pipeline", new=AsyncMock(side_effect=DeadLinkError(reason))), \
         TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        res = client.post("/api/ingest", json={"content": "https://github.com/made/up"})
    assert res.status_code == 422
    assert res.json()["detail"] == reason


@pytest.mark.asyncio
async def test_the_queue_does_not_retry_a_dead_link_and_tells_the_sender():
    worker = TaskWorker(concurrency=1, poll_interval=0.1, max_retries=2)
    reason = dead_link.video_message("影片不存在或已被移除")
    run = AsyncMock(side_effect=DeadLinkError(reason))
    with patch("app.queue.worker.run_pipeline", new=run), \
         patch("app.queue.worker.notify_task_failed", new=AsyncMock()) as told:
        task = create_ingest_task(url="https://www.youtube.com/watch?v=0h9r1q9F4jA", source="telegram",
                                  chat_id=555444, message_id=333223)
        worker.start()
        await asyncio.sleep(0.4)
        await worker.stop()
    stored = get_ingest_task(task["id"])
    assert stored["status"] == "failed" and stored["error_message"] == reason
    assert run.await_count == 1  # no retries: it will not open later either
    assert told.called
