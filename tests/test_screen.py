"""Text on the screen of long videos that the speech does not say (app/parsers/screen.py)."""
import asyncio
import logging
import shutil
import sys
from unittest.mock import AsyncMock, patch

import pytest

from app.parsers import screen
from app.parsers.transcript import Transcript
from app.pipeline import run_pipeline

REAL_AVAILABLE = screen.available  # conftest turns it off for every test once collected
SAID = "[00:00] 今天我們來談 Anthropic 的營收\n\n[00:31] 第一是企業市場，第二是 Claude Code"


def test_only_what_the_speech_and_earlier_frames_do_not_have_is_listed():
    frames = [
        (2.0, ["解數一下", "今天我們來談Anthropic的營收"]),  # watermark (new once) and a burned-in subtitle
        (21.5, ["解數一下", "資料來源|Menlo Ventures", "企業端市佔率比較 Anthropic 32% OpenAI 25%"]),
        (30.0, ["解數一下", "第一是企業市場"]),  # subtitle only
        (44.0, ["解數一下", "資料來源|Menlo Ventures", "Yahoo股市 -12.31% 2026年2月12日"]),
        (50.0, ["解数一下", "第二是 Claude Code"]),  # Simplified watermark is the same watermark
    ]
    found = screen.novel_lines(frames, SAID)
    assert [at for at, _ in found] == [21.5, 44.0]
    assert found[0][1] == "資料來源|Menlo Ventures / 企業端市佔率比較 Anthropic 32% OpenAI 25%"
    assert found[1][1] == "Yahoo股市 -12.31% 2026年2月12日"  # the source line was shown before


def test_the_section_marks_each_frame_with_its_time_and_stays_small(monkeypatch):
    found = [(65.0, "Menlo Ventures 32%"), (3725.0, "最後一張")]
    text = screen.section(found)
    assert text.splitlines() == [screen.SECTION_TITLE, "影片畫面上的字（投影片、圖表、截圖），只列旁白沒講到的部分。",
                                 "- [01:05] Menlo Ventures 32%", "- [1:02:05] 最後一張"]
    assert "（只讀前 60 分鐘）。" in screen.section(found, "（只讀前 60 分鐘）")
    assert screen.section([]) == ""
    many = [(float(i), "字" * 250) for i in range(200)]
    assert len(screen.section(many)) <= screen.MAX_SECTION_CHARS + 200
    monkeypatch.setattr(screen, "MAX_LINES", 3)
    assert len(screen.section([(float(i), "x") for i in range(10)]).splitlines()) == 2 + 3


def test_missing_packages_skip_the_frames_with_one_log_line(monkeypatch, caplog):
    monkeypatch.setattr(screen, "available", REAL_AVAILABLE)
    monkeypatch.setattr(screen, "_missing_logged", False)
    monkeypatch.setitem(sys.modules, "rapidocr", None)
    monkeypatch.setattr(screen, "_screen_sync", lambda *a: pytest.fail("downloaded the video"))
    with caplog.at_level(logging.WARNING, logger="omnikeep.screen"):
        assert asyncio.run(screen.screen_notes("https://youtu.be/x", {"duration": 600}, SAID)) == ""
        assert asyncio.run(screen.screen_notes("https://youtu.be/y", {"duration": 600}, SAID)) == ""
    hints = [r.getMessage() for r in caplog.records if "requirements-ocr.txt" in r.getMessage()]
    assert len(hints) == 1 and "rapidocr" in hints[0]


def test_frames_are_read_only_for_long_enough_videos_and_never_raise(monkeypatch, caplog):
    monkeypatch.setattr(screen, "available", lambda: True)
    calls = []
    monkeypatch.setattr(screen, "_screen_sync", lambda url, duration, said: calls.append(duration) or "## 畫面重點")
    for info in ({"duration": 45}, {"duration": 3 * 3600}, {}, None):
        assert asyncio.run(screen.screen_notes("https://youtu.be/x", info, SAID)) == ""
    assert asyncio.run(screen.screen_notes("https://youtu.be/x", {"duration": 600}, "  ")) == ""
    assert asyncio.run(screen.screen_notes("https://youtu.be/x", {"duration": 600}, SAID)) == "## 畫面重點"
    assert calls == [600.0]

    def broken(url, duration, said):
        raise RuntimeError("ERROR: Requested format is not available")
    monkeypatch.setattr(screen, "_screen_sync", broken)
    with caplog.at_level(logging.WARNING, logger="omnikeep.screen"):
        assert asyncio.run(screen.screen_notes("https://youtu.be/x", {"duration": 600}, SAID)) == ""
    assert any("Requested format is not available" in r.getMessage() for r in caplog.records)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_a_clip_with_slides_gives_the_slide_text_not_the_subtitles(isolated_runtime):
    if screen.missing_packages():
        pytest.skip("requirements-ocr.txt is not installed")
    import cv2
    import numpy as np
    path = str(isolated_runtime / "slides.avi")
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), 4, (1280, 720))
    slides = [["today we talk about revenue"], ["Source: Menlo Ventures", "Enterprise share 32 percent"],
              ["Stock price down 12.31 percent", "Seen on February 12"]]
    for lines in slides:
        image = np.full((720, 1280, 3), 255, dtype=np.uint8)
        for row, line in enumerate(lines):
            cv2.putText(image, line, (60, 200 + row * 120), cv2.FONT_HERSHEY_SIMPLEX, 2.2, (0, 0, 0), 5)
        for _ in range(4 * 25):  # 25 s each
            writer.write(image)
    writer.release()
    stats = {}
    text = screen.read_screen(path, "[00:00] today we talk about revenue", 75, stats)
    assert stats["kept"] == 3 and stats["ocr_frames"] == 3, stats
    assert text.startswith(screen.SECTION_TITLE) and "today we talk" not in text.lower()
    assert "Menlo" in text and "12.31" in text and "- [00:" in text


AI = {"category": "Inbox", "title_l1": "測試影片分析", "summary_l1": "影片在講營收。",
      "tech_tags": ["AI"], "deep_analysis": "## 重點\n- 一", "is_composite": False, "sub_entities": []}


@pytest.mark.asyncio
async def test_the_analysis_gets_the_screen_text_apart_from_a_long_transcript():
    meta = {"title": "測試影片", "author": "測試頻道", "description": "說明", "cover_image": "", "duration": 600}
    long_said = Transcript("ok", "[00:00] " + "營收" * 20000 + "最後一句", "stt", "zh")
    notes = screen.section([(470.0, "資料來源|Menlo Ventures / 企業端市佔率比較")])
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=dict(AI))
    with patch("app.pipeline.fetch_youtube_metadata", new=AsyncMock(return_value=dict(meta))), \
         patch("app.pipeline.get_transcript", new=AsyncMock(return_value=long_said)), \
         patch("app.pipeline.screen_notes", new=AsyncMock(return_value=notes)) as notes_call, \
         patch("app.pipeline.has_video_provider", return_value=False), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        item = await run_pipeline("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert notes_call.await_args.args[2] == long_said.text
    assert item["content_raw"].endswith("\n\n" + notes)
    prompt = provider.generate_json.await_args.args[0]
    assert "- [07:50] 資料來源|Menlo Ventures" in prompt and "不是旁白" in prompt
    assert "<ocr_text>" in prompt and "</ocr_text>" in prompt
    spoken = prompt.split("<transcript>\n", 1)[1].split("\n</transcript>", 1)[0]
    assert len(spoken) == 30000 and screen.SECTION_TITLE not in spoken


@pytest.mark.asyncio
async def test_no_screen_pass_without_a_transcript():
    meta = {"title": "測試影片", "author": "測試頻道", "description": "說明", "cover_image": "", "duration": 600}
    with patch("app.pipeline.fetch_youtube_metadata", new=AsyncMock(return_value=dict(meta))), \
         patch("app.pipeline.get_transcript", new=AsyncMock(return_value=Transcript("failed", reason="HTTP 403"))), \
         patch("app.pipeline.screen_notes", new=AsyncMock(side_effect=AssertionError("read the frames"))), \
         patch("app.pipeline.has_video_provider", return_value=False):
        item = await run_pipeline("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert screen.SECTION_TITLE not in item["content_raw"]
