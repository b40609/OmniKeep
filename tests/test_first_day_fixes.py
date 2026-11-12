"""Small things a first-day user ran into (clean install rehearsal, 2026-11-12)."""
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.brain as brain
from app import ai_connections, app_settings
from app.config import Settings, settings
from app.logging_setup import redact_url_secrets
from app.main import app

REPO = Path(__file__).resolve().parents[1]
TOKEN = "110201543:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"  # the example in Telegram's documentation


# ── Asking with nothing saved ────────────────────────────────────

async def test_a_question_with_nothing_to_cite_is_not_sent_to_any_model(monkeypatch):
    async def nothing(query, limit=10, vector_weight=0.5):
        return []

    def no_model(*args, **kwargs):
        raise AssertionError("a model was asked although nothing was retrieved")

    monkeypatch.setattr(brain, "search_hybrid", nothing)
    monkeypatch.setattr(brain.httpx, "AsyncClient", no_model)
    monkeypatch.setattr("app.providers.get_provider", no_model)
    result = await brain.ask_brain("Rust 的 async 怎麼運作？")
    assert result["citations"] == [] and result["provider"] == "retrieval_only"
    assert "還沒有相關的收藏" in result["answer"]


# ── .env.example must not ask a new install to "import" anything ─

def _example_values():
    values = {}
    for line in (REPO / ".env.example").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line)
        if match and match.group(2).strip():
            values[match.group(1)] = match.group(2).strip()
    return values


def test_env_example_presets_nothing_the_app_manages():
    # A value that differs from the built-in default shows up in 設定 › 進階 as
    # "有 1 項設定還寫在 .env" (LLM_MIN_REQUEST_INTERVAL=2.0 against a default of 2.5 did).
    preset = _example_values()
    stray = {}
    for spec in app_settings.SPECS:
        if spec.key in preset and str(preset[spec.key]) != str(app_settings.default_value(spec)):
            stray[spec.key] = preset[spec.key]
    assert stray == {}


def test_a_new_env_file_has_nothing_to_import(monkeypatch):
    for key in list(os.environ):
        if key in app_settings.SPEC_BY_KEY or key in ("OPENAI_MODEL", "GEMINI_API_KEYS"):
            monkeypatch.delenv(key)
    fresh = Settings(_env_file=REPO / ".env.example")
    differing = [spec.key for spec in app_settings.SPECS
                 if getattr(fresh, spec.field) not in ("", None)
                 and getattr(fresh, spec.field) != app_settings.default_value(spec)]
    assert differing == []


# ── A "本機 Ollama" connection only when Ollama is there ──────────

def _start_once():
    with TestClient(app):
        pass
    return {c.origin: c for c in ai_connections.list_connections()}


def test_a_fresh_install_without_ollama_lists_no_connection(monkeypatch):
    monkeypatch.setattr(ai_connections, "ollama_answers", lambda url: False)
    assert _start_once() == {}
    assert ai_connections.slots() == {slot: [] for slot in ai_connections.SLOTS}
    assert ai_connections.needs_setup() is True  # the banner and the list now agree
    assert ai_connections.migrate_legacy() is False  # still migrated once


def test_a_fresh_install_with_ollama_running_lists_it(monkeypatch):
    monkeypatch.setattr(ai_connections, "ollama_answers", lambda url: True)
    conns = _start_once()
    assert set(conns) == {"legacy_ollama"}
    slots = ai_connections.slots()
    assert slots["analysis"] == [] and ai_connections.needs_setup() is True  # analysis still needs a choice
    assert [e["connection_id"] for e in slots["brain"]] == [conns["legacy_ollama"].id]


def test_an_ollama_address_the_owner_wrote_is_kept_without_asking(monkeypatch):
    asked = []
    monkeypatch.setattr(ai_connections, "ollama_answers", lambda url: asked.append(url) or False)
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://192.168.1.20:11434")
    monkeypatch.setattr(settings, "BRAIN_BASE_URL", "http://192.168.1.20:11434")
    conns = _start_once()
    assert conns["legacy_ollama"].base_url == "http://192.168.1.20:11434" and asked == []


# ── The Telegram token stays out of the log ──────────────────────

def test_secrets_in_request_urls_are_redacted():
    line = f'HTTP Request: POST https://api.telegram.org/bot{TOKEN}/getUpdates "HTTP/1.1 200 OK"'
    assert redact_url_secrets(line) == 'HTTP Request: POST https://api.telegram.org/bot***/getUpdates "HTTP/1.1 200 OK"'
    assert redact_url_secrets("GET https://x.example/v1/models?key=AIzaSecret123&alt=json") == \
        "GET https://x.example/v1/models?key=***&alt=json"
    assert redact_url_secrets("GET https://example.com/article?id=5") == "GET https://example.com/article?id=5"


PROBE = """
import asyncio, io, logging, sys
{before}
import app.main  # FastMCP puts an INFO handler on the root logger
import httpx
{after}
buffer = io.StringIO()
logging.getLogger().addHandler(logging.StreamHandler(buffer))
async def main():
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={{"ok": True}}))
    async with httpx.AsyncClient(transport=transport) as client:
        await client.post("https://api.telegram.org/bot{token}/getUpdates", json={{}})
asyncio.run(main())
print("LOGGED", repr(buffer.getvalue()))
"""


@pytest.mark.parametrize("before, after, logged", [
    # Started without run.py (uvicorn app.main:app): this used to print the token.
    ("", "", False),
    # Someone turns request logging on to debug: the line is there, the token is not.
    ("", "logging.getLogger('httpx').setLevel(logging.INFO)", True),
    # run.py's own setting still holds.
    ("logging.getLogger('httpx').setLevel(logging.CRITICAL)", "", False),
])
def test_a_telegram_request_never_logs_its_token(before, after, logged):
    env = {**os.environ, "PYTHONPATH": str(REPO), "OMNIKEEP_TESTING": "1"}
    res = subprocess.run([sys.executable, "-c", PROBE.format(before=before, after=after, token=TOKEN)],
                         cwd=REPO, env=env, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr
    assert TOKEN not in res.stdout and TOKEN not in res.stderr
    assert TOKEN.split(":")[1] not in res.stdout + res.stderr
    line = [text for text in res.stdout.splitlines() if text.startswith("LOGGED")][0]
    assert ("bot***/getUpdates" in line) is logged


# ── Scripts ──────────────────────────────────────────────────────

@pytest.mark.parametrize("script", ["scripts/install.ps1", "scripts/watchdog.ps1"])
def test_windows_scripts_read_the_port_instead_of_assuming_5000(script):
    text = (REPO / script).read_text(encoding="utf-8-sig")
    assert "127.0.0.1:5000" not in text and "-LocalPort 5000" not in text
    assert "Get-ServicePort" in text and "return 5000" in text  # PORT from .env, 5000 when not set


def test_run_bat_only_hands_over_to_the_installer():
    text = (REPO / "run.bat").read_text(encoding="utf-8")
    assert "scripts\\install.ps1" in text
    assert ".env.example" not in text and "venv" not in text and "run.py" not in text
