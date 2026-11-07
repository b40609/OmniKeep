"""Google Vertex AI (Agent Platform) card: the Gemini provider in express mode, so the
Google AI Pro monthly credit can pay for OmniKeep's calls."""
import asyncio
from types import SimpleNamespace

import pytest

from app import ai_connections, connection_checks, provider_catalog
from app.providers import build_provider
from app.providers.gemini import TIMEOUT_MS, GeminiProvider

KEY = "AQ.test-vertex-key-1234567890"


class FakeClient:
    made = []

    def __init__(self, **kwargs):
        FakeClient.made.append(kwargs)
        self.reply = kwargs.pop("_reply", None)
        self.aio = SimpleNamespace(models=SimpleNamespace(generate_content=self._generate))

    async def _generate(self, **kwargs):
        if FakeClient.fail:
            exc = RuntimeError(f"403 PERMISSION_DENIED blocked for key {KEY}")
            exc.code = 403
            raise exc
        return SimpleNamespace(text='{"回覆": "連線成功", "數字": 42}', usage_metadata=None)


@pytest.fixture
def fake_genai(monkeypatch):
    import google.genai
    FakeClient.made = []
    FakeClient.fail = False
    monkeypatch.setattr(google.genai, "Client", FakeClient)
    return FakeClient


def test_card_is_listed_as_a_gemini_kind_with_vertex_on():
    card = provider_catalog.card("vertex")
    assert card["kind"] == "gemini" and card["caps"]["vertex"] is True
    assert card["model"] in card["models"]
    # YouTube analysis through Vertex with an API key answers 401 (needs OAuth), 2026-11-06.
    assert card["caps"]["video"] is False
    # gemini-2.5-flash is closed to new users (404), so neither card offers it by default.
    assert provider_catalog.card("gemini")["model"] != "gemini-2.5-flash"


def test_provider_talks_to_vertex_only_for_the_vertex_card(fake_genai):
    vertex = ai_connections.create({"card": "vertex", "key": KEY})
    studio = ai_connections.create({"card": "gemini", "key": "AIza-test-key-1234567890"})
    assert isinstance(build_provider(vertex), GeminiProvider) and build_provider(vertex).vertexai is True
    assert build_provider(studio).vertexai is False
    build_provider(vertex).make_client(KEY)
    build_provider(studio).make_client("AIza-test-key-1234567890")
    made = [{k: v for k, v in m.items() if k != "http_options"} for m in fake_genai.made]
    assert made == [{"api_key": KEY, "vertexai": True}, {"api_key": "AIza-test-key-1234567890"}]
    # Without a timeout a stalled connection waits forever.
    assert all(m["http_options"].timeout == TIMEOUT_MS for m in fake_genai.made)


def test_connection_test_uses_vertex_and_hides_the_key(fake_genai):
    conn = ai_connections.create({"card": "vertex", "key": KEY})
    ok = asyncio.run(connection_checks.check_connection(conn))
    assert ok["ok"] and "Vertex" in ok["message"]
    assert fake_genai.made[-1]["api_key"] == KEY and fake_genai.made[-1]["vertexai"] is True
    assert fake_genai.made[-1]["http_options"].timeout == TIMEOUT_MS
    fake_genai.fail = True
    bad = asyncio.run(connection_checks.check_connection(conn))
    assert not bad["ok"] and bad["status"] == 403
    assert KEY not in bad["message"] + bad["detail"]


def test_a_vertex_connection_cannot_take_the_video_slot():
    vertex = ai_connections.create({"card": "vertex", "key": KEY})
    with pytest.raises(ai_connections.AIConfigError) as exc:
        ai_connections.set_slots({"video": [vertex.id]})
    assert "YouTube" in exc.value.errors["video"]


def test_moving_a_connection_to_the_vertex_card_takes_the_vertex_abilities():
    conn = ai_connections.create({"card": "gemini", "key": "AIza-test-key-1234567890"})
    assert conn.caps["video"] is True
    moved = ai_connections.update(conn.id, {"card": "vertex", "key": KEY})
    assert moved.caps["vertex"] is True and moved.caps["video"] is False


def test_thinking_level_reaches_every_gemini_request(fake_genai):
    conn = ai_connections.create({"card": "vertex", "key": KEY, "model": "gemini-3.8-flash",
                                  "caps": {"thinking_level": "high"}})
    provider = build_provider(conn)
    assert provider.thinking_level == "high"
    assert provider._config(temperature=0.2).thinking_config.thinking_level.lower() == "high"
    plain = ai_connections.update(conn.id, {"caps": {"thinking_level": ""}})
    assert build_provider(plain)._config().thinking_config is None


def test_unknown_thinking_level_is_refused():
    with pytest.raises(ai_connections.AIConfigError) as exc:
        ai_connections.create({"card": "vertex", "key": KEY, "caps": {"thinking_level": "max"}})
    assert "思考等級" in exc.value.errors["caps"]
