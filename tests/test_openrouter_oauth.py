"""OpenRouter OAuth PKCE one-click API key provisioning (app/openrouter_oauth.py, 2026-11-23)."""
from contextlib import closing
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from app import ai_connections, ai_status, openrouter_oauth, providers
from app.config import settings
from app.database import get_db_connection
from app.main import app

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}
OR_KEY = "sk-or-v1-test-openrouter-key-9876"
OR_KEY_2 = "sk-or-v1-test-openrouter-key-4321"


@pytest.fixture(autouse=True)
def clean_state():
    openrouter_oauth.clear()
    ai_status.forget()
    providers.reset_providers()
    yield
    openrouter_oauth.clear()
    ai_status.forget()
    providers.reset_providers()


class _FakeResponse:
    def __init__(self, status_code: int, body=None, text: str = ""):
        self.status_code = status_code
        self._body = body
        self.text = text

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeAsyncClient:
    def __init__(self, outcome, seen: list):
        self._outcome = outcome
        self._seen = seen

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, json=None, headers=None):
        self._seen.append({"url": url, "json": json, "headers": headers})
        if isinstance(self._outcome, Exception):
            raise self._outcome
        return self._outcome


def test_catalog_marks_only_openrouter_with_oauth():
    with TestClient(app) as client:
        cards = client.get("/api/ai/catalog", headers=HEADERS).json()["cards"]
    by_id = {c["id"]: c for c in cards}
    assert by_id["openrouter"]["oauth"] == "openrouter"
    assert by_id["groq"]["oauth"] == ""


def test_oauth_routes_stay_behind_api_key_gate():
    with TestClient(app) as client:
        r1 = client.post("/api/ai/oauth/openrouter/start", json={"callback_url": "http://localhost:5000/"})
        r2 = client.post("/api/ai/oauth/openrouter/exchange", json={"code": "abc", "state": "xyz"})
    assert r1.status_code == 401
    assert r2.status_code == 401


def test_start_and_exchange_creates_encrypted_openrouter_connection_without_exposing_key(monkeypatch):
    seen = []
    monkeypatch.setattr(
        openrouter_oauth.httpx,
        "AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(200, {"key": OR_KEY, "user_id": "user_1"}), seen),
    )

    with TestClient(app) as client:
        started = client.post(
            "/api/ai/oauth/openrouter/start",
            headers=HEADERS,
            json={"callback_url": "http://127.0.0.1:5000/?ignored=1#frag", "slot": "analysis"},
        )
        assert started.status_code == 200, started.text
        data = started.json()
        assert data["state"] and "code_verifier" not in data

        parsed = urlsplit(data["auth_url"])
        qs = parse_qs(parsed.query)
        assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "https://openrouter.ai/auth"
        assert qs["callback_url"] == ["http://127.0.0.1:5000/"]
        assert qs["code_challenge_method"] == ["S256"]
        challenge = qs["code_challenge"][0]

        exchanged = client.post(
            "/api/ai/oauth/openrouter/exchange",
            headers=HEADERS,
            json={"code": "or_auth_code_123", "state": data["state"], "label": "我的 OpenRouter"},
        )
        assert exchanged.status_code == 200, exchanged.text
        assert OR_KEY not in exchanged.text

        conn = exchanged.json()["connection"]
        assert conn["card"] == "openrouter"
        assert conn["label"] == "我的 OpenRouter"
        assert conn["key_configured"] is True
        assert conn["key_hint"] == "…9876"
        assert conn["used_in"] == ["analysis"]

    assert len(seen) == 1
    assert seen[0]["url"] == "https://openrouter.ai/api/v1/auth/keys"
    assert seen[0]["json"]["code"] == "or_auth_code_123"
    assert seen[0]["json"]["code_challenge_method"] == "S256"
    assert openrouter_oauth.code_challenge_s256(seen[0]["json"]["code_verifier"]) == challenge

    with closing(get_db_connection()) as db:
        stored = db.execute("SELECT key_enc FROM ai_connections WHERE id = ?", (conn["id"],)).fetchone()[0]
    assert stored.startswith("fernet1:") and OR_KEY not in stored


def test_edit_mode_updates_existing_openrouter_key_and_rejects_other_cards(monkeypatch):
    seen = []
    monkeypatch.setattr(
        openrouter_oauth.httpx,
        "AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(200, {"key": OR_KEY_2}), seen),
    )

    with TestClient(app) as client:
        groq = client.post("/api/ai/connections", headers=HEADERS, json={
            "card": "groq", "key": "gsk-test-abcdefghijklmnop1111",
        }).json()["connection"]
        bad = client.post("/api/ai/oauth/openrouter/start", headers=HEADERS, json={
            "callback_url": "http://localhost:5000/", "connection_id": groq["id"],
        })
        assert bad.status_code == 400

        existing = client.post("/api/ai/connections", headers=HEADERS, json={
            "card": "openrouter", "key": OR_KEY, "label": "舊 OpenRouter",
        }).json()["connection"]
        assert existing["key_hint"] == "…9876"

        before_count = len(client.get("/api/ai/connections", headers=HEADERS).json()["connections"])
        started = client.post("/api/ai/oauth/openrouter/start", headers=HEADERS, json={
            "callback_url": "http://localhost:5000/", "connection_id": existing["id"],
        }).json()

        exchanged = client.post("/api/ai/oauth/openrouter/exchange", headers=HEADERS, json={
            "code": "code_edit_456", "state": started["state"],
        })
        assert exchanged.status_code == 200, exchanged.text
        assert OR_KEY_2 not in exchanged.text
        conn = exchanged.json()["connection"]
        assert conn["id"] == existing["id"]
        assert conn["label"] == "舊 OpenRouter"
        assert conn["key_hint"] == "…4321"
        conns_after = exchanged.json()["connections"]
        assert len(conns_after) == before_count
        assert sum(1 for c in conns_after if c["card"] == "openrouter") == 1


def test_state_is_one_time_and_expires(monkeypatch):
    monkeypatch.setattr(
        openrouter_oauth.httpx,
        "AsyncClient",
        lambda **kw: _FakeAsyncClient(_FakeResponse(200, {"key": OR_KEY}), []),
    )

    with TestClient(app) as client:
        started = client.post("/api/ai/oauth/openrouter/start", headers=HEADERS, json={
            "callback_url": "http://localhost:5000/",
        }).json()

        first = client.post("/api/ai/oauth/openrouter/exchange", headers=HEADERS, json={
            "code": "once", "state": started["state"],
        })
        assert first.status_code == 200

        replay = client.post("/api/ai/oauth/openrouter/exchange", headers=HEADERS, json={
            "code": "once", "state": started["state"],
        })
        assert replay.status_code == 400

    # Expired challenge is refused.
    t0 = 1_800_000_000.0
    res = openrouter_oauth.start("http://localhost:5000/", now=t0)
    with pytest.raises(openrouter_oauth.OpenRouterOAuthError) as exc:
        import asyncio
        asyncio.run(openrouter_oauth.exchange("code", res["state"], now=t0 + openrouter_oauth.TTL + 1))
    assert exc.value.status_code == 400


@pytest.mark.parametrize("bad_url", [
    "",
    "javascript:alert(1)",
    "ftp://localhost:5000/",
    "http://user:pass@localhost:5000/",
    "http://localhost:5000/\r\nX-Test: 1",
])
def test_invalid_callback_urls_are_rejected(bad_url):
    with TestClient(app) as client:
        res = client.post("/api/ai/oauth/openrouter/start", headers=HEADERS, json={"callback_url": bad_url})
    assert res.status_code == 400


@pytest.mark.parametrize("outcome, expected_status", [
    (_FakeResponse(400, {"error": "invalid_grant"}), 400),
    (_FakeResponse(403, {"error": "forbidden"}), 400),
    (_FakeResponse(500, {"error": "server"}), 502),
    (_FakeResponse(200, {"user_id": "missing_key"}), 502),
    (httpx.ReadTimeout("timed out"), 504),
    (httpx.ConnectError("offline"), 502),
])
def test_exchange_errors_translate_cleanly(monkeypatch, outcome, expected_status):
    monkeypatch.setattr(
        openrouter_oauth.httpx,
        "AsyncClient",
        lambda **kw: _FakeAsyncClient(outcome, []),
    )
    with TestClient(app) as client:
        started = client.post("/api/ai/oauth/openrouter/start", headers=HEADERS, json={
            "callback_url": "http://localhost:5000/",
        }).json()
        res = client.post("/api/ai/oauth/openrouter/exchange", headers=HEADERS, json={
            "code": "bad_code", "state": started["state"],
        })
    assert res.status_code == expected_status
    assert res.json()["detail"]
