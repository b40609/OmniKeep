"""The bookmarklet's page title/description reach the pipeline instead of being dropped."""
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import pipeline
from app.config import settings
from app.database import get_item_by_id
from app.main import app
from app.routers import ingest

# What parse_web_page returns when the server only reaches a login wall (app/parsers/web.py).
LOGIN_WALL = {"title": "未知標題", "content_raw": "（未能擷取到網頁內文）", "cover_image": "",
              "author": "", "published_date": "", "raw_html": ""}


def _client():
    return TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"})


def test_ingest_api_hands_normalised_page_hints_to_the_pipeline(monkeypatch):
    run = AsyncMock(return_value={"id": "x"})
    monkeypatch.setattr(ingest, "run_pipeline", run)
    with _client() as client:
        res = client.post("/api/ingest", json={
            "content": "https://example.com/members/post",
            "page_title": "  會員限定\n文章  標題 ",
            "page_description": "長" * 5000,
        })
        assert res.status_code == 200
        client.post("/api/ingest", json={"content": "https://example.com/plain"})
    first, second = run.await_args_list
    assert first.kwargs == {"page_title": "會員限定 文章 標題", "page_description": "長" * 1000}
    assert second.kwargs == {"page_title": "", "page_description": ""}


async def _run(provider_result, **hints):
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=provider_result)
    with patch.object(pipeline, "get_primary_provider", return_value=provider), \
         patch.object(pipeline, "parse_web_page", AsyncMock(return_value=dict(LOGIN_WALL))):
        item = await pipeline.run_pipeline("https://example.com/members/post", **hints)
    return item, provider.generate_json


# The server got no text, so the analysis may only use what the browser saw, and says so
# (app/parsers/blocked.py, 2026-11-07).
async def test_browser_view_rescues_a_login_walled_page():
    item, generate = await _run({}, page_title="會員限定：Rust 非同步實戰", page_description="從 Tokio 到 io_uring 的效能比較")
    prompt = generate.await_args.args[0]
    saved = get_item_by_id(item["id"])
    assert saved["title_l1"] == "會員限定：Rust 非同步實戰"
    assert saved["summary_l1"] == pipeline.METADATA_ONLY_TAG + "從 Tokio 到 io_uring 的效能比較"
    assert "標題：會員限定：Rust 非同步實戰" in prompt
    assert "描述：從 Tokio 到 io_uring 的效能比較" in prompt
    assert "未能擷取到網頁內文" not in prompt


async def test_ai_analysis_still_wins_over_the_hints():
    item, _ = await _run({"title_l1": "AI 標題", "summary_l1": "AI 摘要"}, page_title="瀏覽器標題",
                         page_description="瀏覽器描述")
    assert (item["title_l1"], item["summary_l1"]) == ("AI 標題", pipeline.METADATA_ONLY_TAG + "AI 摘要")


async def test_without_hints_there_is_nothing_to_analyse():
    item, generate = await _run({})
    generate.assert_not_awaited()  # no AI analysis made up from an empty page
    assert item["title_l1"] == "example.com/members/post"
    assert item["summary_l1"].startswith(pipeline.FETCH_FAILED_TAG)
