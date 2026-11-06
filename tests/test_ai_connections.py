"""設定 › AI 服務商: connections, task slots, the fallback chain, tests and the migration."""
from contextlib import closing
from types import SimpleNamespace

import httpx
import openai
import pytest
from fastapi.testclient import TestClient

from app import ai_connections, ai_status, app_settings, connection_checks, error_translate, providers
from app.config import settings
from app.database import get_db_connection
from app.main import app
from app.providers.chain import ChainProvider

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}
AGNES_KEY = "sk-agnes-abcdefghijklmnop1111"
AGNES_KEY_2 = "wk-agnes-qrstuvwxyzabcdef2222"
GEMINI_KEY = "AIzaGEMINIGEMINIGEMINI3333"


@pytest.fixture(autouse=True)
def clean_state():
    ai_status.forget()
    providers.reset_providers()
    yield
    ai_status.forget()
    providers.reset_providers()


def _status_error(cls, status, message):
    response = httpx.Response(status, request=httpx.Request("POST", "https://provider.example/v1/chat/completions"))
    return cls(message, response=response, body=None)


def _agnes(client, key=AGNES_KEY, slot="analysis", label="Agnes"):
    res = client.post("/api/ai/connections", headers=HEADERS,
                      json={"card": "agnes", "key": key, "slot": slot, "label": label})
    assert res.status_code == 201, res.text
    return res.json()["connection"]


# ── Catalog ──────────────────────────────────────────────────────

def test_catalog_lists_options_without_a_default_or_subscription_routes():
    with TestClient(app) as client:
        cards = client.get("/api/ai/catalog", headers=HEADERS).json()["cards"]
    ids = [c["id"] for c in cards]
    for wanted in ("agnes", "gemini", "groq", "cloudflare", "openrouter", "zai", "inception", "tokenharbor",
                   "requesty", "nvidia", "aihubmix", "sealion", "itera", "kilo", "ovh", "omniroute", "ollama",
                   "deepseek", "openai", "custom"):
        assert wanted in ids
    assert len(set(ids)) == len(ids)
    for card in cards:
        assert card["verified"] and card["kind"] in ("openai", "gemini", "ollama")
        assert "default" not in card and not card.get("recommended")
        assert card.get("key_url", "").startswith("https://") or card["key_mode"] != "required"
    text = str(cards).lower()
    assert "claude" not in text and "chatgpt" not in text and "antigravity" not in text


# ── Connections API ──────────────────────────────────────────────

def test_keys_are_encrypted_and_never_returned():
    with TestClient(app) as client:
        conn = _agnes(client)
        listed = client.get("/api/ai/connections", headers=HEADERS)
    assert AGNES_KEY not in listed.text
    assert conn["key_configured"] is True and conn["key_hint"] == "…1111"
    assert conn["base_url"] == "https://apihub.agnes-ai.com/v1" and conn["used_in"] == ["analysis"]
    with closing(get_db_connection()) as db:
        stored = db.execute("SELECT key_enc FROM ai_connections WHERE id = ?", (conn["id"],)).fetchone()[0]
    assert stored.startswith("fernet1:") and AGNES_KEY not in stored
    assert listed.json()["needs_setup"] is False


@pytest.mark.parametrize("body, field", [
    ({"card": "agnes"}, "key"),
    ({"card": "nope", "key": "x"}, "card"),
    ({"card": "cloudflare", "key": "cf-token"}, "base_url"),  # <帳號 ID> left in the address
    ({"card": "custom", "base_url": "ftp://x.example", "model": "m"}, "base_url"),
    ({"card": "custom", "base_url": "https://x.example/v1", "model": ""}, "model"),
    ({"card": "agnes", "key": "sk two"}, "key"),
])
def test_invalid_connections_are_refused(body, field):
    with TestClient(app) as client:
        res = client.post("/api/ai/connections", headers=HEADERS, json=body)
    assert res.status_code == 400 and field in res.json()["errors"], res.text


def test_a_saved_key_never_follows_a_new_address():
    with TestClient(app) as client:
        conn = _agnes(client)
        moved = client.patch(f"/api/ai/connections/{conn['id']}", headers=HEADERS,
                             json={"base_url": "https://elsewhere.example/v1"})
        assert moved.status_code == 400 and "金鑰" in moved.json()["errors"]["key"]
        renamed = client.patch(f"/api/ai/connections/{conn['id']}", headers=HEADERS,
                               json={"label": "Agnes 個人", "min_interval": 7})
        assert renamed.status_code == 200
        assert renamed.json()["connection"]["key_hint"] == "…1111"  # key kept
        assert renamed.json()["connection"]["effective_interval"] == 7


def test_deleting_a_connection_takes_it_out_of_every_slot():
    with TestClient(app) as client:
        first = _agnes(client)
        second = _agnes(client, AGNES_KEY_2, label="Agnes 企業")
        client.put("/api/ai/slots", headers=HEADERS, json={"slots": {"radar": [second["id"], first["id"]]}})
        body = client.delete(f"/api/ai/connections/{first['id']}", headers=HEADERS).json()
    by_slot = {s["id"]: s["entries"] for s in body["slots"]}
    assert by_slot["analysis"] == [{"connection_id": second["id"], "model": ""}]
    assert by_slot["radar"] == [{"connection_id": second["id"], "model": ""}]


def test_slots_check_what_each_task_can_use():
    with TestClient(app) as client:
        agnes = _agnes(client)
        gemini = client.post("/api/ai/connections", headers=HEADERS,
                             json={"card": "gemini", "key": GEMINI_KEY}).json()["connection"]
        bad_video = client.put("/api/ai/slots", headers=HEADERS, json={"slots": {"video": [agnes["id"]]}})
        assert bad_video.status_code == 400 and "Gemini" in bad_video.json()["detail"]
        bad_vec = client.put("/api/ai/slots", headers=HEADERS, json={"slots": {"embeddings": [gemini["id"]]}})
        assert bad_vec.status_code == 400
        dup = client.put("/api/ai/slots", headers=HEADERS, json={"slots": {"analysis": [agnes["id"], agnes["id"]]}})
        assert dup.status_code == 400
        ok = client.put("/api/ai/slots", headers=HEADERS, json={"slots": {
            "video": [gemini["id"]], "analysis": [{"connection_id": agnes["id"]}, {"connection_id": gemini["id"]}]}})
        assert ok.status_code == 200 and ok.json()["reindex_hint"] is False
    assert providers.has_video_provider()
    assert isinstance(providers.get_gemini_provider(), ChainProvider)
    assert providers.get_gemini_provider().model == "gemini-2.5-flash"  # reel.py reads it directly


def test_changing_the_embedding_model_asks_for_a_rebuild():
    with TestClient(app) as client:
        ollama = client.post("/api/ai/connections", headers=HEADERS, json={"card": "ollama"}).json()["connection"]
        res = client.put("/api/ai/slots", headers=HEADERS, json={"slots": {
            "embeddings": [{"connection_id": ollama["id"], "model": "qwen3-embedding:0.6b"}]}})
    assert res.json()["reindex_hint"] is True


# ── Slots and the provider each task gets ────────────────────────

def test_empty_slots_keep_the_older_behaviour():
    analysis = providers.get_primary_provider()
    assert not isinstance(analysis, ChainProvider)  # OPENAI_* settings
    assert providers.get_provider("radar") is analysis
    assert providers.get_provider("video") is None and not providers.has_video_provider()


def test_brain_and_radar_follow_analysis_after_their_own_list():
    with TestClient(app) as client:
        agnes = _agnes(client)
        ollama = client.post("/api/ai/connections", headers=HEADERS, json={"card": "ollama"}).json()["connection"]
        client.put("/api/ai/slots", headers=HEADERS, json={"slots": {"brain": [ollama["id"]]}})
    brain = providers.get_provider("brain")
    assert [m.label for m in brain.members] == ["本機 Ollama", "Agnes"]
    # app/brain.py asks Ollama itself first, then takes the rest of the chain.
    cloud = providers.get_provider("brain", skip_kinds=("ollama",))
    assert [m.label for m in cloud.members] == ["Agnes"]
    assert [m.label for m in providers.get_provider("radar").members] == ["Agnes"]
    assert providers.get_primary_provider().members[0].provider.base_url == "https://apihub.agnes-ai.com/v1"
    assert agnes["id"] != ollama["id"]
    # Ollama chat goes through its OpenAI-compatible /v1 endpoint with a placeholder key.
    local = brain.members[0].provider
    assert local.base_url == "http://127.0.0.1:11434/v1" and local.api_key == "dummy-key"


def test_brain_slot_writes_back_the_settings_ask_brain_reads():
    with TestClient(app) as client:
        agnes = _agnes(client)
        ollama = client.post("/api/ai/connections", headers=HEADERS,
                             json={"card": "ollama", "base_url": "http://127.0.0.1:11500"}).json()["connection"]
        client.put("/api/ai/slots", headers=HEADERS, json={"slots": {
            "brain": [{"connection_id": ollama["id"], "model": "qwen3:14b"}]}})
        assert (settings.BRAIN_PROVIDER, settings.BRAIN_BASE_URL, settings.BRAIN_MODEL) == (
            "ollama", "http://127.0.0.1:11500", "qwen3:14b")
        client.put("/api/ai/slots", headers=HEADERS, json={"slots": {"brain": [agnes["id"]]}})
        assert settings.BRAIN_PROVIDER == "cloud"


# ── The fallback chain ───────────────────────────────────────────

class Fake:
    def __init__(self, label, outcomes):
        self.label, self.outcomes, self.calls = label, list(outcomes), 0
        self.model = f"{label}-model"

    async def generate_json(self, prompt, system_prompt=None):
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else {"from": self.label}
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


@pytest.fixture
def two_agnes(monkeypatch):
    fakes = {}

    def build(conn, model=None):
        return fakes[conn.label]

    monkeypatch.setattr(providers, "build_provider", build)
    with TestClient(app) as client:
        first = _agnes(client, label="primary")
        second = _agnes(client, AGNES_KEY_2, label="backup")
    return fakes, f"c{first['id']}", f"c{second['id']}"


async def test_a_bad_key_moves_to_the_next_connection_and_the_next_call_starts_over(two_agnes):
    fakes, primary_key, _ = two_agnes
    fakes["primary"] = Fake("primary", [_status_error(openai.AuthenticationError, 401, "Incorrect API key provided"),
                                        {"from": "primary"}])
    fakes["backup"] = Fake("backup", [])
    chain = providers.get_primary_provider()
    assert await chain.generate_json("x") == {"from": "backup"}
    assert ai_status.get(primary_key)["kind"] == "auth"
    assert await chain.generate_json("x") == {"from": "primary"}  # the primary is tried first again


async def test_a_disabled_key_needs_a_person_and_is_skipped(two_agnes):
    fakes, primary_key, _ = two_agnes
    fakes["primary"] = Fake("primary", [_status_error(openai.AuthenticationError, 401,
                                                      "This token status is unavailable (request id: abc)")])
    fakes["backup"] = Fake("backup", [])
    chain = providers.get_primary_provider()
    assert await chain.generate_json("x") == {"from": "backup"}
    state = ai_status.get(primary_key)
    assert state["action_required"] is True and "platform.agnes-ai.com" in state["hint"]
    assert await chain.generate_json("x") == {"from": "backup"}
    assert fakes["primary"].calls == 1  # not retried automatically


async def test_a_rate_limited_connection_cools_down_and_the_backup_takes_over(two_agnes):
    fakes, primary_key, _ = two_agnes
    fakes["primary"] = Fake("primary", [_status_error(openai.RateLimitError, 429, "rate limit for free users")])
    fakes["backup"] = Fake("backup", [])
    chain = providers.get_primary_provider()
    assert await chain.generate_json("x") == {"from": "backup"}
    assert ai_status.snapshot()[primary_key]["cooldown_seconds"] > 0
    assert await chain.generate_json("x") == {"from": "backup"}
    assert fakes["primary"].calls == 1


async def test_when_everything_fails_a_rate_limit_wins_so_the_worker_backs_off(two_agnes):
    fakes, _, _ = two_agnes
    fakes["primary"] = Fake("primary", [_status_error(openai.RateLimitError, 429, "rate limit for free users")])
    fakes["backup"] = Fake("backup", [_status_error(openai.AuthenticationError, 401, "Incorrect API key")])
    with pytest.raises(openai.RateLimitError):
        await providers.get_primary_provider().generate_json("x")


async def test_a_single_connection_behaves_like_before(monkeypatch):
    fake = Fake("only", [_status_error(openai.RateLimitError, 429, "slow down"), {"from": "only"}])
    monkeypatch.setattr(providers, "build_provider", lambda conn, model=None: fake)
    with TestClient(app) as client:
        _agnes(client, label="only")
    chain = providers.get_primary_provider()
    with pytest.raises(openai.RateLimitError):
        await chain.generate_json("x")
    assert await chain.generate_json("x") == {"from": "only"}  # cooling down, but nothing else to use


def test_each_connection_has_its_own_limiter():
    with TestClient(app) as client:
        _agnes(client, label="a")
        _agnes(client, AGNES_KEY_2, label="b")
    a, b = providers.get_primary_provider().members
    assert a.provider.limiter is not b.provider.limiter
    assert a.provider.limiter.interval == 7.0  # Agnes card default: about 8.5 requests a minute


# ── Testing a connection ─────────────────────────────────────────

class FakeOpenAI:
    reply = '{"回覆": "連線成功", "數字": 42}'
    fail = None
    seen = []

    def __init__(self, *, base_url, api_key, timeout, max_retries):
        self.base_url, self.api_key = base_url, api_key
        self.models = SimpleNamespace(list=self._list)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _list(self):
        return SimpleNamespace(data=[SimpleNamespace(id="agnes-3.0-flash")])

    async def _create(self, **kwargs):
        FakeOpenAI.seen.append((self.base_url, self.api_key, kwargs))
        if FakeOpenAI.fail:
            raise FakeOpenAI.fail
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=FakeOpenAI.reply))])

    async def close(self):
        pass


@pytest.fixture
def fake_openai(monkeypatch):
    FakeOpenAI.fail, FakeOpenAI.seen = None, []
    FakeOpenAI.reply = '{"回覆": "連線成功", "數字": 42}'
    monkeypatch.setattr(connection_checks, "AsyncOpenAI", FakeOpenAI)
    return FakeOpenAI


def test_testing_sends_a_small_chinese_json_request_and_lights_the_status(fake_openai):
    with TestClient(app) as client:
        conn = _agnes(client)
        res = client.post(f"/api/ai/connections/{conn['id']}/test", headers=HEADERS).json()
        status = client.get("/api/settings/status", headers=HEADERS).json()
    assert res["ok"] is True and "agnes-3.0-flash" in res["message"] and res["models"] == ["agnes-3.0-flash"]
    base_url, key, sent = fake_openai.seen[-1]
    assert base_url == "https://apihub.agnes-ai.com/v1" and key == AGNES_KEY
    assert sent["response_format"] == {"type": "json_object"} and "繁體中文" in sent["messages"][-1]["content"]
    assert status["services"][f"c{conn['id']}"]["ok"] is True
    assert AGNES_KEY not in str(res) + str(status)


def test_a_disabled_key_is_explained_in_chinese(fake_openai):
    fake_openai.fail = _status_error(openai.AuthenticationError, 401,
                                     f"This token status is unavailable for {AGNES_KEY}")
    with TestClient(app) as client:
        conn = _agnes(client)
        res = client.post(f"/api/ai/connections/{conn['id']}/test", headers=HEADERS).json()
        status = client.get("/api/settings/status", headers=HEADERS).json()["services"][f"c{conn['id']}"]
    assert res["ok"] is False and "金鑰被停用" in res["message"] and res["action_required"] is True
    assert AGNES_KEY not in str(res)
    assert status["action_required"] is True and status["label"] == "Agnes"


def test_a_reply_that_is_not_json_fails_the_test(fake_openai):
    fake_openai.reply = "好的，連線成功！"
    with TestClient(app) as client:
        res = client.post("/api/ai/test", headers=HEADERS, json={"card": "agnes", "key": AGNES_KEY}).json()
    assert res["ok"] is False and "JSON" in res["message"]


def test_a_model_without_json_mode_is_retried_plainly_and_remembered(fake_openai):
    calls = []

    async def create(self, **kwargs):
        calls.append(kwargs)
        if "response_format" in kwargs:
            raise _status_error(openai.BadRequestError, 400, "response_format is not supported")
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='```json\n{"ok": 1}\n```'))])

    fake_openai._create = create
    with TestClient(app) as client:
        conn = _agnes(client)
        res = client.post(f"/api/ai/connections/{conn['id']}/test", headers=HEADERS).json()
        listed = client.get("/api/ai/connections", headers=HEADERS).json()["connections"]
        caps = next(c for c in listed if c["id"] == conn["id"])["caps"]
    assert res["ok"] is True and res["json_mode"] is False and len(calls) == 2
    assert caps["json_mode"] is False
    provider = providers.get_primary_provider().members[0].provider
    assert provider.json_mode is False


def test_unsaved_test_needs_a_key_and_the_real_address(fake_openai):
    with TestClient(app) as client:
        missing = client.post("/api/ai/test", headers=HEADERS, json={"card": "agnes"}).json()
        placeholder = client.post("/api/ai/test", headers=HEADERS, json={"card": "cloudflare", "key": "t"}).json()
    assert missing["ok"] is False and "金鑰" in missing["message"]
    assert placeholder["ok"] is False and "帳號 ID" in placeholder["message"]
    assert fake_openai.seen == []


# ── Error translation ────────────────────────────────────────────

@pytest.mark.parametrize("status, message, words, action", [
    (401, "This token status is unavailable", "金鑰被停用", True),
    (429, "rate limit for free users", "7 秒", False),
    (401, "Incorrect API key provided: sk-...", "金鑰錯誤", False),
    (400, "API key not valid. Please pass a valid API key.", "金鑰錯誤", False),
    (402, "Insufficient Balance", "儲值", True),
    (404, "The model `gpt-9` does not exist", "模型名稱", False),
    (503, "upstream overloaded", "暫時故障", False),
    (None, "ConnectError: All connection attempts failed", "連不上", False),
])
def test_errors_become_chinese_instructions(status, message, words, action):
    info = error_translate.translate(status, message)
    assert words in info["hint"] and info["action_required"] is action


# ── Migration from the flat settings ─────────────────────────────

def test_migration_turns_the_flat_settings_into_connections(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://apihub.agnes-ai.com/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", AGNES_KEY)
    monkeypatch.setattr(settings, "PRIMARY_MODEL", "agnes-3.0-flash")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS_RAW", GEMINI_KEY)
    monkeypatch.setattr(settings, "LLM_MIN_REQUEST_INTERVAL", 7.0)
    with TestClient(app):
        pass
    conns = {c.origin: c for c in ai_connections.list_connections()}
    assert set(conns) == {"legacy_openai", "legacy_gemini", "legacy_ollama"}
    assert conns["legacy_openai"].card == "agnes" and conns["legacy_openai"].key == AGNES_KEY
    assert conns["legacy_openai"].interval() == 7.0
    slots = ai_connections.slots()
    assert [e["connection_id"] for e in slots["analysis"]] == [conns["legacy_openai"].id]
    assert [e["connection_id"] for e in slots["video"]] == [conns["legacy_gemini"].id]
    assert [(e["connection_id"], e["model"]) for e in slots["brain"]] == [(conns["legacy_ollama"].id, "qwen3:8b")]
    # Agnes has no vectors, so it is not put behind Ollama in the embeddings slot.
    assert [(e["connection_id"], e["model"]) for e in slots["embeddings"]] == [
        (conns["legacy_ollama"].id, "embeddinggemma-2")]
    provider = providers.get_primary_provider()
    assert (provider.base_url, provider.api_key, provider.model) == (
        "https://apihub.agnes-ai.com/v1", AGNES_KEY, "agnes-3.0-flash")
    assert ai_connections.migrate_legacy() is False  # once per database


def test_migration_keeps_a_custom_address_as_the_embeddings_fallback(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://vllm.example.test/v1")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", AGNES_KEY)
    with TestClient(app):
        pass
    conns = {c.origin: c for c in ai_connections.list_connections()}
    assert conns["legacy_openai"].card == "custom"
    embed_ids = [e["connection_id"] for e in ai_connections.slots()["embeddings"]]
    assert conns["legacy_openai"].id in embed_ids


def test_a_fresh_install_gets_no_preselected_provider():
    with TestClient(app) as client:
        body = client.get("/api/ai/connections", headers=HEADERS).json()
    assert [c["card"] for c in body["connections"]] == ["ollama"]  # what the vector search already tried
    by_slot = {s["id"]: s["entries"] for s in body["slots"]}
    assert by_slot["analysis"] == [] and body["needs_setup"] is True


def test_flat_settings_saved_by_older_clients_reach_the_migrated_connection(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", AGNES_KEY)
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://apihub.agnes-ai.com/v1")
    with TestClient(app) as client:
        res = client.put("/api/settings", headers=HEADERS, json={"values": {
            "OPENAI_API_KEY": AGNES_KEY_2, "PRIMARY_MODEL": "agnes-3.5-flash"}, "reset": []})
        assert res.status_code == 200, res.text
    conn = next(c for c in ai_connections.list_connections() if c.origin == "legacy_openai")
    assert (conn.key, conn.model) == (AGNES_KEY_2, "agnes-3.5-flash")
    assert providers.get_primary_provider().api_key == AGNES_KEY_2


def test_rotating_the_master_key_re_encrypts_connection_keys():
    with TestClient(app) as client:
        conn = _agnes(client)
    app_settings.save({"GITHUB_TOKEN": "ghp_rotaterotaterotate"})
    result = app_settings.rotate_master_key()
    assert f"ai_connection:{conn['id']}" in result["rotated"]
    assert ai_connections.get_connection(conn["id"]).key == AGNES_KEY


def test_embeddings_slot_is_used_and_local_runners_stay_off_in_tests():
    from app import vector
    with TestClient(app) as client:
        ollama = client.post("/api/ai/connections", headers=HEADERS, json={"card": "ollama"}).json()["connection"]
        client.put("/api/ai/slots", headers=HEADERS, json={"slots": {"embeddings": [ollama["id"]]}})
    assert vector.embedding_slot()[0][1] == "embeddinggemma-2"
    assert vector.target_embedding_model() == vector.LOCAL_EMBEDDING_MODEL  # Ollama is never reached in tests


def test_the_vector_test_uses_the_embedding_model(monkeypatch):
    calls = []

    async def fake_ollama(method, url, **kwargs):
        calls.append((url, kwargs.get("json", {}).get("model")))
        return httpx.Response(200, json={"embeddings": [[0.1] * 768]})

    monkeypatch.setattr(connection_checks, "_ollama", fake_ollama)
    with TestClient(app) as client:
        ollama = client.post("/api/ai/connections", headers=HEADERS, json={"card": "ollama"}).json()["connection"]
        res = client.post(f"/api/ai/connections/{ollama['id']}/test", headers=HEADERS,
                          json={"purpose": "embeddings"}).json()
    assert res["ok"] is True and "embeddinggemma-2" in res["message"]
    assert calls == [("http://127.0.0.1:11434/api/embed", "embeddinggemma-2")]  # not the chat model qwen3:8b
