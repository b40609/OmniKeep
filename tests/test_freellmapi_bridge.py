"""End-to-end tests for zero-copy-paste FreeLLMAPI local bridge (scripts/freellmapi_bridge.py)."""
from __future__ import annotations

import json

import httpx
import pytest

from app import ai_connections
from scripts import freellmapi_bridge as bridge

UNIFIED_SECRET = "freellmapi-secret-unified-key-9876"
SESSION_SECRET = "desktop-session-token-secret-5432"
GROQ_SECRET = "gsk_free_groq_secret_1111"
VERTEX_SECRET = "AIzaPaidVertexKeyMustNeverMirror9999"


def _make_fake_transport(desktop_mode: bool = True):
    state = {
        "keyless_enabled": False,
        "added_keys": [],
        "providers": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        auth = request.headers.get("authorization", "")

        def check_admin() -> bool:
            return auth == f"Bearer {SESSION_SECRET}"

        if request.method == "GET" and path == "/api/auth/status":
            return httpx.Response(200, json={"needsSetup": False, "authenticated": False, "desktop": desktop_mode})
        if request.method == "POST" and path == "/api/auth/desktop-session":
            if not desktop_mode:
                return httpx.Response(403, json={"error": "forbidden"})
            return httpx.Response(200, json={"token": SESSION_SECRET})
        if request.method == "POST" and path == "/api/keys/keyless-available/enable":
            if not check_admin():
                return httpx.Response(401, json={"error": "unauthorized"})
            state["keyless_enabled"] = True
            return httpx.Response(200, json={"enabled": ["kilo", "ovh"]})
        if request.method == "GET" and path == "/api/keys/providers":
            if not check_admin():
                return httpx.Response(401, json={"error": "unauthorized"})
            return httpx.Response(200, json={"providers": state["providers"]})
        if request.method == "POST" and path == "/api/keys":
            if not check_admin():
                return httpx.Response(401, json={"error": "unauthorized"})
            body = json.loads(request.content.decode("utf-8"))
            state["added_keys"].append(body)
            state["providers"].append({"platform": body.get("platform"), "configured": True})
            return httpx.Response(201, json={"id": len(state["added_keys"]), "platform": body.get("platform")})
        if request.method == "GET" and path == "/api/settings/api-key":
            if not check_admin():
                return httpx.Response(401, json={"error": "unauthorized"})
            return httpx.Response(200, json={"apiKey": UNIFIED_SECRET})
        if request.method == "GET" and path == "/v1/models":
            if auth != f"Bearer {UNIFIED_SECRET}":
                return httpx.Response(401, json={"error": "bad key"})
            return httpx.Response(200, json={"data": [{"id": "auto"}, {"id": "groq/gpt-oss-120b"}]})
        return httpx.Response(404, json={"error": f"not found: {request.method} {path}"})

    return httpx.MockTransport(handler), state


def _patch_httpx_client(monkeypatch, transport, seen_kwargs=None):
    real_client = httpx.Client

    def _client(*args, **kwargs):
        if seen_kwargs is not None:
            seen_kwargs.append(dict(kwargs))
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(bridge.httpx, "Client", _client)


def test_auto_connect_wires_keyless_mirrors_only_free_keys_and_never_leaks_secrets(monkeypatch, capsys):
    # Pre-seed one free-tier key (groq, with explicit slot model override) and one paid/subscription key (vertex)
    groq_conn = ai_connections.create({"card": "groq", "key": GROQ_SECRET}, slot="analysis")
    ai_connections.set_slots({"analysis": [{"connection_id": groq_conn.id, "model": "llama-3.3-70b-versatile"}]})
    ai_connections.create({"card": "vertex", "key": VERTEX_SECRET})

    transport, state = _make_fake_transport(desktop_mode=True)
    client_kwargs = []
    _patch_httpx_client(monkeypatch, transport, seen_kwargs=client_kwargs)

    rc = bridge.main([
        "--base-url", "http://127.0.0.1:31415",
        "--sync-existing-keys",
    ])
    out = capsys.readouterr().out

    assert rc == 0, out
    # Security invariant: zero plaintext secrets in CLI output and loopback never trusts proxy env vars
    assert UNIFIED_SECRET not in out
    assert SESSION_SECRET not in out
    assert GROQ_SECRET not in out
    assert VERTEX_SECRET not in out
    assert client_kwargs and all(kw.get("trust_env") is False for kw in client_kwargs)

    doc = json.loads(out)
    assert doc["ok"] is True
    assert doc["keyless_enabled"] == ["kilo", "ovh"]
    assert doc["models_probe_ok"] is True
    assert doc["ready_models_count"] == 2
    assert doc["connection"]["action"] == "created"
    assert doc["connection"]["key_hint"] == "…9876"
    assert doc["connection"]["slot_order"][0] == doc["connection"]["connection_id"]
    assert groq_conn.id in doc["connection"]["slot_order"]

    # Existing peer slot entry preserves its custom model override
    analysis_entries = ai_connections.slots()["analysis"]
    groq_slot_entry = next(e for e in analysis_entries if int(e["connection_id"]) == groq_conn.id)
    assert groq_slot_entry.get("model") == "llama-3.3-70b-versatile"

    # FreeLLMAPI received only the free groq key — never the paid vertex key
    assert state["keyless_enabled"] is True
    assert [k["platform"] for k in state["added_keys"]] == ["groq"]
    assert state["added_keys"][0]["key"] == GROQ_SECRET

    # Saved OmniKeep connection holds the unified key encrypted and resolves to the detected port
    saved = ai_connections.list_connections()
    flm = next(c for c in saved if c.card == "freellmapi")
    assert flm.base_url == "http://127.0.0.1:31415/v1"
    assert flm.key == UNIFIED_SECRET


def test_auto_connect_refuses_non_loopback_userinfo_and_handles_non_desktop_mode(monkeypatch):
    with pytest.raises(ValueError, match="loopback"):
        bridge.auto_connect(base_url="https://evil.example:31415")
    with pytest.raises(ValueError, match="loopback"):
        bridge.auto_connect(base_url="http://user:pass@127.0.0.1:31415")

    transport, _ = _make_fake_transport(desktop_mode=False)
    _patch_httpx_client(monkeypatch, transport)
    res = bridge.auto_connect(base_url="http://127.0.0.1:3001")
    assert res["ok"] is False
    assert "非桌面免密碼模式" in res["error"]
