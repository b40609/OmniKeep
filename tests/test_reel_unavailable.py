from contextlib import nullcontext
from unittest.mock import AsyncMock

import pytest

from app import database
from app.parsers import reel
from app.queue import worker as worker_module


URL = "https://www.instagram.com/reel/DemoReel001/"
PLACEHOLDER = "（Instagram 貼文未提供公開文字說明）"


@pytest.mark.asyncio
async def test_instagram_download_failure_does_not_analyze_placeholder(monkeypatch):
    class FailedDownload:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, *args, **kwargs):
            raise RuntimeError("empty media response")

    monkeypatch.setattr(reel, "validate_url", lambda url: None)
    monkeypatch.setattr(reel, "ytdlp_cookie_opts", lambda url: nullcontext({}))
    monkeypatch.setattr(reel, "PublicYoutubeDL", FailedDownload)
    fallback = AsyncMock(return_value={"url": URL, "content_raw": PLACEHOLDER})
    monkeypatch.setattr("app.parsers.web.parse_instagram_page", fallback)

    with pytest.raises(reel.ReelUnavailableError, match="無法取得短影音或貼文內容"):
        await reel.parse_video_reel(URL)
    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_instagram_download_failure_falls_back_to_page_metadata(monkeypatch):
    class FailedDownload:
        def __init__(self, options):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def extract_info(self, *args, **kwargs):
            raise RuntimeError("empty media response")

    monkeypatch.setattr(reel, "validate_url", lambda url: None)
    monkeypatch.setattr(reel, "ytdlp_cookie_opts", lambda url: nullcontext({}))
    monkeypatch.setattr(reel, "PublicYoutubeDL", FailedDownload)
    fallback = AsyncMock(return_value={
        "url": URL,
        "title": "Instagram 精彩片段",
        "content_raw": "這是 Instagram 貼文說明全文",
        "cover_image": "https://cdn.instagram.com/pic.jpg",
        "author": "創作者",
    })
    monkeypatch.setattr("app.parsers.web.parse_instagram_page", fallback)

    result = await reel.parse_video_reel(URL)
    assert result["title"] == "Instagram 精彩片段"
    # Only the post's text came: marked, so the pipeline keeps it as a fetch failure and refetch retries.
    from app.parsers.transcript import TRANSCRIPT_MISSING
    assert result["content_raw"].startswith("這是 Instagram 貼文說明全文\n\n## 影片逐字稿\n" + TRANSCRIPT_MISSING)
    assert result["transcript_status"] == "failed" and "empty media response" in result["transcript_reason"]
    fallback.assert_awaited_once()


@pytest.mark.asyncio
async def test_empty_cached_reel_is_retried_and_updated(monkeypatch):
    item_id = database.save_item({"url": URL, "source_type": "reel", "content_raw": PLACEHOLDER})
    task = database.create_ingest_task(URL, source="test")

    async def run_pipeline(url):
        assert url == URL
        saved = database.save_item({"url": url, "source_type": "reel", "content_raw": "影片語音內容"})
        return {"id": saved, "url": url}

    monkeypatch.setattr(worker_module, "run_pipeline", run_pipeline)
    worker = worker_module.TaskWorker()
    monkeypatch.setattr(worker, "_trigger_completion_notification", AsyncMock())
    await worker._process_task(task)

    assert database.get_ingest_task(task["id"])["item_id"] == item_id
    assert database.get_item_by_id(item_id)["content_raw"] == "影片語音內容"


@pytest.mark.asyncio
async def test_failed_retry_keeps_old_item_and_marks_task_failed(monkeypatch):
    item_id = database.save_item({"url": URL, "source_type": "reel", "content_raw": PLACEHOLDER})
    task = database.create_ingest_task(URL, source="test")
    monkeypatch.setattr(worker_module, "run_pipeline", AsyncMock(side_effect=reel.ReelUnavailableError("無法取得影片")))

    await worker_module.TaskWorker()._process_task(task)

    assert database.get_ingest_task(task["id"])["status"] == "failed"
    assert database.get_item_by_id(item_id)["content_raw"] == PLACEHOLDER


def test_successful_reel_is_not_treated_as_empty():
    assert not reel.is_empty_reel_metadata({"url": URL, "content_raw": "影片語音內容"})
