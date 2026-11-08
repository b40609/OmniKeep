"""A YouTube video is analysed from what is said in it, never passed off from its title and description.

Survey 2026-10-25 (gap P1) marked title-only analyses; on 2026-11-08 41 of 44 saved videos were
still analysed that way. Now: transcript -> analysis; no transcript -> fetch failure, retried later.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app import pipeline
from app.parsers.transcript import TRANSCRIPT_MISSING, Transcript
from app.pipeline import FETCH_FAILED_TAG, METADATA_ONLY_TAG, run_pipeline

URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
META = {"title": "測試影片", "author": "測試頻道", "description": "這是說明欄", "cover_image": "https://i.ytimg.com/c.jpg"}
AI = {"category": "Inbox", "title_l1": "測試影片分析", "summary_l1": "影片在講向量模型。",
      "tech_tags": ["AI"], "deep_analysis": "## 重點\n- 一", "is_composite": False, "sub_entities": []}
SAID = Transcript("ok", "今天我們來談向量模型怎麼挑，第一是維度，第二是語言。", "stt", "zh")


def _provider():
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=dict(AI))
    return provider


def _patches(transcript, video=False, gemini=None, provider=None):
    return [patch("app.pipeline.fetch_youtube_metadata", new=AsyncMock(return_value=dict(META))),
            patch("app.pipeline.get_transcript", new=AsyncMock(return_value=transcript)),
            patch("app.pipeline.has_video_provider", return_value=video),
            patch("app.pipeline.get_gemini_provider", return_value=gemini),
            patch("app.pipeline.get_primary_provider", return_value=provider or _provider())]


async def _run(*patches):
    for p in patches:
        p.start()
    try:
        return await run_pipeline(URL)
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_the_transcript_is_what_gets_analysed():
    provider = _provider()
    item = await _run(*_patches(SAID, provider=provider))
    prompt = provider.generate_json.await_args.args[0]
    assert "第一是維度" in prompt and "逐字稿" in prompt
    assert "## 影片逐字稿（本機語音轉錄，zh）" in item["content_raw"]
    assert not item["summary_l1"].startswith(METADATA_ONLY_TAG) and "證據不足" not in item["deep_analysis"]


@pytest.mark.asyncio
async def test_no_transcript_is_a_fetch_failure_with_no_ai_call():
    provider = _provider()
    item = await _run(*_patches(Transcript("failed", reason="音訊沒有下載到：HTTP 403"), provider=provider))
    provider.generate_json.assert_not_awaited()
    assert item["summary_l1"].startswith(FETCH_FAILED_TAG) and "HTTP 403" in item["summary_l1"]
    assert item["title_l1"] == "測試影片" and item["cover_image"] == META["cover_image"]
    assert "沒有做 AI 分析" in item["deep_analysis"] and "自動重抓" in item["deep_analysis"]
    assert TRANSCRIPT_MISSING in item["content_raw"]  # app/refetch.py picks it up from this


@pytest.mark.asyncio
async def test_a_failed_video_analysis_falls_back_to_the_transcript():
    gemini = AsyncMock()
    gemini.analyze_youtube = AsyncMock(side_effect=RuntimeError("quota"))
    provider = _provider()
    item = await _run(*_patches(SAID, video=True, gemini=gemini, provider=provider))
    assert "第一是維度" in provider.generate_json.await_args.args[0]
    assert not item["summary_l1"].startswith(METADATA_ONLY_TAG)


@pytest.mark.asyncio
async def test_a_watched_video_is_not_marked_even_without_a_transcript():
    gemini = AsyncMock()
    gemini.analyze_youtube = AsyncMock(return_value=dict(AI))
    item = await _run(*_patches(Transcript("failed", reason="x"), video=True, gemini=gemini))
    assert not item["summary_l1"].startswith((METADATA_ONLY_TAG, FETCH_FAILED_TAG))
    assert "證據不足" not in item["deep_analysis"]


@pytest.mark.asyncio
async def test_a_video_with_no_speech_says_so():
    item = await _run(*_patches(Transcript("no_speech")))
    assert item["summary_l1"].startswith(METADATA_ONLY_TAG)
    assert "沒有辨識到口語內容" in item["deep_analysis"] and "說明欄" in item["deep_analysis"]


def test_note_names_what_was_seen():
    assert "說明欄" in pipeline.metadata_only_note("有說明")
    assert "沒有說明欄" in pipeline.metadata_only_note("  ")
