"""caps["extra_body"]: extra request fields (e.g. a reasoning switch) on a connection."""
import asyncio
from types import SimpleNamespace

import pytest

from app import ai_connections, connection_checks
from app.ai_connections import AIConfigError
from app.providers import build_provider
from app.providers.openai_compatible import OpenAICompatibleProvider

OFF = {"thinking": {"type": "disabled"}}


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
