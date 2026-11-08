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
    info = {"automatic_captions": {"fr": [_fmt("json3")], "zh-TW": [_fmt("json3")], "en-orig": [_fmt("json3")]}}
    assert pick_track(info)[:2] == ("auto", "en")
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


def test_no_subtitles_means_the_audio_is_transcribed(monkeypatch, isolated_runtime):
    def download(url, folder):
        path = isolated_runtime / "audio.webm"
        path.write_bytes(b"x")
        return str(path)
    monkeypatch.setattr(tr, "stt_available", lambda: True)
    monkeypatch.setattr(tr, "_download_audio", download)
    monkeypatch.setattr(tr, "transcribe_file", lambda path, max_seconds=tr.MAX_STT_SECONDS: "大家好 今天談向量")
    result = asyncio.run(tr.get_transcript("https://youtu.be/x", _info(language="zh")))
    assert (result.status, result.source, result.text) == ("ok", "stt", "大家好 今天談向量")
    monkeypatch.setattr(tr, "transcribe_file", lambda path, max_seconds=0: "")
    assert asyncio.run(tr.get_transcript("https://youtu.be/x", _info())).status == "no_speech"


def test_every_way_of_not_getting_it_is_a_failure_with_a_reason(monkeypatch):
    monkeypatch.setattr(tr, "stt_available", lambda: False)
    result = asyncio.run(tr.get_transcript("https://youtu.be/x", _info()))
    assert result.status == "failed" and "faster-whisper" in result.reason
    monkeypatch.setattr(tr, "stt_available", lambda: True)
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
    monkeypatch.setattr(tr, "stt_available", lambda: False)
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
