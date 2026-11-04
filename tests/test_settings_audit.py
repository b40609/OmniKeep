"""Settings audit page and the first-run setup wizard's server side."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from app import app_settings, connection_checks
from app.config import settings
from app.main import app

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}
KEY = "sk-audit-abcdefghijklmnopqrst1234"


def test_audit_requires_the_api_key():
    with TestClient(app) as client:
        assert client.get("/api/settings/audit").status_code == 401


def test_audit_lists_changes_newest_first_with_labels_and_no_values():
    app_settings.save({"OPENAI_API_KEY": KEY, "PRIMARY_MODEL": "audit-model"})
    app_settings.save({"OPENAI_API_KEY": ""})
    app_settings.save(reset=["PRIMARY_MODEL"])
    with TestClient(app) as client:
        res = client.get("/api/settings/audit", headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert KEY not in res.text and "audit-model" not in res.text
    assert [(e["key"], e["action"]) for e in body["entries"]] == [
        ("PRIMARY_MODEL", "reset"), ("OPENAI_API_KEY", "clear"),
        ("PRIMARY_MODEL", "set"), ("OPENAI_API_KEY", "set")]
    first = body["entries"][0]
    assert (first["label"], first["group"]) == ("分析模型", "AI 服務商")
    assert first["created_at"].endswith("+00:00")
    assert set(first) == {"id", "key", "label", "group", "action", "created_at"}
    assert body["has_more"] is False


def test_audit_pages_with_before():
    for i in range(5):
        app_settings.save({"PRIMARY_MODEL": f"model-{i}"})
    with TestClient(app) as client:
        page = client.get("/api/settings/audit?limit=2", headers=HEADERS).json()
        assert len(page["entries"]) == 2 and page["has_more"] is True
        rest = client.get(f"/api/settings/audit?limit=10&before={page['entries'][-1]['id']}", headers=HEADERS).json()
        assert client.get("/api/settings/audit?limit=0", headers=HEADERS).status_code == 422
    ids = [e["id"] for e in page["entries"] + rest["entries"]]
    assert len(ids) == 5 and ids == sorted(ids, reverse=True) and rest["has_more"] is False


def test_telegram_pairing_shows_up_as_its_own_action():
    from app.bot.telegram_pairing import bind_telegram_user
    assert bind_telegram_user(424242)
    entry = app_settings.audit_log(1)["entries"][0]
    assert (entry["key"], entry["action"], entry["group"]) == ("TELEGRAM_ALLOWED_USER_IDS", "pair", "Telegram")


# ── Setup wizard: what it relies on ──────────────────────────────

class FakeOpenAI:
    seen = []

    def __init__(self, *, base_url, api_key, timeout, max_retries):
        FakeOpenAI.seen.append((base_url, api_key))
        self.models = SimpleNamespace(list=self._list)

    async def _list(self):
        return SimpleNamespace(data=[SimpleNamespace(id="qwen3:8b")])

    async def close(self):
        pass


@pytest.fixture
def fake_openai(monkeypatch):
    FakeOpenAI.seen = []
    monkeypatch.setattr(connection_checks, "AsyncOpenAI", FakeOpenAI)
    return FakeOpenAI


def test_wizard_can_test_a_local_server_that_needs_no_key(fake_openai):
    values = {"OPENAI_BASE_URL": "http://127.0.0.1:11434/v1", "PRIMARY_MODEL": "qwen3:8b"}
    with TestClient(app) as client:
        res = client.post("/api/settings/check/llm", headers=HEADERS, json={"values": values}).json()
    assert res["ok"] is True and "qwen3:8b" in res["message"]
    assert fake_openai.seen == [("http://127.0.0.1:11434/v1", "dummy-key")]


def test_testing_a_keyless_local_server_never_sends_the_saved_key(fake_openai, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", KEY)
    local = {"OPENAI_BASE_URL": "http://127.0.0.1:11434/v1", "PRIMARY_MODEL": "qwen3:8b"}
    with TestClient(app) as client:
        blocked = client.post("/api/settings/check/llm", headers=HEADERS, json={"values": local}).json()
        keyless = client.post("/api/settings/check/llm", headers=HEADERS,
                              json={"values": {**local, "OPENAI_API_KEY": ""}}).json()
    assert blocked["ok"] is False and fake_openai.seen == [("http://127.0.0.1:11434/v1", "dummy-key")]
    assert keyless["ok"] is True


def test_the_default_openai_address_still_needs_a_key(fake_openai):
    with TestClient(app) as client:
        res = client.post("/api/settings/check/llm", headers=HEADERS, json={"values": {}}).json()
    assert res["ok"] is False and "金鑰" in res["message"] and fake_openai.seen == []


def test_saving_what_the_wizard_sends_ends_the_setup_prompt():
    with TestClient(app) as client:
        assert client.get("/api/settings/status", headers=HEADERS).json()["needs_setup"] is True
        res = client.put("/api/settings", headers=HEADERS, json={"values": {
            "PRIMARY_LLM_PROVIDER": "openai_compatible", "OPENAI_BASE_URL": "http://127.0.0.1:11434/v1",
            "PRIMARY_MODEL": "qwen3:8b"}, "reset": []})
        assert res.status_code == 200, res.text
        assert client.get("/api/settings/status", headers=HEADERS).json()["needs_setup"] is False


def test_saving_a_gemini_choice_from_the_wizard_ends_the_setup_prompt():
    with TestClient(app) as client:
        res = client.put("/api/settings", headers=HEADERS, json={"values": {
            "PRIMARY_LLM_PROVIDER": "gemini", "GEMINI_API_KEYS": "AIzaWIZARDWIZARDWIZARD1234",
            "GEMINI_MODEL": "gemini-2.5-flash"}, "reset": []})
        assert res.status_code == 200, res.text
        assert "AIzaWIZARD" not in res.text
        assert client.get("/api/settings/status", headers=HEADERS).json()["needs_setup"] is False
