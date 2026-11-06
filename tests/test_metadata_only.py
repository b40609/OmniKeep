"""A YouTube analysis made from the title and description alone says so (survey 2026-10-25, gap P1)."""
from unittest.mock import AsyncMock, patch

import pytest

from app import pipeline
from app.pipeline import METADATA_ONLY_TAG, run_pipeline

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
META = {"title": "測試影片", "author": "測試頻道", "description": "這是說明欄", "cover_image": ""}
AI = {"category": "Inbox", "title_l1": "測試影片分析", "summary_l1": "影片在講向量模型。",
      "tech_tags": ["AI"], "deep_analysis": "## 重點\n- 一", "is_composite": False, "sub_entities": []}


def _provider():
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=dict(AI))
    return provider


@pytest.mark.asyncio
async def test_no_video_provider_marks_the_analysis_as_title_only():
    with patch("app.pipeline.fetch_youtube_metadata", new=AsyncMock(return_value=dict(META))), \
         patch("app.pipeline.has_video_provider", return_value=False), \
         patch("app.pipeline.get_primary_provider", return_value=_provider()):
        item = await run_pipeline(URL)
    assert item["summary_l1"].startswith(METADATA_ONLY_TAG)
    assert item["deep_analysis"].startswith("> ⚠️ 證據不足") and "## 重點" in item["deep_analysis"]
    assert "說明欄" in item["deep_analysis"]


@pytest.mark.asyncio
async def test_a_failed_video_analysis_falls_back_and_is_marked():
    gemini = AsyncMock()
    gemini.analyze_youtube = AsyncMock(side_effect=RuntimeError("quota"))
    with patch("app.pipeline.fetch_youtube_metadata", new=AsyncMock(return_value={**META, "description": ""})), \
         patch("app.pipeline.has_video_provider", return_value=True), \
         patch("app.pipeline.get_gemini_provider", return_value=gemini), \
         patch("app.pipeline.get_primary_provider", return_value=_provider()):
        item = await run_pipeline(URL)
    assert item["summary_l1"].startswith(METADATA_ONLY_TAG)
    assert "沒有說明欄" in item["deep_analysis"]


@pytest.mark.asyncio
async def test_a_watched_video_is_not_marked():
    gemini = AsyncMock()
    gemini.analyze_youtube = AsyncMock(return_value=dict(AI))
    with patch("app.pipeline.fetch_youtube_metadata", new=AsyncMock(return_value=dict(META))), \
         patch("app.pipeline.has_video_provider", return_value=True), \
         patch("app.pipeline.get_gemini_provider", return_value=gemini), \
         patch("app.pipeline.get_primary_provider", return_value=_provider()):
        item = await run_pipeline(URL)
    assert not item["summary_l1"].startswith(METADATA_ONLY_TAG)
    assert "證據不足" not in item["deep_analysis"]


def test_note_names_what_was_seen():
    assert "說明欄" in pipeline.metadata_only_note("有說明")
    assert "沒有說明欄" in pipeline.metadata_only_note("  ")
