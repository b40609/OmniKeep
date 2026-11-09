"""Video transcripts: subtitles first, then the audio on this machine, and a failure says why."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

from app import database as db
from app import refetch
from app.parsers import transcript as tr
from app.parsers.transcript import TRANSCRIPT_MISSING, Transcript, pick_track, track_text


def _fmt(ext):
    return {"ext": ext, "url": f"https://www.youtube.com/api/timedtext?fmt={ext}"}


def test_the_uploaders_subtitles_in_the_videos_language_come_first():
    info = {"language": "ja",
            "subtitles": {"en": [_fmt("vtt")], "ja": [_fmt("vtt"), _fmt("json3")], "live_chat": [_fmt("json")]},
            "automatic_captions": {"ja-orig": [_fmt("json3")]}}
    source, lang, fmt = pick_track(info)
    assert (source, lang, fmt["ext"]) == ("subtitles", "ja", "json3")


def test_chinese_subtitles_before_english_when_the_language_is_unknown():
    info = {"subtitles": {"en": [_fmt("vtt")], "zh-Hant": [_fmt("vtt")]}}
    assert pick_track(info)[1] == "zh-Hant"


def test_automatic_captions_only_in_the_spoken_language():
    info = {"language": "en", "automatic_captions": {"fr": [_fmt("json3")], "zh-TW": [_fmt("json3")], "en-orig": [_fmt("json3")]}}
    assert pick_track(info)[:2] == ("auto", "en")
    # A Mandarin video whose only "-orig" track is English: a translation, not what is said (2026-11-09).
    assert pick_track({"language": "zh-Hant", "automatic_captions": {"en-orig": [_fmt("json3")], "zh-Hant": [_fmt("json3")]}}) is None
    assert pick_track({"automatic_captions": {"en-orig": [_fmt("json3")]}}) is None  # language unknown
    # Only machine translations of the speech recognition: better to transcribe the audio.
    assert pick_track({"automatic_captions": {"fr": [_fmt("json3")], "de": [_fmt("vtt")]}}) is None
    assert pick_track({}) is None


def test_json3_and_rolling_vtt_become_plain_text():
    body = json.dumps({"events": [{"segs": [{"utf8": "今天"}, {"utf8": "來談"}]}, {"segs": [{"utf8": "\n"}]},
                                  {"segs": [{"utf8": "向量模型"}]}, {"segs": [{"utf8": "with RAG"}]}]})
    assert track_text(body, "json3") == "今天來談向量模型 with RAG"
    vtt = ("WEBVTT\nKind: captions\nLanguage: en\n\n00:00:00.000 --> 00:00:02.000\nso in <c>college</c>\n\n"
           "00:00:02.000 --> 00:00:04.000\nso in college\nI was a major\n\n1\n00:00:04,000 --> 00:00:05,000\nin government\n")
    assert track_text(vtt, "vtt") == "so in college I was a major in government"


def _info(**extra):
    return {"subtitles": {}, "automatic_captions": {}, "duration": 600, **extra}


def test_subtitle_timings_are_kept():
    body = json.dumps({"events": [{"tStartMs": 0, "segs": [{"utf8": "大家好"}]},
                                  {"tStartMs": 1500, "segs": [{"utf8": "\n"}]},
                                  {"tStartMs": 65250, "segs": [{"utf8": "第二段"}]}, {"segs": [{"utf8": "沒有時間"}]}]})
    assert tr.track_segments(body, "json3") == [(0.0, 0.0, "大家好"), (65.25, 65.25, "第二段"), (None, None, "沒有時間")]
    srt = "1\n00:00:01,500 --> 00:00:03,000\n第一句\n2026\n2\n01:02:03,040 --> 01:02:05,000\n第二句\n"
    assert tr.track_segments(srt, "srt") == [(1.5, 1.5, "第一句"), (1.5, 1.5, "2026"), (3723.04, 3723.04, "第二句")]


def test_a_mark_about_every_30_seconds_and_a_heading_per_chapter():
    segments = [(0.0, 4.0, "大家好"), (12.0, 15.0, "今天談向量"), (31.0, 35.0, "第一是維度"),
                (59.5, 62.0, "接著"), (70.0, 72.0, "with RAG"), (3725.0, 3727.0, "最後")]
    chapters = [{"start_time": 0, "end_time": 60, "title": "開場"}, {"start_time": 60.0, "title": " 正題\n"},
                {"start_time": "x", "title": "壞的"}, {"start_time": 3700, "title": ""}]
    assert tr.timed_text(segments, chapters) == (
        "### [00:00] 開場\n\n[00:00] 大家好今天談向量\n\n[00:31] 第一是維度\n\n"
        "### [01:00] 正題\n\n[00:59] 接著 with RAG\n\n[1:02:05] 最後")
    assert tr.timed_text(segments[:2]) == "[00:00] 大家好今天談向量"
    assert tr.timed_text([(None, None, "沒有時間的字幕")]) == "沒有時間的字幕"
    assert tr.stamp(59.9) == "[00:59]" and tr.stamp(3600) == "[1:00:00]" and tr.stamp(None) == "[00:00]"
    assert tr.plain_text(tr.timed_text(segments, chapters)) == "大家好今天談向量\n第一是維度\n接著 with RAG\n最後"


def test_subtitles_come_with_marks_and_chapters(monkeypatch):
    segments = [(0.0, 0.0, "今天來談向量模型怎麼挑"), (40.0, 40.0, "第一是維度，第二是語言")]
    monkeypatch.setattr(tr, "_read_track", lambda url, fmt: segments)
    info = _info(subtitles={"zh-TW": [_fmt("json3")]}, chapters=[{"start_time": 30, "title": "怎麼挑"}])
    result = asyncio.run(tr.get_transcript("https://youtu.be/x", info))
    assert result.text == "[00:00] 今天來談向量模型怎麼挑\n\n### [00:30] 怎麼挑\n\n[00:40] 第一是維度，第二是語言"
    assert result.section().startswith("## 影片逐字稿（上傳者字幕，zh-TW）\n[00:00] ")
    long = [(float(i), float(i), "字" * 100) for i in range(800)]
    monkeypatch.setattr(tr, "_read_track", lambda url, fmt: long)
    assert len(asyncio.run(tr.get_transcript("https://youtu.be/x", info)).text) == tr.MAX_CHARS


def test_simplified_chinese_becomes_taiwan_traditional(monkeypatch, caplog):
    import logging
    import pytest
    pytest.importorskip("opencc")
    monkeypatch.setattr(tr, "_opencc", None)
    assert tr.to_traditional("这个软件的视频信息") == "這個軟體的影片資訊"
    monkeypatch.setattr(tr, "_opencc", None)
    monkeypatch.setitem(__import__("sys").modules, "opencc", None)
    with caplog.at_level(logging.WARNING, logger="omnikeep.transcript"):
        assert tr.to_traditional("这个") == "这个" and tr.to_traditional("软件") == "软件"
    assert sum("requirements-stt.txt" in r.getMessage() for r in caplog.records) == 1


def test_no_subtitles_means_the_audio_is_transcribed(monkeypatch, isolated_runtime):
    def download(url, folder):
        path = isolated_runtime / "audio.webm"
        path.write_bytes(b"x")
        return str(path)
    asked = []
    monkeypatch.setattr(tr, "stt_available", lambda language="": asked.append(language) or True)
    monkeypatch.setattr(tr, "_download_audio", download)

    def transcribe(path, max_seconds=tr.MAX_STT_SECONDS, language=""):
        asked.append(language)
        return [(0.0, 2.5, "大家好"), (2.5, 4.0, "今天談向量")]
    monkeypatch.setattr(tr, "transcribe_file", transcribe)
    result = asyncio.run(tr.get_transcript("https://youtu.be/x", _info(language="zh-Hant")))
    assert (result.status, result.source, result.text) == ("ok", "stt", "[00:00] 大家好今天談向量")
    assert asked == ["zh-Hant", "zh-Hant"]  # the model is picked by the video's language
    monkeypatch.setattr(tr, "transcribe_file", lambda path, max_seconds=0, language="": [])
    assert asyncio.run(tr.get_transcript("https://youtu.be/x", _info())).status == "no_speech"


def test_every_way_of_not_getting_it_is_a_failure_with_a_reason(monkeypatch):
    monkeypatch.setattr(tr, "stt_available", lambda language="": False)
    result = asyncio.run(tr.get_transcript("https://youtu.be/x", _info()))
    assert result.status == "failed" and "faster-whisper" in result.reason
    monkeypatch.setattr(tr, "stt_available", lambda language="": True)
    monkeypatch.setattr(tr, "_download_audio", lambda url, folder: (_ for _ in ()).throw(RuntimeError("ERROR: HTTP Error 403")))
    result = asyncio.run(tr.get_transcript("https://youtu.be/x", _info()))
    assert result.status == "failed" and result.reason == "音訊沒有下載到：HTTP Error 403"
    monkeypatch.setattr(tr, "extract_info", lambda url: (_ for _ in ()).throw(RuntimeError("Video unavailable")))
    result = asyncio.run(tr.get_transcript("https://youtu.be/x", None))
    assert result.status == "failed" and "Video unavailable" in result.reason
    assert asyncio.run(tr.get_transcript("https://youtu.be/x", _info(live_status="is_live"))).reason == "直播還沒結束"
    assert TRANSCRIPT_MISSING in Transcript("failed", reason="r").section()


def test_unreadable_subtitles_fall_through_to_the_audio(monkeypatch):
    monkeypatch.setattr(tr, "_read_track", lambda url, fmt: (_ for _ in ()).throw(RuntimeError("429")))
    monkeypatch.setattr(tr, "stt_available", lambda language="": False)
    result = asyncio.run(tr.get_transcript("https://youtu.be/x", _info(subtitles={"en": [_fmt("vtt")]})))
    assert result.status == "failed" and "faster-whisper" in result.reason


NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


def _save_video(item_id, content):
    db.save_item({"id": item_id, "url": f"https://youtu.be/{item_id}", "source_type": "youtube",
                  "title_l1": "影片", "summary_l1": "（擷取失敗）影片逐字稿沒有讀到", "deep_analysis": "> ⚠️",
                  "content_raw": content, "category_name": "Inbox"})
    conn = db.get_db_connection()
    created = (NOW - timedelta(hours=3)).isoformat()
    conn.execute("UPDATE items SET created_at = ?, updated_at = ? WHERE id = ?", (created, created, item_id))
    conn.commit()
    conn.close()


def test_a_video_without_its_transcript_is_retried_and_parsed_once(monkeypatch):
    refetch._last_try.clear()
    _save_video("vid00000001", "# 影片\n\n" + Transcript("failed", reason="HTTP 403").section())
    _save_video("vid00000002", "# 影片\n\n## 影片逐字稿（上傳者字幕）\n" + "內容" * 50)
    assert [i["id"] for i in refetch.candidates(NOW)] == ["vid00000001"]

    async def fixed(url, origin="manual"):
        conn = db.get_db_connection()
        conn.execute("UPDATE items SET content_raw = ? WHERE url = ?", ("## 影片逐字稿（本機語音轉錄）\n大家好", url))
        conn.commit()
        conn.close()
    with patch("app.pipeline.parse_url", new=AsyncMock(side_effect=AssertionError("parsed twice"))), \
         patch("app.pipeline.run_pipeline", new=AsyncMock(side_effect=fixed)) as run:
        assert asyncio.run(refetch.run_once(NOW))["fixed"] == 1
    run.assert_awaited_once()
    assert refetch.candidates(NOW + timedelta(hours=4)) == []
    refetch._last_try.clear()


def test_a_reel_that_was_not_downloaded_is_a_fetch_failure(monkeypatch):
    from app.pipeline import FETCH_FAILED_TAG, run_pipeline
    page = {"url": "https://www.instagram.com/reel/abc/", "title": "IG reel", "author": "someone",
            "cover_image": "", "published_date": "",
            "content_raw": "貼文文字\n\n## 影片逐字稿\n" + TRANSCRIPT_MISSING + "\n原因：影片沒有下載到：login required",
            "transcript_status": "failed", "transcript_reason": "影片沒有下載到：login required"}
    provider = AsyncMock()
    with patch("app.pipeline.parse_video_reel", new=AsyncMock(return_value=page)), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        item = asyncio.run(run_pipeline("https://www.instagram.com/reel/abc/"))
    provider.generate_json.assert_not_awaited()
    assert item["summary_l1"].startswith(FETCH_FAILED_TAG) and "login required" in item["summary_l1"]
    assert item["title_l1"] == "IG reel"


def test_whispers_hallucinations_on_music_are_not_speech():
    for text in ("You", "You.", "Thank you.", "Thanks for watching!", "字幕由Amara.org社群提供", "嗯", ""):
        assert not tr.spoken(text), text
    assert tr.spoken("大家好 今天談向量") and tr.spoken("Hello everyone, today we talk about RAG")


def test_a_video_attached_to_a_post_adds_its_transcript_or_says_why_not(monkeypatch):
    answers = iter([Transcript("ok", "大家好 今天談向量", "stt"), Transcript("no_speech"),
                    Transcript("failed", reason="音訊沒有下載到：HTTP 403")])
    monkeypatch.setattr(tr, "get_transcript", AsyncMock(side_effect=lambda url, info=None: next(answers)))
    assert asyncio.run(tr.attached_video_section("https://video.twimg.com/a.mp4")).startswith("\n\n## 影片逐字稿（本機語音轉錄）")
    assert asyncio.run(tr.attached_video_section("https://video.twimg.com/b.mp4")) == ""
    failed = asyncio.run(tr.attached_video_section("https://video.twimg.com/c.mp4"))
    assert "HTTP 403" in failed and TRANSCRIPT_MISSING not in failed  # the post itself was read
    assert asyncio.run(tr.attached_video_section("")) == ""
