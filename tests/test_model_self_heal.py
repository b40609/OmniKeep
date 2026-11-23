"""Automatic switch off a retired catalog model on 404 / not_found (2026-11-23)."""
import copy
import time
from datetime import datetime, timezone

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app import ai_connections, ai_status, provider_catalog, providers
from app.config import settings
from app.main import app

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}
GROQ_KEY = "gsk-test-abcdefghijklmnop1111"
NV_KEY = "nvapi-test-abcdefghijklmnop2222"


@pytest.fixture(autouse=True)
def clean_state():
    saved = [copy.deepcopy(c) for c in provider_catalog.CARDS]
    ai_status.forget()
    providers.reset_providers()
    yield
    for card, old in zip(provider_catalog.CARDS, saved):
        card.clear()
        card.update(old)
    ai_status.forget()
    providers.reset_providers()


def _not_found(message: str = "The model `old-model` does not exist"):
    resp = httpx.Response(404, request=httpx.Request("POST", "https://provider.example/v1/chat/completions"))
    return openai.NotFoundError(message, response=resp, body=None)


class FakeProvider:
    def __init__(self, label, model, outcomes, status_key=""):
        self.label = label
        self.model = model
        self.outcomes = list(outcomes)
        self.status_key = status_key
        self.calls = []

    async def generate_json(self, prompt, system_prompt=None):
        self.calls.append(self.model)
        outcome = self.outcomes.pop(0) if self.outcomes else {"from": self.label, "model": self.model}
        if isinstance(outcome, Exception):
            if self.status_key:
                ai_status.record_failure(self.status_key, getattr(outcome, "status_code", None), str(outcome), self.label)
            raise outcome
        if self.status_key:
            ai_status.record_success(self.status_key, self.label)
        return outcome


async def test_chain_switches_retired_model_clears_cooldown_and_next_call_uses_new_model(monkeypatch):
    groq = ai_connections.create({"card": "groq", "key": GROQ_KEY, "model": "llama-3.3-70b-versatile", "label": "Groq"},
                                 slot="analysis")
    ai_connections.create({"card": "flm", "label": "flm"}, slot="analysis")
    seen = []

    def build(conn, model=None):
        seen.append((conn.label, model))
        if conn.label == "Groq":
            outcomes = [_not_found("The model `llama-3.3-70b-versatile` does not exist")] if model == "llama-3.3-70b-versatile" else []
            return FakeProvider("Groq", model, outcomes, status_key=conn.status_key)
        return FakeProvider("flm", model, [], status_key=conn.status_key)

    monkeypatch.setattr(providers, "build_provider", build)

    # First call: Groq 404s -> switches to card default, clears cooldown, this call falls back to flm (no same-call retry).
    first = await providers.get_primary_provider().generate_json("hello")
    assert first == {"from": "flm", "model": "auto"}
    updated = ai_connections.get_connection(groq.id)
    expected = provider_catalog.card("groq")["model"]
    assert updated.model == expected
    assert not ai_status.unusable(groq.status_key)
    assert ai_status.snapshot().get(groq.status_key) is None
    assert seen == [("Groq", "llama-3.3-70b-versatile"), ("flm", "auto")]

    # Second call: Groq is not cooled down and immediately uses the replacement model.
    second = await providers.get_primary_provider().generate_json("hello again")
    assert second == {"from": "Groq", "model": expected}
    assert ("Groq", expected) in seen


async def test_model_still_in_card_list_is_not_switched_and_cools_down(monkeypatch):
    # qwen/qwen3.8-27b is not the card's default, but it is still in groq["models"].
    groq_card = provider_catalog.card("groq")
    listed_non_default = next(m for m in groq_card["models"] if m != groq_card["model"])
    groq = ai_connections.create({"card": "groq", "key": GROQ_KEY, "model": listed_non_default, "label": "Groq"},
                                 slot="analysis")
    ai_connections.create({"card": "flm", "label": "flm"}, slot="analysis")

    def build(conn, model=None):
        outcomes = [_not_found(f"model {model} not found")] if conn.label == "Groq" else []
        return FakeProvider(conn.label, model, outcomes, status_key=conn.status_key)

    monkeypatch.setattr(providers, "build_provider", build)
    assert (await providers.get_primary_provider().generate_json("x"))["from"] == "flm"
    assert ai_connections.get_connection(groq.id).model == listed_non_default
    assert ai_connections.model_switch_info(groq.id) is None
    status = ai_status.snapshot()[groq.status_key]
    assert status["cooldown_seconds"] > 5 * 3600


@pytest.mark.parametrize("payload", [
    {"card": "custom", "base_url": "https://custom.example/v1", "model": "my-old-model"},
    {"card": "omniroute", "base_url": "http://127.0.0.1:20128/v1", "model": "route-old"},
    {"card": "ollama", "base_url": "http://127.0.0.1:11434", "model": "llama3.2:latest"},
])
async def test_cards_without_fixed_model_list_are_never_switched(monkeypatch, payload):
    conn = ai_connections.create(payload, slot="analysis")
    ai_connections.create({"card": "flm", "label": "flm"}, slot="analysis")

    def build(c, model=None):
        outcomes = [_not_found("model not found")] if c.id == conn.id else []
        return FakeProvider(c.label, model, outcomes, status_key=c.status_key)

    monkeypatch.setattr(providers, "build_provider", build)
    assert (await providers.get_primary_provider().generate_json("x"))["from"] == "flm"
    assert ai_connections.get_connection(conn.id).model == payload["model"]
    assert ai_connections.model_switch_info(conn.id) is None
    assert ai_status.snapshot()[conn.status_key]["cooldown_seconds"] > 5 * 3600


async def test_when_card_default_is_still_the_dead_model_nothing_changes(monkeypatch):
    card = provider_catalog.card("groq")
    monkeypatch.setitem(card, "model", "dead-default")
    monkeypatch.setitem(card, "models", ["other-live-model"])
    groq = ai_connections.create({"card": "groq", "key": GROQ_KEY, "model": "dead-default", "label": "Groq"},
                                 slot="analysis")
    ai_connections.create({"card": "flm", "label": "flm"}, slot="analysis")

    def build(c, model=None):
        outcomes = [_not_found("model dead-default not found")] if c.id == groq.id else []
        return FakeProvider(c.label, model, outcomes, status_key=c.status_key)

    monkeypatch.setattr(providers, "build_provider", build)
    assert (await providers.get_primary_provider().generate_json("x"))["from"] == "flm"
    assert ai_connections.get_connection(groq.id).model == "dead-default"
    assert ai_connections.model_switch_info(groq.id) is None
    assert ai_status.snapshot()[groq.status_key]["cooldown_seconds"] > 5 * 3600


def test_matching_slot_entries_are_updated_together_and_others_are_left_alone():
    groq_card = provider_catalog.card("groq")
    expected = groq_card["model"]
    other_live = next(m for m in groq_card["models"] if m != expected)
    dead = "llama-3.3-70b-versatile"

    groq = ai_connections.create({"card": "groq", "key": GROQ_KEY, "model": dead})
    ai_connections.set_slots({
        "analysis": [{"connection_id": groq.id, "model": ""}],          # inherits connection model
        "brain": [{"connection_id": groq.id, "model": dead}],           # explicit dead model -> must update
        "radar": [{"connection_id": groq.id, "model": other_live}],     # explicit other model -> must stay
    })

    switched = ai_connections.replace_retired_model(groq.id, dead)
    assert switched is not None and switched["from"] == dead and switched["to"] == expected
    assert ai_connections.get_connection(groq.id).model == expected
    by_slot = ai_connections.slots()
    assert by_slot["analysis"] == [{"connection_id": groq.id, "model": ""}]
    assert by_slot["brain"] == [{"connection_id": groq.id, "model": expected}]
    assert by_slot["radar"] == [{"connection_id": groq.id, "model": other_live}]


def test_slot_only_dead_override_is_updated_even_when_connection_already_uses_new_model():
    groq_card = provider_catalog.card("groq")
    expected = groq_card["model"]
    dead = "llama-3.1-8b-instant"

    groq = ai_connections.create({"card": "groq", "key": GROQ_KEY, "model": expected})
    ai_connections.set_slots({"brain": [{"connection_id": groq.id, "model": dead}]})

    switched = ai_connections.replace_retired_model(groq.id, dead)
    assert switched is not None and switched["to"] == expected
    assert ai_connections.slots()["brain"] == [{"connection_id": groq.id, "model": expected}]


def test_extra_body_presets_follow_the_model_switch_and_manual_values_survive(monkeypatch):
    old_preset = {"chat_template_kwargs": {"thinking": False}}
    new_preset = {"reasoning": {"effort": "low"}}
    card_default = {"thinking": {"type": "disabled"}}

    # 1. Old model had a preset, new model has none, card has no default -> old preset removed.
    nv = provider_catalog.card("nvidia")
    monkeypatch.setitem(nv, "model", "minimaxai/minimax-m3.1-flash")
    monkeypatch.setitem(nv, "models", ["minimaxai/minimax-m3.1-flash"])
    monkeypatch.setitem(nv, "model_extra_body", {"deepseek-ai/deepseek-v4.1-flash": old_preset})
    c1 = ai_connections.create({"card": "nvidia", "key": NV_KEY, "model": "deepseek-ai/deepseek-v4.1-flash"})
    assert c1.caps.get("extra_body") == old_preset
    assert ai_connections.replace_retired_model(c1.id, "deepseek-ai/deepseek-v4.1-flash") is not None
    c1_after = ai_connections.get_connection(c1.id)
    assert "extra_body" not in c1_after.caps
    assert providers.build_provider(c1_after).extra_body is None

    # 2. Old model had no preset, new model has one -> new preset applied.
    monkeypatch.setitem(nv, "model", "new-reasoning-model")
    monkeypatch.setitem(nv, "models", ["new-reasoning-model"])
    monkeypatch.setitem(nv, "model_extra_body", {"new-reasoning-model": new_preset})
    c2 = ai_connections.create({"card": "nvidia", "key": NV_KEY, "model": "old-plain-model"})
    assert not c2.caps.get("extra_body")
    assert ai_connections.replace_retired_model(c2.id, "old-plain-model") is not None
    c2_after = ai_connections.get_connection(c2.id)
    assert c2_after.caps["extra_body"] == new_preset
    assert providers.build_provider(c2_after).extra_body == new_preset

    # 3. Old model had a per-model preset on a card with a card-level default -> restored to card default.
    zai = provider_catalog.card("zai")
    monkeypatch.setitem(zai, "model", "glm-4.7-flash")
    monkeypatch.setitem(zai, "models", ["glm-4.7-flash"])
    monkeypatch.setitem(zai, "model_extra_body", {"glm-4.0-old": {"custom_flag": True}})
    c3 = ai_connections.create({"card": "zai", "key": GROQ_KEY, "model": "glm-4.0-old"})
    assert c3.caps["extra_body"] == {"custom_flag": True}
    assert ai_connections.replace_retired_model(c3.id, "glm-4.0-old") is not None
    assert ai_connections.get_connection(c3.id).caps["extra_body"] == card_default

    # 4. Manual extra_body survives even when switching to a model that has a preset.
    c4 = ai_connections.create({
        "card": "nvidia", "key": NV_KEY, "model": "old-plain-model",
        "caps": {"extra_body": {"top_k": 5}},
    })
    assert ai_connections.replace_retired_model(c4.id, "old-plain-model") is not None
    assert ai_connections.get_connection(c4.id).caps["extra_body"] == {"top_k": 5}


async def test_throttled_to_at_most_once_per_hour_per_connection(monkeypatch):
    card = provider_catalog.card("groq")
    t0 = 1_800_000_000.0
    now_box = [t0]
    monkeypatch.setattr(ai_connections.time, "time", lambda: now_box[0])

    monkeypatch.setitem(card, "model", "model-v2")
    monkeypatch.setitem(card, "models", ["model-v2"])
    groq = ai_connections.create({"card": "groq", "key": GROQ_KEY, "model": "model-v1", "label": "Groq"},
                                 slot="analysis")
    ai_connections.create({"card": "flm", "label": "flm"}, slot="analysis")

    def build(c, model=None):
        outcomes = [_not_found(f"{model} gone")] if c.id == groq.id else []
        return FakeProvider(c.label, model, outcomes, status_key=c.status_key)

    monkeypatch.setattr(providers, "build_provider", build)

    # First switch at t0 succeeds: model-v1 -> model-v2.
    await providers.get_primary_provider().generate_json("x")
    assert ai_connections.get_connection(groq.id).model == "model-v2"
    assert not ai_status.unusable(groq.status_key)

    # 30 minutes later, catalog moves on again to model-v3, and model-v2 404s.
    # Still within 1 hour -> must NOT switch again; cools down for 6 hours instead.
    now_box[0] = t0 + 1800.0
    monkeypatch.setitem(card, "model", "model-v3")
    monkeypatch.setitem(card, "models", ["model-v3"])
    await providers.get_primary_provider().generate_json("y")
    assert ai_connections.get_connection(groq.id).model == "model-v2"
    assert ai_status.snapshot()[groq.status_key]["cooldown_seconds"] > 5 * 3600

    # After 1 hour passes, switching is allowed again and clears cooldown.
    now_box[0] = t0 + 3601.0
    switched = ai_connections.replace_retired_model(groq.id, "model-v2")
    assert switched is not None and switched["from"] == "model-v2" and switched["to"] == "model-v3"
    assert ai_connections.get_connection(groq.id).model == "model-v3"
    assert not ai_status.unusable(groq.status_key)


def test_switch_notice_appears_in_connections_api_and_clears_on_manual_model_edit():
    ts = time.time()
    expected_date = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().date().isoformat()
    dead = "llama-3.3-70b-versatile"
    new_model = provider_catalog.card("groq")["model"]

    with TestClient(app) as client:
        created = client.post("/api/ai/connections", headers=HEADERS, json={
            "card": "groq", "key": GROQ_KEY, "model": dead, "slot": "analysis",
        }).json()["connection"]
        assert created["model_switch"] is None

        ai_connections.replace_retired_model(created["id"], dead, now=ts)

        listed = client.get("/api/ai/connections", headers=HEADERS).json()["connections"]
        conn = next(c for c in listed if c["id"] == created["id"])
        assert conn["model"] == new_model
        assert conn["model_switch"] == {
            "from": dead,
            "to": new_model,
            "date": expected_date,
            "message": f"模型 {dead} 已下架，已自動改用 {new_model}（{expected_date}）",
        }

        # Toggling enabled does not erase the notice.
        toggled = client.patch(f"/api/ai/connections/{created['id']}", headers=HEADERS,
                               json={"enabled": False}).json()["connection"]
        assert toggled["model_switch"] == conn["model_switch"]

        # Manually changing the model clears the notice.
        other_model = next(m for m in provider_catalog.card("groq")["models"] if m != new_model)
        edited = client.patch(f"/api/ai/connections/{created['id']}", headers=HEADERS,
                              json={"model": other_model}).json()["connection"]
        assert edited["model_switch"] is None
