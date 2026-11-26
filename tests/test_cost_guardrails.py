"""Cost guardrails of 2026-11-27: a spend cap is a quota told to the owner once, the local
gateway has a daily budget and an end date per source, and a capped account is left out.

Sources: OmniKeep cross review 2026-11-26 (KEEP-X-02, A-03, A-04, KEEP-X-05).
"""
import asyncio
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from app import ai_status, llm_gateway, owner_alert
from app.error_translate import translate
from tests.test_llm_gateway import MESSAGES, FakeError, _caller

# What Vertex AI answered on 2026-11-26 (service log), the project number shortened.
SPEND_CAP = ("403 PERMISSION_DENIED. {'error': {'code': 403, 'message': 'Spend cap breached for project: "
             "projects/1 for service: aiplatform.googleapis.com. Correlation ID: x', 'status': 'PERMISSION_DENIED'}}")


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(owner_alert, "_fire", lambda title, body, tag: out.append((title, body)))
    return out


@pytest.fixture
def vertex():
    from app import ai_connections
    ai_status.forget()
    fake = "AQ.fake-" + "x" * 24  # not a credential; built so the secret scanner has nothing to match
    a = ai_connections.create({"card": "vertex", "key": fake + "a", "label": "帳號 2"})
    b = ai_connections.create({"card": "vertex", "key": fake + "b", "label": "帳號 3"})
    yield a, b
    ai_status.forget()


def _config(a, b, sources=None):
    return llm_gateway.check_config({"connections": [a.id, b.id], "sources": sources or {}})


def _run(config, outcomes=None, calls=None, source="claude-mem"):
    return asyncio.run(llm_gateway.complete(MESSAGES, source, config=config,
                                            caller=_caller(outcomes or {}, [] if calls is None else calls)))


# ── A-04: the spend cap is a quota a person must fix ──────────────────────────

def test_a_spend_cap_is_a_quota_that_needs_a_person():
    info = translate(403, SPEND_CAP)
    assert info["kind"] == "quota"
    assert info["action_required"] is True
    assert "支出上限" in info["hint"]
    # a plain 403 is still a missing permission
    assert translate(403, "403 PERMISSION_DENIED. Permission denied on resource")["kind"] == "auth"


def test_the_owner_is_told_once_until_the_connection_works_again(sent):
    ai_status.record_failure("c99", 403, SPEND_CAP, "Google Vertex AI（帳號 2）")
    ai_status.record_failure("c99", 403, SPEND_CAP, "Google Vertex AI（帳號 2）")
    assert len(sent) == 1 and "帳號 2" in sent[0][0]
    ai_status.forget()  # as after a restart: the database still knows it was sent
    ai_status.record_failure("c99", 403, SPEND_CAP)
    assert len(sent) == 1
    ai_status.record_success("c99")  # the cap was raised
    ai_status.record_failure("c99", 403, SPEND_CAP)
    assert len(sent) == 2


def test_a_rate_limit_is_not_told_to_the_owner(sent):
    ai_status.record_failure("c98", 429, "429 RESOURCE_EXHAUSTED")
    assert sent == []


# ── KEEP-X-05: an account past its spend cap is left out of the next calls ────

def test_a_capped_account_is_not_knocked_again_within_six_hours(vertex):
    a, b = vertex
    first = []
    _run(_config(a, b), {(a.status_key, "gemini-4-hydrogen"): FakeError(403, SPEND_CAP)}, first)
    assert first[0][0] == a.status_key
    second = []
    failing_b = {(b.status_key, m): FakeError(503, "UNAVAILABLE") for m in ("gemini-4-hydrogen", "gemini-3.8-flash")}
    with pytest.raises(llm_gateway.GatewayError):
        _run(_config(a, b), failing_b, second)
    assert a.status_key not in {c[0] for c in second}  # before: tried again at the back of the line
    # six hours later it gets one more try
    ai_status._state[a.status_key]["cooldown_until"] = 0.0
    third = []
    _run(_config(a, b), failing_b, third)
    assert third[-1][0] == a.status_key


# ── A-03 / KEEP-X-02: a budget and an end date per source ────────────────────

def test_a_source_over_its_daily_requests_is_refused_until_midnight(vertex, sent):
    a, b = vertex
    config = _config(a, b, {"claude-mem": {"daily_requests": 1}})
    _run(config)
    calls = []
    with pytest.raises(llm_gateway.GatewayError) as caught:
        _run(config, calls=calls)
    assert caught.value.status == 429 and caught.value.retry_after and caught.value.retry_after <= 86400
    assert calls == []  # nothing was sent to Vertex
    with pytest.raises(llm_gateway.GatewayError):
        _run(config)
    assert len(sent) == 1 and "claude-mem" in sent[0][0]  # told once a day


def test_a_source_over_its_daily_tokens_is_refused(vertex):
    a, b = vertex
    config = _config(a, b, {"claude-mem": {"daily_requests": None, "daily_tokens": 100}})
    _run(config)  # 420 tokens
    with pytest.raises(llm_gateway.GatewayError) as caught:
        _run(config)
    assert caught.value.status == 429


def test_other_sources_keep_their_own_budget(vertex):
    a, b = vertex
    config = _config(a, b, {"claude-mem": {"daily_requests": 1}, "*": {"daily_requests": 5}})
    _run(config)
    with pytest.raises(llm_gateway.GatewayError):
        _run(config)
    assert _run(config, source="other-tool").connection == a.status_key


def test_a_source_without_an_entry_gets_the_default_cap(vertex):
    a, b = vertex
    assert llm_gateway.limits_for("someone", _config(a, b))["daily_requests"] == \
        llm_gateway.DEFAULT_SOURCE_LIMITS["daily_requests"]


def test_the_end_date_refuses_the_source_from_midnight_that_day(vertex, sent):
    a, b = vertex
    config = _config(a, b, {"claude-mem": {"until": "2026-12-03"}})
    llm_gateway.check_source("claude-mem", config, now=datetime(2026, 12, 2, 23, 59))
    with pytest.raises(llm_gateway.GatewayError) as caught:
        llm_gateway.check_source("claude-mem", config, now=datetime(2026, 12, 3, 0, 0))
    assert caught.value.status == 403 and "until" in str(caught.value)
    assert len(sent) == 1 and "claude-mem" in sent[0][0]


def test_an_end_date_in_the_past_sends_nothing(vertex):
    a, b = vertex
    calls = []
    with pytest.raises(llm_gateway.GatewayError) as caught:
        _run(_config(a, b, {"claude-mem": {"until": "2020-01-01"}}), calls=calls)
    assert caught.value.status == 403 and calls == []


@pytest.mark.parametrize("entry", [{"until": "12/03"}, {"daily_requests": "many"}, {"daily_tokens": -1}, "off"])
def test_an_entry_that_cannot_be_read_refuses_the_source(vertex, entry):
    a, b = vertex
    calls = []
    with pytest.raises(llm_gateway.GatewayError) as caught:
        _run(_config(a, b, {"claude-mem": entry}), calls=calls)
    assert caught.value.status == 403 and calls == []


def test_the_endpoint_says_when_to_come_back(monkeypatch, vertex):
    a, b = vertex
    monkeypatch.setattr(llm_gateway, "_call", _caller({}, []))
    monkeypatch.setattr(llm_gateway, "load_config",
                        lambda path=None: _config(a, b, {"claude-mem": {"daily_requests": 0}}))
    token = llm_gateway.ensure_token("claude-mem")
    client = TestClient(llm_gateway.create_app())
    response = client.post("/v1/chat/completions", headers={"Authorization": f"Bearer {token}"},
                           json={"messages": MESSAGES, "stream": True})
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 60
    assert response.json()["error"]["type"] == "rate_limit_error"
