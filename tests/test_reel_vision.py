"""Short videos: the storyboard is read by whatever the analysis slot is, Facebook's logged-in
page does not wipe the post text, and a clip with nothing readable is a fetch failure (2026-11-09)."""
import asyncio
from contextlib import contextmanager

import pytest

from app.parsers import reel
from app.parsers.transcript import TRANSCRIPT_MISSING
from app.providers.chain import ChainProvider, Member

URL = "https://www.facebook.com/share/r/DemoReel01/"


class TextOnly:
    async def generate_json(self, prompt, system_prompt=None):
        return {}


class Seeing:
    def __init__(self, answer="No.01 AgentGuard"):
        self.answer = answer
        self.calls = 0

    async def describe_image(self, image, prompt, mime_type="image/jpeg"):
        self.calls += 1
        return self.answer


def test_the_chain_reads_an_image_with_the_first_connection_that_can():
    seeing = Seeing()
    chain = ChainProvider([Member(TextOnly(), "a", "text"), Member(seeing, "b", "vision")])
    assert asyncio.run(chain.describe_image(b"jpg", "read")) == "No.01 AgentGuard"
    assert seeing.calls == 1


def _tile(isolated_runtime):
    path = isolated_runtime / "tile.jpg"
    path.write_bytes(b"x" * 2048)
    return str(path)


def test_the_storyboard_is_read_by_a_vertex_primary(monkeypatch, isolated_runtime):
    # Before: only a primary with an OpenAI-style .client.chat was asked, so a Vertex chain gave "".
    chain = ChainProvider([Member(Seeing("畫面：Claude Code /fast"), "vertex", "Vertex")])
    monkeypatch.setattr(reel, "get_primary_provider", lambda: chain)
    monkeypatch.setattr(reel, "has_video_provider", lambda: False)
    assert asyncio.run(reel.analyze_storyboard_vision(_tile(isolated_runtime))) == "畫面：Claude Code /fast"


def test_a_failing_primary_falls_back_to_the_video_slot(monkeypatch, isolated_runtime):
    class Broken:
        async def describe_image(self, *a, **k):
            raise RuntimeError("400 image input not supported")
    monkeypatch.setattr(reel, "get_primary_provider", lambda: Broken())
    monkeypatch.setattr(reel, "has_video_provider", lambda: True)
    monkeypatch.setattr(reel, "get_gemini_provider", lambda: Seeing("from the video slot"))
    assert asyncio.run(reel.analyze_storyboard_vision(_tile(isolated_runtime))) == "from the video slot"
    monkeypatch.setattr(reel, "has_video_provider", lambda: False)
    assert asyncio.run(reel.analyze_storyboard_vision(_tile(isolated_runtime))) == ""


def test_session_lost_metadata():
    assert reel.session_lost_metadata({"title": "Facebook", "description": ""})
    assert reel.session_lost_metadata({"title": " instagram ", "description": None})
    assert not reel.session_lost_metadata({"title": "Facebook", "description": "貼文全文"})
    assert not reel.session_lost_metadata({"title": "14K views · 64 reactions | 一個指令", "description": ""})


def _fake_downloads(monkeypatch, isolated_runtime, with_session, without_session, calls):
    class FakeYDL:
        def __init__(self, opts):
            self.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

        def extract_info(self, url, download=True):
            session = "cookiefile" in self.opts
            calls.append((session, download))
            if download:
                (isolated_runtime / "reel.mp4").write_bytes(b"v")
            return dict(with_session if session else without_session)

    @contextmanager
    def cookies(url):
        yield {"cookiefile": "session.txt"}

    monkeypatch.setattr(reel, "validate_url", lambda url: None)
    monkeypatch.setattr(reel, "ytdlp_cookie_opts", cookies)
    monkeypatch.setattr(reel, "PublicYoutubeDL", FakeYDL)
    monkeypatch.setattr(reel.tempfile, "mkdtemp", lambda prefix="": str(isolated_runtime))
    monkeypatch.setattr(reel.shutil, "rmtree", lambda *a, **k: None)
    monkeypatch.setattr(reel, "extract_scene_tile", lambda *a: False)
    monkeypatch.setattr(reel, "extract_audio_stream", lambda *a: False)


@pytest.mark.asyncio
async def test_facebook_post_text_is_read_again_without_the_session(monkeypatch, isolated_runtime):
    calls = []
    _fake_downloads(monkeypatch, isolated_runtime,
                    {"title": "Facebook", "description": "", "duration": 25},
                    {"title": "14K views · 64 reactions | 一個指令讓 Opus 快 2.5 倍 | Lập Trình Web AI",
                     "description": "Fast Mode 怎麼開：/fast", "uploader": "Lập Trình Web AI", "duration": 25},
                    calls)
    result = await reel.parse_video_reel(URL)
    assert calls == [(True, True), (False, False)]  # the clip once, then only the text
    assert "Fast Mode 怎麼開：/fast" in result["content_raw"]
    assert result["author"] == "Lập Trình Web AI" and result["title"] != "Facebook"
    assert result.get("transcript_status") != "failed"


@pytest.mark.asyncio
async def test_a_clip_with_nothing_readable_is_a_fetch_failure(monkeypatch, isolated_runtime):
    calls = []
    empty = {"title": "Facebook", "description": "", "duration": 25}
    _fake_downloads(monkeypatch, isolated_runtime, empty, empty, calls)
    result = await reel.parse_video_reel(URL)
    assert result["transcript_status"] == "failed"
    assert TRANSCRIPT_MISSING in result["content_raw"]
