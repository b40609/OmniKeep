"""caps["extra_body"]: extra request fields (e.g. a reasoning switch) on a connection."""
import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import ai_connections, connection_checks, provider_catalog
from app.ai_connections import AIConfigError
from app.config import settings
from app.main import app
from app.providers import build_provider
from app.providers.openai_compatible import OpenAICompatibleProvider

OFF = {"thinking": {"type": "disabled"}}
HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}


def test_extra_body_is_saved_and_cleared():
    conn = ai_connections.create({"card": "kilo", "caps": {"extra_body": OFF}})
    assert conn.caps["extra_body"] == OFF
    conn = ai_connections.update(conn.id, {"caps": {"extra_body": {}}})
    assert not conn.caps["extra_body"]
    assert build_provider(conn).extra_body is None


@pytest.mark.parametrize("bad", [{"model": "other"}, {"messages": []}, "thinking off", {"x": "y" * 3000}])
def test_extra_body_cannot_override_core_fields_or_be_huge(bad):
    with pytest.raises(AIConfigError) as exc:
        ai_connections.create({"card": "kilo", "caps": {"extra_body": bad}})
    assert "extra_body" in exc.value.errors["caps"]


def test_card_default_reaches_the_provider():
    conn = ai_connections.create({"card": "kilo", "caps": {"extra_body": OFF}})
    assert build_provider(conn).extra_body == OFF


def test_provider_merges_extra_body_into_every_chat_call():
    seen = []

    async def create(**kwargs):
        seen.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))])

    provider = OpenAICompatibleProvider(base_url="http://127.0.0.1:9/v1", api_key="sk-test", model="m",
                                        extra_body=OFF)
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    asyncio.run(provider._chat(model="m", messages=[], extra_body={"top_k": 5}))
    assert seen[0]["extra_body"] == {**OFF, "top_k": 5}


def test_connection_test_sends_the_same_extra_body(monkeypatch):
    seen = []

    class FakeOpenAI:
        def __init__(self, **_):
            self.models = SimpleNamespace(list=self._list)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        async def _list(self):
            return SimpleNamespace(data=[])

        async def _create(self, **kwargs):
            seen.append(kwargs.get("extra_body"))
            message = SimpleNamespace(content='{"回覆": "連線成功", "數字": 42}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        async def close(self):
            pass

    monkeypatch.setattr(connection_checks, "AsyncOpenAI", FakeOpenAI)
    draft = SimpleNamespace(kind="openai", base_url="https://gateway.test/v1", key="", model="m",
                            caps={"json_mode": True, "extra_body": OFF})
    result = asyncio.run(connection_checks.check_connection(draft))
    assert result["ok"] and seen == [OFF]


# ── Per-model presets (NVIDIA's DeepSeek only answers with its reasoning off) ──

DS = "deepseek-ai/deepseek-v4.1-flash"
MINIMAX = "minimaxai/minimax-m3.1-flash"
NV_OFF = {"chat_template_kwargs": {"thinking": False}}
NV_KEY = "nvapi-test-abcdefghijklmnop"


def test_every_preset_is_a_valid_extra_body_for_a_listed_model():
    for card in provider_catalog.CARDS:
        for model, extra in (card.get("model_extra_body") or {}).items():
            assert model in card["models"], (card["id"], model)
            assert ai_connections.validate_extra_body(extra) == extra


def test_picking_a_model_with_a_preset_brings_its_extra_body_and_leaving_drops_it():
    conn = ai_connections.create({"card": "nvidia", "key": NV_KEY})
    assert not conn.caps.get("extra_body")
    conn = ai_connections.update(conn.id, {"model": DS})
    assert conn.caps["extra_body"] == NV_OFF
    assert build_provider(conn).extra_body == NV_OFF
    conn = ai_connections.update(conn.id, {"model": MINIMAX})
    assert not conn.caps.get("extra_body")
    assert ai_connections.create({"card": "nvidia", "key": NV_KEY, "model": DS}).caps["extra_body"] == NV_OFF


def test_extra_body_typed_by_hand_wins_over_the_preset():
    conn = ai_connections.create({"card": "nvidia", "key": NV_KEY, "model": DS, "caps": {"extra_body": {"top_k": 5}}})
    assert conn.caps["extra_body"] == {"top_k": 5}
    conn = ai_connections.update(conn.id, {"model": MINIMAX})
    assert conn.caps["extra_body"] == {"top_k": 5}  # changed by hand, so it stays


def test_a_slot_naming_another_model_gets_that_models_preset():
    nvidia = ai_connections.create({"card": "nvidia", "key": NV_KEY})
    assert build_provider(nvidia, DS).extra_body == NV_OFF
    assert build_provider(nvidia).extra_body is None
    kilo = ai_connections.create({"card": "kilo"})
    # No preset for that model: the connection's own switch is provider-wide.
    assert build_provider(kilo, "kilo-auto/free").extra_body == kilo.caps["extra_body"]


def _fake_openai(monkeypatch):
    seen = []

    class FakeOpenAI:
        def __init__(self, **_):
            self.models = SimpleNamespace(list=self._list)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

        async def _list(self):
            return SimpleNamespace(data=[])

        async def _create(self, **kwargs):
            seen.append(kwargs.get("extra_body"))
            message = SimpleNamespace(content='{"回覆": "連線成功", "數字": 42}')
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

        async def close(self):
            pass

    monkeypatch.setattr(connection_checks, "AsyncOpenAI", FakeOpenAI)
    return seen


def test_the_form_test_sends_what_was_typed_and_refuses_core_fields(monkeypatch):
    seen = _fake_openai(monkeypatch)
    with TestClient(app) as client:
        typed = client.post("/api/ai/test", headers=HEADERS, json={"card": "kilo", "extra_body": {"top_k": 5}}).json()
        cleared = client.post("/api/ai/test", headers=HEADERS, json={"card": "kilo", "extra_body": {}}).json()
        preset = client.post("/api/ai/test", headers=HEADERS,
                             json={"card": "nvidia", "key": NV_KEY, "model": DS}).json()
        bad = client.post("/api/ai/test", headers=HEADERS, json={"card": "kilo", "extra_body": {"model": "x"}}).json()
    assert typed["ok"] and cleared["ok"] and preset["ok"]
    assert seen == [{"top_k": 5}, None, NV_OFF]
    assert not bad["ok"] and "extra_body" in bad["message"]


def test_testing_a_saved_connection_with_a_slot_model_uses_its_preset(monkeypatch):
    seen = _fake_openai(monkeypatch)
    conn = ai_connections.create({"card": "nvidia", "key": NV_KEY})
    with TestClient(app) as client:
        res = client.post(f"/api/ai/connections/{conn.id}/test", headers=HEADERS, params={"model": DS}).json()
    assert res["ok"] and seen == [NV_OFF]
