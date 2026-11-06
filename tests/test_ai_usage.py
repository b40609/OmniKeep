"""Per-connection usage counts and free-allowance progress (設定 › AI 服務商)."""
import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import ai_connections, ai_usage
from app.main import app
from app.providers import build_provider
from tests.test_ai_connections import HEADERS


def _reply(prompt=120, completion=30):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
                           usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion))


def _call(provider, create):
    provider.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return asyncio.run(provider._chat(model=provider.model, messages=[]))


def test_successful_calls_add_requests_and_tokens():
    conn = ai_connections.create({"card": "inception", "key": "sk-test-1234567890"})
    provider = build_provider(conn)

    async def create(**_):
        return _reply()

    _call(provider, create)
    _call(provider, create)
    usage = ai_usage.summary(conn.id)
    assert usage["today"] == {"requests": 2, "failures": 0, "tokens": 300, "prompt_tokens": 240,
                              "completion_tokens": 60}
    assert usage["month"]["tokens"] == usage["total"]["tokens"] == 300


def test_quota_progress_follows_the_card():
    conn = ai_connections.create({"card": "inception", "key": "sk-test-1234567890"})
    ai_usage.record_success(conn.status_key, {"usage": {"prompt_tokens": 40_000_000, "completion_tokens": 10_000_000}})
    quota = ai_usage.summary(conn.id, {"tokens": 100_000_000, "period": "once"})["quota"]
    assert quota == {"unit": "tokens", "period": "once", "limit": 100_000_000, "used": 50_000_000, "percent": 50.0}
    daily = ai_usage.summary(conn.id, {"requests": 200, "period": "day"})["quota"]
    assert daily["used"] == 1 and daily["unit"] == "requests"


def test_failures_and_missing_usage_are_counted_without_tokens():
    conn = ai_connections.create({"card": "kilo"})
    ai_usage.record_failure(conn.status_key)
    ai_usage.record_success(conn.status_key, SimpleNamespace(usage=None))
    today = ai_usage.summary(conn.id)["today"]
    assert (today["requests"], today["failures"], today["tokens"]) == (1, 1, 0)


def test_the_older_flat_settings_are_not_recorded():
    ai_usage.record_success("llm", _reply())  # no connection row to show it on; must not raise


def test_the_connection_list_reports_usage_and_quota():
    conn = ai_connections.create({"card": "requesty", "key": "sk-test-1234567890"})
    ai_usage.record_success(conn.status_key, _reply())
    with TestClient(app) as client:
        listed = client.get("/api/ai/connections", headers=HEADERS).json()["connections"]
    row = next(c for c in listed if c["id"] == conn.id)
    assert row["usage"]["today"]["requests"] == 1
    assert row["usage"]["quota"]["limit"] == 200 and row["usage"]["quota"]["period"] == "day"
