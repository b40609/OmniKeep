"""End-to-end tests for zero-copy-paste FreeLLMAPI local bridge (scripts/freellmapi_bridge.py)."""
from __future__ import annotations

import json

import httpx
import pytest

from app import ai_connections, provider_catalog
from scripts import freellmapi_bridge as bridge
from scripts import setup_cli

UNIFIED_SECRET = "freellmapi-secret-unified-key-9876"
SESSION_SECRET = "desktop-session-token-secret-5432"
GROQ_SECRET = "gsk_free_groq_secret_1111"
GROQ_SECRET_2 = "gsk_free_groq_secret_2222"
GEMINI_SECRET_1 = "AIzaFreeGeminiKeyOne1111"
GEMINI_SECRET_2 = "AIzaFreeGeminiKeyTwo2222"
CF_TOKEN = "cf_workers_ai_secret_token_7777"
CF_ACCOUNT = "acc1234567890abcdef"
VERTEX_SECRET = "AIzaPaidVertexKeyMustNeverMirror9999"
OPENAI_SECRET = "sk-paid-openai-secret-8888"
DEEPSEEK_SECRET = "sk-paid-deepseek-secret-6666"


def _make_fake_transport(
    desktop_mode: bool = True,
    *,
    providers_status: int = 200,
    initial_providers: list | None = None,
    keyless_status: int = 200,
    keys_post_status: int = 201,
    bad_json_path: str | None = None,
    unified_key: str = UNIFIED_SECRET,
    redirect_path: str | None = None,
    only_port: int | None = None,
):
    state = {
        "requests": [],
        "keyless_enabled": False,
        "added_keys": [],
        "providers": list(initial_providers or []),
        "logged_out": False,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if only_port is not None and request.url.port != only_port:
            raise httpx.ConnectError(f"port {request.url.port} closed")

        path = request.url.path
        auth = request.headers.get("authorization", "")
        state["requests"].append((request.method, path, request.url.port))

        def check_admin() -> bool:
            return auth == f"Bearer {SESSION_SECRET}"

        if redirect_path and path == redirect_path:
            return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

        if bad_json_path and path == bad_json_path:
            return httpx.Response(200, text="<html>not json</html>", headers={"content-type": "text/html"})

        if request.method == "GET" and path == "/api/auth/status":
            return httpx.Response(200, json={"needsSetup": False, "authenticated": False, "desktop": desktop_mode})
        if request.method == "POST" and path == "/api/auth/desktop-session":
            if not desktop_mode:
                return httpx.Response(403, json={"error": "forbidden"})
            return httpx.Response(200, json={"token": SESSION_SECRET})
        if request.method == "POST" and path == "/api/auth/logout":
            if check_admin():
                state["logged_out"] = True
                return httpx.Response(200, json={"ok": True})
            return httpx.Response(401, json={"error": "unauthorized"})
        if request.method == "POST" and path == "/api/keys/keyless-available/enable":
            if not check_admin():
                return httpx.Response(401, json={"error": "unauthorized"})
            if keyless_status != 200:
                return httpx.Response(keyless_status, json={"error": "upstream unavailable"})
            state["keyless_enabled"] = True
            return httpx.Response(200, json={"enabled": ["kilo", "ovh"]})
        if request.method == "GET" and path == "/api/keys/providers":
            if not check_admin():
                return httpx.Response(401, json={"error": "unauthorized"})
            if providers_status != 200:
                return httpx.Response(providers_status, json={"error": "db error"})
            return httpx.Response(200, json={"providers": state["providers"]})
        if request.method == "POST" and path == "/api/keys":
            if not check_admin():
                return httpx.Response(401, json={"error": "unauthorized"})
            if keys_post_status not in (200, 201):
                return httpx.Response(keys_post_status, json={"error": "rejected"})
            body = json.loads(request.content.decode("utf-8"))
            state["added_keys"].append(body)
            state["providers"].append({"platform": body.get("platform"), "configured": True})
            return httpx.Response(201, json={"id": len(state["added_keys"]), "platform": body.get("platform")})
        if request.method == "GET" and path == "/api/settings/api-key":
            if not check_admin():
                return httpx.Response(401, json={"error": "unauthorized"})
            return httpx.Response(200, json={"apiKey": unified_key})
        if request.method == "GET" and path == "/v1/models":
            if auth != f"Bearer {unified_key}":
                return httpx.Response(401, json={"error": "bad key"})
            return httpx.Response(200, json={"data": [{"id": "auto"}, {"id": "groq/gpt-oss-120b"}]})
        return httpx.Response(404, json={"error": f"not found: {request.method} {path}"})

    return httpx.MockTransport(handler), state


_REAL_HTTPX_CLIENT = httpx.Client


def _patch_httpx_client(monkeypatch, transport, seen_kwargs=None):
    def _client(*args, **kwargs):
        if seen_kwargs is not None:
            seen_kwargs.append(dict(kwargs))
        kwargs["transport"] = transport
        return _REAL_HTTPX_CLIENT(*args, **kwargs)

    monkeypatch.setattr(bridge.httpx, "Client", _client)


def test_auto_connect_wires_keyless_mirrors_only_free_keys_logs_out_and_never_leaks(monkeypatch, capsys):
    # Pre-seed free cards (groq, gemini comma-multi-key, cloudflare with account_id) + paid cards (vertex, openai, deepseek)
    groq_conn = ai_connections.create({"card": "groq", "key": GROQ_SECRET}, slot="analysis")
    ai_connections.set_slots({"analysis": [{"connection_id": groq_conn.id, "model": "llama-3.3-70b-versatile"}]})
    ai_connections.create({"card": "gemini", "key": f"{GEMINI_SECRET_1}, {GEMINI_SECRET_2}"})
    ai_connections.create({
        "card": "cloudflare",
        "base_url": f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/v1",
        "key": CF_TOKEN,
    })
    ai_connections.create({"card": "vertex", "key": VERTEX_SECRET})
    ai_connections.create({"card": "openai", "key": OPENAI_SECRET})
    ai_connections.create({"card": "deepseek", "key": DEEPSEEK_SECRET})

    transport, state = _make_fake_transport(desktop_mode=True)
    client_kwargs = []
    _patch_httpx_client(monkeypatch, transport, seen_kwargs=client_kwargs)

    rc = bridge.main([
        "--base-url", "http://127.0.0.1:31415",
        "--sync-existing-keys",
    ])
    captured = capsys.readouterr()
    combined = captured.out + captured.err

    assert rc == 0, captured.out
    # Security invariant: zero plaintext secrets in stdout or stderr, and loopback never trusts proxy env vars
    for secret in (UNIFIED_SECRET, SESSION_SECRET, GROQ_SECRET, GEMINI_SECRET_1, GEMINI_SECRET_2, CF_TOKEN, VERTEX_SECRET, OPENAI_SECRET, DEEPSEEK_SECRET):
        assert secret not in combined
    assert client_kwargs and all(kw.get("trust_env") is False and kw.get("follow_redirects") is False for kw in client_kwargs)

    doc = json.loads(captured.out)
    assert doc["ok"] is True
    assert doc["keyless_enabled"] == ["kilo", "ovh"]
    assert doc["keyless_error"] is None
    assert doc["models_probe_ok"] is True
    assert doc["ready_models_count"] == 2
    assert doc["connection"]["action"] == "created"
    assert doc["connection"]["key_hint"] == "…9876"
    assert doc["connection"]["slot_order"][0] == doc["connection"]["connection_id"]
    assert groq_conn.id in doc["connection"]["slot_order"]
    assert state["logged_out"] is True

    # Existing peer slot entry preserves its custom model override
    analysis_entries = ai_connections.slots()["analysis"]
    groq_slot_entry = next(e for e in analysis_entries if int(e["connection_id"]) == groq_conn.id)
    assert groq_slot_entry.get("model") == "llama-3.3-70b-versatile"

    # FreeLLMAPI received groq, 2x google keys, and properly formatted cloudflare account_id:token — never paid cards
    by_platform = {}
    for item in state["added_keys"]:
        by_platform.setdefault(item["platform"], []).append(item["key"])
    assert by_platform == {
        "groq": [GROQ_SECRET],
        "google": [GEMINI_SECRET_1, GEMINI_SECRET_2],
        "cloudflare": [f"{CF_ACCOUNT}:{CF_TOKEN}"],
    }

    # Saved OmniKeep connection holds the unified key encrypted and resolves to the detected port
    saved = ai_connections.list_connections()
    flm = next(c for c in saved if c.card == "freellmapi")
    assert flm.base_url == "http://127.0.0.1:31415/v1"
    assert flm.key == UNIFIED_SECRET


def test_dry_run_is_strictly_zero_write_on_both_freellmapi_and_omnikeep(monkeypatch, capsys):
    ai_connections.create({"card": "groq", "key": GROQ_SECRET})
    before_conns = [(c.id, c.card, c.base_url, c.model) for c in ai_connections.list_connections()]
    before_slots = ai_connections.slots()

    transport, state = _make_fake_transport(desktop_mode=True)
    _patch_httpx_client(monkeypatch, transport)

    rc = bridge.main([
        "--base-url", "http://127.0.0.1:31415",
        "--sync-existing-keys",
        "--dry-run",
    ])
    out = capsys.readouterr().out
    assert rc == 0, out
    doc = json.loads(out)
    assert doc["ok"] is True
    assert doc["dry_run"] is True
    assert doc["would_enable_keyless"] is True
    assert doc["mirrored_free_keys"]["synced"] == ["groq->groq(將匯入 1 把)"]
    assert doc["connection"]["action"] == "create"
    assert doc["connection"]["model"] == "auto"

    # Strict zero-write invariant: ONLY GET /api/auth/status was called (no desktop-session, no POSTs)
    assert state["requests"] == [("GET", "/api/auth/status", 31415)]
    assert state["keyless_enabled"] is False
    assert state["added_keys"] == []
    assert [(c.id, c.card, c.base_url, c.model) for c in ai_connections.list_connections()] == before_conns
    assert ai_connections.slots() == before_slots


def test_rerun_preserves_custom_model_slot_override_slot_order_and_remote_freellmapi_connection(monkeypatch):
    # Pre-seed a remote manually configured freellmapi connection AND a local one with custom model & slot override
    remote_flm = ai_connections.create({
        "card": "freellmapi",
        "label": "Remote FreeLLMAPI",
        "base_url": "http://192.168.1.50:3001/v1",
        "key": "freellmapi-remote-key-keep-me-1234",
        "model": "auto:fast",
    })
    groq_conn = ai_connections.create({"card": "groq", "key": GROQ_SECRET})
    local_flm = ai_connections.create({
        "card": "freellmapi",
        "label": "My Local Gateway",
        "base_url": "http://127.0.0.1:31415/v1",
        "key": "freellmapi-old-local-key-0000",
        "model": "auto:smart",
    })
    ai_connections.set_slots({
        "analysis": [
            {"connection_id": groq_conn.id, "model": "llama-3.3-70b-versatile"},
            {"connection_id": local_flm.id, "model": "auto:fast"},
        ]
    })

    transport, _ = _make_fake_transport(desktop_mode=True)
    _patch_httpx_client(monkeypatch, transport)

    # Default re-run (no --model, no --prepend/--append)
    res = bridge.auto_connect(base_url="http://127.0.0.1:31415")
    assert res["ok"] is True
    assert res["connection"]["action"] == "updated"
    assert res["connection"]["connection_id"] == local_flm.id
    assert res["connection"]["model"] == "auto:smart"
    assert res["connection"]["slot_order"] == [groq_conn.id, local_flm.id]

    # Slot override on local_flm and peer groq_conn are BOTH preserved
    entries = ai_connections.slots()["analysis"]
    assert entries == [
        {"connection_id": groq_conn.id, "model": "llama-3.3-70b-versatile"},
        {"connection_id": local_flm.id, "model": "auto:fast"},
    ]

    # Remote freellmapi connection is completely untouched
    remote_after = ai_connections.get_connection(remote_flm.id)
    assert remote_after is not None
    assert remote_after.base_url == "http://192.168.1.50:3001/v1"
    assert remote_after.key == "freellmapi-remote-key-keep-me-1234"
    assert remote_after.model == "auto:fast"

    # Explicit --prepend moves it to position 0 while still preserving its slot model override
    res_pre = bridge.auto_connect(base_url="http://127.0.0.1:31415", slot_position="prepend", model="auto:balanced")
    assert res_pre["ok"] is True
    assert res_pre["connection"]["model"] == "auto:balanced"
    assert ai_connections.slots()["analysis"] == [
        {"connection_id": local_flm.id, "model": "auto:fast"},
        {"connection_id": groq_conn.id, "model": "llama-3.3-70b-versatile"},
    ]


def test_remote_only_freellmapi_does_not_get_overwritten_when_connecting_local(monkeypatch):
    remote_flm = ai_connections.create({
        "card": "freellmapi",
        "label": "Remote FreeLLMAPI",
        "base_url": "http://192.168.1.50:3001/v1",
        "key": "freellmapi-remote-key-keep-me-1234",
        "model": "auto:fast",
    })
    transport, _ = _make_fake_transport(desktop_mode=True)
    _patch_httpx_client(monkeypatch, transport)

    res = bridge.auto_connect(base_url="http://127.0.0.1:31415")
    assert res["ok"] is True
    assert res["connection"]["action"] == "created"
    assert res["connection"]["connection_id"] != remote_flm.id
    remote_after = ai_connections.get_connection(remote_flm.id)
    assert remote_after is not None
    assert remote_after.base_url == "http://192.168.1.50:3001/v1"


def test_cloudflare_bad_url_disabled_and_custom_relay_are_handled_safely(monkeypatch):
    # 1. Cloudflare with non-standard path (missing /accounts/<id>/ai) -> failed, not pushed
    ai_connections.create({
        "card": "cloudflare",
        "base_url": "https://api.cloudflare.com/client/v4/other/v1",
        "key": CF_TOKEN,
    })
    # 2. Disabled groq -> skipped
    ai_connections.create({"card": "groq", "key": GROQ_SECRET, "enabled": False})
    # 3. OpenRouter pointed at custom third-party relay -> skipped
    ai_connections.create({
        "card": "openrouter",
        "base_url": "https://relay.example.com/v1",
        "key": "sk-or-relay-secret-3333",
    })
    # 4. Two enabled groq connections -> BOTH mirrored (dry-run & live consistent)
    ai_connections.create({"card": "groq", "label": "Groq A", "key": GROQ_SECRET})
    ai_connections.create({"card": "groq", "label": "Groq B", "key": GROQ_SECRET_2})

    transport, state = _make_fake_transport(desktop_mode=True)
    _patch_httpx_client(monkeypatch, transport)

    dry = bridge.auto_connect(base_url="http://127.0.0.1:31415", sync_existing_keys=True, dry_run=True)
    assert dry["ok"] is True
    assert len(dry["mirrored_free_keys"]["synced"]) == 2
    assert any("missing_cloudflare_account_id" in f["status"] for f in dry["mirrored_free_keys"]["failed"])
    assert any("已停用" in s for s in dry["mirrored_free_keys"]["skipped"])
    assert any("自訂 base_url" in s for s in dry["mirrored_free_keys"]["skipped"])

    live = bridge.auto_connect(base_url="http://127.0.0.1:31415", sync_existing_keys=True, dry_run=False)
    assert live["ok"] is True
    assert [k["key"] for k in state["added_keys"]] == [GROQ_SECRET, GROQ_SECRET_2]
    assert len(live["mirrored_free_keys"]["synced"]) == 2
    assert any("missing_cloudflare_account_id" in f["status"] for f in live["mirrored_free_keys"]["failed"])


def test_providers_non_200_aborts_mirroring_and_already_configured_skips(monkeypatch):
    ai_connections.create({"card": "groq", "key": GROQ_SECRET})

    # Non-200 /api/keys/providers must abort mirroring instead of pushing duplicates
    transport_err, state_err = _make_fake_transport(desktop_mode=True, providers_status=500)
    _patch_httpx_client(monkeypatch, transport_err)
    res_err = bridge.auto_connect(base_url="http://127.0.0.1:31415", sync_existing_keys=True)
    assert res_err["ok"] is True
    assert state_err["added_keys"] == []
    assert res_err["mirrored_free_keys"]["failed"] == [{"card": "*", "platform": "*", "status": "providers_http_500"}]

    # Already configured platform is skipped cleanly
    transport_ok, state_ok = _make_fake_transport(
        desktop_mode=True,
        initial_providers=[{"platform": "groq", "configured": True}],
    )
    _patch_httpx_client(monkeypatch, transport_ok)
    res_ok = bridge.auto_connect(base_url="http://127.0.0.1:31415", sync_existing_keys=True)
    assert res_ok["ok"] is True
    assert state_ok["added_keys"] == []
    assert res_ok["mirrored_free_keys"]["skipped"] == ["groq->groq(已設定)"]


def test_invalid_slot_and_video_slot_fail_before_any_network_or_db_write(monkeypatch):
    ai_connections.create({"card": "groq", "key": GROQ_SECRET})
    transport, state = _make_fake_transport(desktop_mode=True)
    _patch_httpx_client(monkeypatch, transport)

    bad = bridge.auto_connect(base_url="http://127.0.0.1:31415", slot="analysys", sync_existing_keys=True)
    assert bad["ok"] is False
    assert "無效的槽位" in bad["error"]
    assert state["requests"] == []
    assert state["added_keys"] == []

    vid = bridge.auto_connect(base_url="http://127.0.0.1:31415", slot="video", sync_existing_keys=True)
    assert vid["ok"] is False
    assert "video" in vid["error"]
    assert state["requests"] == []


def test_append_empty_slot_no_keyless_short_key_mask_and_keyless_error(monkeypatch):
    groq_conn = ai_connections.create({"card": "groq", "key": GROQ_SECRET}, slot="analysis")
    transport, state = _make_fake_transport(desktop_mode=True, unified_key="ab12", keyless_status=503)
    _patch_httpx_client(monkeypatch, transport)

    # Short unified key must NEVER be exposed in key_hint; keyless HTTP error is reported distinctly
    res = bridge.auto_connect(
        base_url="http://127.0.0.1:31415/v1",
        slot="analysis",
        slot_position="append",
        enable_keyless=True,
    )
    assert res["ok"] is True
    assert res["keyless_enabled"] == []
    assert res["keyless_error"] == "HTTP 503"
    assert res["connection"]["key_hint"] == "已設定"
    assert "ab12" not in json.dumps(res, ensure_ascii=False)
    assert res["connection"]["slot_order"] == [groq_conn.id, res["connection"]["connection_id"]]

    # Empty slot + --no-keyless leaves slots untouched
    before_slots = ai_connections.slots()
    res_noslot = bridge.auto_connect(
        base_url="http://127.0.0.1:31415",
        slot="",
        enable_keyless=False,
    )
    assert res_noslot["ok"] is True
    assert res_noslot["connection"]["slot_order"] == []
    assert ai_connections.slots() == before_slots


def test_loopback_validation_ipv6_auto_port_fallback_redirects_and_bad_json(monkeypatch, capsys):
    for bad_url in (
        "https://evil.example:31415",
        "http://user:pass@127.0.0.1:31415",
        "http://127.0.0.1:31415#@evil.com",
        "http://127.0.0.1:31415?next=https://evil.com",
        "http://127.0.0.1:31415/custom/path",
        "http://evil.com\\@127.0.0.1:31415",
        "ftp://127.0.0.1:31415",
        "http://0.0.0.0:31415",
    ):
        with pytest.raises(ValueError, match="loopback"):
            bridge.auto_connect(base_url=bad_url)

    # IPv6 loopback works and normalizes cleanly
    transport_v6, _ = _make_fake_transport(desktop_mode=True)
    _patch_httpx_client(monkeypatch, transport_v6)
    res_v6 = bridge.auto_connect(base_url="http://[::1]:31415/v1", dry_run=True)
    assert res_v6["ok"] is True
    assert res_v6["origin"] == "http://[::1]:31415"
    assert res_v6["v1_url"] == "http://[::1]:31415/v1"

    # Auto port detection falls back from 31415 to 3001
    transport_3001, _ = _make_fake_transport(desktop_mode=True, only_port=3001)
    _patch_httpx_client(monkeypatch, transport_3001)
    res_3001 = bridge.auto_connect(dry_run=True)
    assert res_3001["ok"] is True
    assert res_3001["origin"] == "http://127.0.0.1:3001"

    # 302 redirect is NOT followed (probe treats it as unreachable)
    transport_302, _ = _make_fake_transport(desktop_mode=True, redirect_path="/api/auth/status")
    _patch_httpx_client(monkeypatch, transport_302)
    res_302 = bridge.auto_connect(base_url="http://127.0.0.1:31415")
    assert res_302["ok"] is False

    # Bad JSON response yields readable Chinese message with zero secret leakage
    transport_bad, _ = _make_fake_transport(desktop_mode=True, bad_json_path="/api/settings/api-key")
    _patch_httpx_client(monkeypatch, transport_bad)
    rc_bad = bridge.main(["--base-url", "http://127.0.0.1:31415"])
    out_bad = capsys.readouterr()
    assert rc_bad == 1
    assert "非 JSON 內容" in out_bad.out
    assert SESSION_SECRET not in (out_bad.out + out_bad.err)

    # Non-desktop mode returns clear guidance
    transport_nd, _ = _make_fake_transport(desktop_mode=False)
    _patch_httpx_client(monkeypatch, transport_nd)
    res_nd = bridge.auto_connect(base_url="http://127.0.0.1:3001")
    assert res_nd["ok"] is False
    assert "非桌面免密碼模式" in res_nd["error"]


def test_setup_cli_connect_freellmapi_forwards_flags_and_exit_code(monkeypatch, capsys):
    transport, _ = _make_fake_transport(desktop_mode=True)
    _patch_httpx_client(monkeypatch, transport)

    rc_ok = setup_cli.main([
        "connect-freellmapi",
        "--base-url", "http://127.0.0.1:31415",
        "--dry-run",
        "--append",
    ])
    out_ok = json.loads(capsys.readouterr().out)
    assert rc_ok == 0
    assert out_ok["ok"] is True
    assert out_ok["dry_run"] is True
    assert out_ok["connection"]["slot_position"] == "append"

    rc_fail = setup_cli.main([
        "connect-freellmapi",
        "--base-url", "http://127.0.0.1:31415",
        "--slot", "bad_slot",
    ])
    out_fail = json.loads(capsys.readouterr().out)
    assert rc_fail == 1
    assert out_fail["ok"] is False


def test_provider_catalog_guess_card_port_boundaries():
    assert provider_catalog.guess_card("http://127.0.0.1:31415/v1") == "freellmapi"
    assert provider_catalog.guess_card("http://localhost:3001/v1") == "freellmapi"
    assert provider_catalog.guess_card("http://[::1]:31415/v1") == "freellmapi"
    assert provider_catalog.guess_card("http://127.0.0.1:30011/v1") == "custom"
    assert provider_catalog.guess_card("http://127.0.0.1:314150/v1") == "custom"
