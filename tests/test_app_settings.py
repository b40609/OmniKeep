"""Settings entered in the app: encrypted at rest, write-only, applied without a restart."""
import asyncio
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app import ai_status, app_settings, connection_checks, secret_box, services
from app.config import settings
from app.database import get_db_connection
from app.main import app

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}
NEW_KEY = "sk-new-abcdefghijklmnopqrst1234"
OLD_KEY = "sk-old-zyxwvutsrqponmlkjihg9876"


@pytest.fixture(autouse=True)
def clean_status():
    ai_status.forget()
    yield
    ai_status.forget()


def _field(body, key):
    for group in body["groups"]:
        for field in group["fields"]:
            if field["key"] == key:
                return field
    raise KeyError(key)


def _row(key):
    with closing(get_db_connection()) as conn:
        return conn.execute("SELECT value, is_secret FROM app_settings WHERE key = ?", (key,)).fetchone()


def _put(client, values=None, reset=None):
    return client.put("/api/settings", headers=HEADERS, json={"values": values or {}, "reset": reset or []})


def test_settings_api_requires_the_api_key():
    with TestClient(app) as client:
        assert client.get("/api/settings").status_code == 401
        assert client.put("/api/settings", json={"values": {"PRIMARY_MODEL": "x"}}).status_code == 401
        assert client.post("/api/settings/check/llm", json={}).status_code == 401


def test_saved_key_is_encrypted_applied_at_once_and_never_returned():
    with TestClient(app) as client:
        res = _put(client, {"OPENAI_API_KEY": NEW_KEY})
        assert res.status_code == 200, res.text
        assert NEW_KEY not in res.text
        field = _field(res.json(), "OPENAI_API_KEY")
        assert field == {**field, "configured": True, "hint": "…1234", "source": "app", "undecryptable": False}
        assert "value" not in field
        assert settings.OPENAI_API_KEY == NEW_KEY  # in effect without a restart

        row = _row("OPENAI_API_KEY")
        assert row["is_secret"] == 1 and row["value"].startswith("fernet1:") and NEW_KEY not in row["value"]
        assert NEW_KEY not in client.get("/api/settings", headers=HEADERS).text

    key_file = secret_box.key_file_path()
    assert key_file.is_file() and key_file.parent == Path(settings.DATABASE_PATH).resolve().parent


def test_env_secret_is_never_returned_either(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", OLD_KEY)
    with TestClient(app) as client:
        res = client.get("/api/settings", headers=HEADERS)
    assert OLD_KEY not in res.text
    assert _field(res.json(), "OPENAI_API_KEY")["source"] == "env"


def test_app_value_beats_env_and_reset_brings_env_back(monkeypatch):
    monkeypatch.setattr(settings, "PRIMARY_MODEL", "env-model")
    with TestClient(app) as client:
        field = _field(client.get("/api/settings", headers=HEADERS).json(), "PRIMARY_MODEL")
        assert (field["source"], field["value"]) == ("env", "env-model")

        field = _field(_put(client, {"PRIMARY_MODEL": "app-model"}).json(), "PRIMARY_MODEL")
        assert (field["source"], field["value"], field["env_value"]) == ("app", "app-model", "env-model")
        assert settings.PRIMARY_MODEL == "app-model"

        field = _field(_put(client, reset=["PRIMARY_MODEL"]).json(), "PRIMARY_MODEL")
        assert (field["source"], field["value"]) == ("env", "env-model")
        assert settings.PRIMARY_MODEL == "env-model"
        assert _row("PRIMARY_MODEL") is None


def test_untouched_setting_reports_the_default():
    with TestClient(app) as client:
        field = _field(client.get("/api/settings", headers=HEADERS).json(), "GEMINI_MODEL")
    assert (field["source"], field["value"]) == ("default", "gemini-2.5-flash")


def test_values_survive_a_restart(monkeypatch):
    from app import database
    with TestClient(app) as client:
        _put(client, {"PRIMARY_MODEL": "kept-model", "OPENAI_API_KEY": NEW_KEY})
    app_settings.restore_baseline()  # what a fresh process starts from
    assert settings.PRIMARY_MODEL != "kept-model"
    database.init_db()
    assert settings.PRIMARY_MODEL == "kept-model" and settings.OPENAI_API_KEY == NEW_KEY


def test_changing_the_address_requires_the_key_again(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", OLD_KEY)
    with TestClient(app) as client:
        res = _put(client, {"OPENAI_BASE_URL": "https://elsewhere.example/v1"})
        assert res.status_code == 400
        assert "OPENAI_API_KEY" in res.json()["errors"]
        assert settings.OPENAI_BASE_URL == "https://api.openai.com/v1"  # nothing was saved

        assert _put(client, {"OPENAI_BASE_URL": "https://api.openai.com/v1/"}).status_code == 200  # same place
        res = _put(client, {"OPENAI_BASE_URL": "https://elsewhere.example/v1/", "OPENAI_API_KEY": NEW_KEY})
        assert res.status_code == 200, res.text
    assert settings.OPENAI_BASE_URL == "https://elsewhere.example/v1"


@pytest.mark.parametrize("values", [
    {"LLM_MAX_CONCURRENCY": 0},
    {"LLM_MIN_REQUEST_INTERVAL": "fast"},
    {"OPENAI_BASE_URL": "ftp://example.com"},
    {"OPENAI_API_KEY": "sk-one\nINJECTED=1"},
    {"OPENAI_API_KEY": "sk two"},
    {"PRIMARY_LLM_PROVIDER": "anthropic-direct"},
    {"TELEGRAM_ALLOWED_USER_IDS": ["123", "abc"]},
    {"VAPID_SUBJECT": "someone@example.com"},
    {"API_KEY": "x" * 40},           # bootstrap settings stay in .env
    {"LOCAL_AUTO_LOGIN": "maybe"},
    {"DATABASE_PATH": "C:/elsewhere.db"},
])
def test_invalid_or_bootstrap_values_are_refused(values):
    with TestClient(app) as client:
        res = _put(client, values)
    assert res.status_code == 400, res.text
    assert set(res.json()["errors"]) == set(values)
    with closing(get_db_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM app_settings").fetchone()[0] == 0


def test_clearing_a_key_overrides_env_and_audit_keeps_no_values(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "ghp_fromenvfromenvfromenv")
    with TestClient(app) as client:
        field = _field(_put(client, {"GITHUB_TOKEN": ""}).json(), "GITHUB_TOKEN")
        assert (field["source"], field["configured"]) == ("app", False)
        assert settings.GITHUB_TOKEN == ""
        _put(client, {"GITHUB_TOKEN": "ghp_newnewnewnewnewnew"})
    with closing(get_db_connection()) as conn:
        audit = [tuple(r) for r in conn.execute("SELECT key, action FROM app_settings_audit ORDER BY id")]
        dump = repr(conn.execute("SELECT * FROM app_settings_audit").fetchall()) + repr(audit)
    assert audit == [("GITHUB_TOKEN", "clear"), ("GITHUB_TOKEN", "set")]
    assert "ghp_" not in dump


def test_hints_never_reveal_short_keys_and_count_gemini_keys():
    with TestClient(app) as client:
        body = _put(client, {"GITHUB_TOKEN": "short", "GEMINI_API_KEYS": "AIzaFIRSTFIRSTFIRST1111, AIzaSECONDSECOND2222"}).json()
    assert _field(body, "GITHUB_TOKEN")["hint"] == ""
    assert _field(body, "GEMINI_API_KEYS")["hint"] == "2 把（…1111、…2222）"
    assert settings.gemini_keys == ["AIzaFIRSTFIRSTFIRST1111", "AIzaSECONDSECOND2222"]


def test_lost_master_key_falls_back_to_env_and_says_so(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", OLD_KEY)  # what .env provides
    with TestClient(app) as client:
        _put(client, {"OPENAI_API_KEY": NEW_KEY})
        assert settings.OPENAI_API_KEY == NEW_KEY

        # The key file is replaced (restored from elsewhere, or deleted and regenerated).
        secret_box.key_file_path().write_bytes(secret_box.Fernet.generate_key())
        secret_box.clear_cache()
        body = client.get("/api/settings", headers=HEADERS).json()
        assert settings.OPENAI_API_KEY == OLD_KEY  # never an empty or garbled key
        assert body["secret_key"]["undecryptable"] == ["OPENAI_API_KEY"]
        assert body["secret_key"]["changed"] is True
        assert _field(body, "OPENAI_API_KEY")["undecryptable"] is True
        # The connection migrated from these settings holds the same key and is flagged too.
        assert client.get("/api/settings/status", headers=HEADERS).json()["undecryptable"] == [
            "OPENAI_API_KEY", "ai_connection:1"]

        body = _put(client, {"OPENAI_API_KEY": NEW_KEY}).json()  # entering it again fixes it
        assert body["secret_key"] == {**body["secret_key"], "undecryptable": [], "changed": False}
        assert settings.OPENAI_API_KEY == NEW_KEY
        assert client.get("/api/settings/status", headers=HEADERS).json()["undecryptable"] == []


def test_saving_llm_settings_rebuilds_the_provider():
    from app.providers import get_primary_provider
    before = get_primary_provider()
    with TestClient(app) as client:
        _put(client, {"OPENAI_API_KEY": NEW_KEY, "PRIMARY_MODEL": "model-b"})
    after = get_primary_provider()
    assert after is not before
    assert (after.api_key, after.model) == (NEW_KEY, "model-b")


def test_saving_pacing_reconfigures_the_shared_limiter():
    from app.providers.rate_limiter import limiter
    with TestClient(app) as client:
        _put(client, {"LLM_MAX_CONCURRENCY": 3, "LLM_MIN_REQUEST_INTERVAL": 0.5})
    assert limiter._concurrency == 3 and limiter.interval == 0.5


def test_saving_a_bot_token_restarts_telegram(monkeypatch):
    restart = AsyncMock()
    monkeypatch.setattr(services, "restart_telegram", restart)
    with TestClient(app) as client:
        _put(client, {"PRIMARY_MODEL": "unrelated"})
        restart.assert_not_awaited()
        _put(client, {"TELEGRAM_BOT_TOKEN": "123456:ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
    restart.assert_awaited_once()


async def test_restart_telegram_swaps_the_poller(monkeypatch):
    from app.bot import telegram_bot
    events = []

    class Bot:
        def __init__(self, name):
            self.name = name

        async def run_polling(self):
            events.append(f"{self.name} polling")
            await asyncio.Event().wait()

        async def close(self):
            events.append(f"{self.name} closed")

    bots = iter([Bot("old"), Bot("new")])
    monkeypatch.setattr(telegram_bot, "get_telegram_bot", lambda: next(bots))
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "1:old")
    assert services.start_telegram()
    await asyncio.sleep(0)
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "2:new")
    await services.restart_telegram()
    await asyncio.sleep(0)
    await services.shutdown()
    assert events == ["old polling", "old closed", "new polling", "new closed"]


def test_import_env_copies_what_env_provides(monkeypatch):
    monkeypatch.setattr(settings, "GITHUB_TOKEN", "ghp_importedimportedimported")
    monkeypatch.setattr(settings, "PRIMARY_MODEL", "env-model")
    with TestClient(app) as client:
        assert {"GITHUB_TOKEN", "PRIMARY_MODEL"} <= set(
            client.get("/api/settings", headers=HEADERS).json()["env_importable"])
        res = client.post("/api/settings/import-env", headers=HEADERS)
    body = res.json()
    assert {"GITHUB_TOKEN", "PRIMARY_MODEL"} <= set(body["imported"])
    assert _field(body, "GITHUB_TOKEN")["source"] == "app"
    assert _row("GITHUB_TOKEN")["value"].startswith("fernet1:")
    assert _row("PRIMARY_MODEL")["value"] == "env-model"
    assert "ghp_" not in res.text


def test_ai_failures_surface_redacted_and_clear_after_saving():
    ai_status.record_failure("llm", 401, "Incorrect API key provided: sk-leakleakleakleak1234")
    with TestClient(app) as client:
        status = client.get("/api/settings/status", headers=HEADERS).json()
        assert status["services"]["llm"]["ok"] is False and status["services"]["llm"]["status"] == 401
        assert "sk-leak" not in str(status)
        assert status["needs_setup"] is True  # no key for the default OpenAI address

        _put(client, {"OPENAI_API_KEY": NEW_KEY})
        status = client.get("/api/settings/status", headers=HEADERS).json()
    assert status["services"] == {} and status["needs_setup"] is False


def test_unbinding_telegram_owner_takes_effect_at_once(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", "1111,2222")
    with TestClient(app) as client:
        field = _field(_put(client, {"TELEGRAM_ALLOWED_USER_IDS": ["2222"]}).json(), "TELEGRAM_ALLOWED_USER_IDS")
    assert field["value"] == ["2222"]
    assert settings.telegram_allowed_ids == [2222]


# ── Connection checks ────────────────────────────────────────────

class FakeOpenAI:
    instances = []
    requests = []

    def __init__(self, *, base_url, api_key, timeout, max_retries):
        self.base_url, self.api_key = base_url, api_key
        self.models = SimpleNamespace(list=self._list)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        FakeOpenAI.instances.append(self)

    async def _list(self):
        if self.api_key == "sk-bad-key-1234567890":
            response = httpx.Response(401, request=httpx.Request("GET", f"{self.base_url}/models"))
            raise openai.AuthenticationError(f"Incorrect API key provided: {self.api_key}",
                                             response=response, body=None)
        return SimpleNamespace(data=[SimpleNamespace(id="gpt-4o-mini")])

    async def _create(self, **kwargs):
        FakeOpenAI.requests.append(kwargs)
        message = SimpleNamespace(content='{"回覆": "連線成功", "數字": 42}')
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    async def close(self):
        pass


@pytest.fixture
def fake_openai(monkeypatch):
    FakeOpenAI.instances = []
    FakeOpenAI.requests = []
    monkeypatch.setattr(connection_checks, "AsyncOpenAI", FakeOpenAI)
    return FakeOpenAI


def test_llm_check_tests_the_typed_key_and_hides_it(fake_openai):
    with TestClient(app) as client:
        bad = client.post("/api/settings/check/llm", headers=HEADERS,
                          json={"values": {"OPENAI_API_KEY": "sk-bad-key-1234567890"}}).json()
        good = client.post("/api/settings/check/llm", headers=HEADERS,
                           json={"values": {"OPENAI_API_KEY": NEW_KEY}}).json()
    assert bad["ok"] is False and bad["status"] == 401 and "停用" in bad["message"]
    assert "sk-bad-key" not in str(bad)
    assert good["ok"] is True and "gpt-4o-mini" in good["message"]
    # Listing models is not enough: a small Chinese json_object request must parse.
    sent = fake_openai.requests[-1]
    assert sent["response_format"] == {"type": "json_object"} and "繁體中文" in sent["messages"][-1]["content"]
    assert good["json_mode"] is True and good["models"] == ["gpt-4o-mini"]
    assert settings.OPENAI_API_KEY == ""  # testing saves nothing


def test_llm_check_never_sends_the_saved_key_to_a_new_address(fake_openai, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", OLD_KEY)
    with TestClient(app) as client:
        res = client.post("/api/settings/check/llm", headers=HEADERS,
                          json={"values": {"OPENAI_BASE_URL": "https://elsewhere.example/v1"}}).json()
    assert res["ok"] is False and "金鑰" in res["message"]
    assert fake_openai.instances == []


@pytest.fixture
def fake_http(monkeypatch):
    calls = []

    def install(handler):
        def client_factory(**kwargs):
            def recorded(request):
                calls.append(request)
                return handler(request)
            return httpx.AsyncClient(transport=httpx.MockTransport(recorded), timeout=kwargs.get("timeout"))
        monkeypatch.setattr("app.network.public_http_client", client_factory)
        return calls

    return install


def test_telegram_check_reports_the_bot_and_scrubs_the_token(fake_http):
    token = "1234:fixture-token-not-a-real-telegram-token"
    calls = fake_http(lambda request: httpx.Response(200, json={"ok": True, "result": {"username": "omni_bot"}}))
    with TestClient(app) as client:
        ok = client.post("/api/settings/check/telegram", headers=HEADERS,
                         json={"values": {"TELEGRAM_BOT_TOKEN": token}}).json()
    assert ok == {**ok, "ok": True, "message": "機器人正常：@omni_bot"}
    assert calls[0].url.path == f"/bot{token}/getMe"

    fake_http(lambda request: httpx.Response(401, text=f"bad token {token}"))
    with TestClient(app) as client:
        bad = client.post("/api/settings/check/telegram", headers=HEADERS,
                          json={"values": {"TELEGRAM_BOT_TOKEN": token}}).json()
    assert bad["ok"] is False and bad["message"] == "機器人權杖無效"
    assert token not in str(bad)


def test_embeddings_check_explains_a_revoked_key(fake_http, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", OLD_KEY)
    fake_http(lambda request: httpx.Response(
        401, json={"error": {"message": "This token status is unavailable"}}))
    with TestClient(app) as client:
        res = client.post("/api/settings/check/embeddings", headers=HEADERS, json={"values": {}}).json()
    assert res["ok"] is False and res["status"] == 401
    assert "This token status is unavailable" in res["detail"]


def test_ollama_address_can_be_blanked_and_brain_settings_apply():
    with TestClient(app) as client:
        res = _put(client, {"OLLAMA_BASE_URL": "", "BRAIN_PROVIDER": "cloud", "BRAIN_MODEL": "qwen3:14b",
                            "BRAIN_MAX_CITATIONS": 8})
        assert res.status_code == 200, res.text
        assert _put(client, {"BRAIN_BASE_URL": ""}).status_code == 400  # only the vector runner may be off
    assert settings.OLLAMA_BASE_URL == ""
    assert (settings.BRAIN_PROVIDER, settings.BRAIN_MODEL, settings.BRAIN_MAX_CITATIONS) == ("cloud", "qwen3:14b", 8)


def _fake_ollama(monkeypatch, handler):
    calls = []

    async def fake(method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return handler(method, url, kwargs)

    monkeypatch.setattr(connection_checks, "_ollama", fake)
    return calls


def test_ollama_check_explains_a_stopped_runner_and_a_missing_model(monkeypatch):
    def down(method, url, kwargs):
        raise httpx.ConnectError("refused")

    _fake_ollama(monkeypatch, down)
    with TestClient(app) as client:
        res = client.post("/api/settings/check/ollama", headers=HEADERS, json={"values": {}}).json()
    assert res["ok"] is False and "Ollama 是否已啟動" in res["message"]

    _fake_ollama(monkeypatch, lambda m, u, k: httpx.Response(404, json={"error": "model not found"}))
    with TestClient(app) as client:
        res = client.post("/api/settings/check/ollama", headers=HEADERS, json={"values": {}}).json()
    assert res["ok"] is False and "ollama pull embeddinggemma-2" in res["message"]

    calls = _fake_ollama(monkeypatch, lambda m, u, k: httpx.Response(200, json={"embeddings": [[0.1] * 768]}))
    with TestClient(app) as client:
        res = client.post("/api/settings/check/ollama", headers=HEADERS,
                          json={"values": {"OLLAMA_BASE_URL": "http://127.0.0.1:11500/"}}).json()
    assert res["ok"] is True and "768" in res["message"]
    assert calls[0][1] == "http://127.0.0.1:11500/api/embed"


def test_brain_check_looks_for_the_configured_model(monkeypatch):
    _fake_ollama(monkeypatch, lambda m, u, k: httpx.Response(200, json={"models": [{"name": "qwen3:8b"}]}))
    with TestClient(app) as client:
        ok = client.post("/api/settings/check/brain", headers=HEADERS, json={"values": {}}).json()
        missing = client.post("/api/settings/check/brain", headers=HEADERS,
                              json={"values": {"BRAIN_MODEL": "llama3.1"}}).json()
        cloud = client.post("/api/settings/check/brain", headers=HEADERS,
                            json={"values": {"BRAIN_PROVIDER": "cloud"}}).json()
    assert ok["ok"] is True and "qwen3:8b" in ok["message"]
    assert missing["ok"] is False and "ollama pull llama3.1" in missing["message"]
    assert cloud["ok"] is True and "設定 › AI" in cloud["message"]


def test_unknown_check_is_404():
    with TestClient(app) as client:
        assert client.post("/api/settings/check/nope", headers=HEADERS, json={}).status_code == 404
