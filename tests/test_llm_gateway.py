"""The local OpenAI-compatible endpoint for claude-mem (app/llm_gateway.py)."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import ai_connections, ai_status, ai_usage, llm_gateway
from scripts import llm_gateway_setup


class FakeError(Exception):
    def __init__(self, code, message):
        super().__init__(f"{code} {message}")
        self.code = code


def _reply(text="答案", prompt=100, candidates=20, thoughts=300):
    return SimpleNamespace(
        text=text,
        candidates=[SimpleNamespace(finish_reason=SimpleNamespace(name="STOP"))],
        usage_metadata=SimpleNamespace(prompt_token_count=prompt, candidates_token_count=candidates,
                                       thoughts_token_count=thoughts, tool_use_prompt_token_count=0))


@pytest.fixture
def vertex():
    ai_status.forget()
    a = ai_connections.create({"card": "vertex", "key": "AQ.vertex-key-a-1234567890", "label": "帳號 2"})
    b = ai_connections.create({"card": "vertex", "key": "AQ.vertex-key-b-1234567890", "label": "帳號 3"})
    yield a, b
    ai_status.forget()


def _config(a, b, **extra):
    return llm_gateway.check_config({"connections": [a.id, b.id], **extra})


def _caller(outcomes, calls):
    """outcomes: (status_key, model) -> exception or reply; default a reply."""
    async def caller(conn, model, system, contents, config, options):
        calls.append((conn.status_key, model, config["thinking_level"]))
        outcome = outcomes.get((conn.status_key, model))
        if isinstance(outcome, Exception):
            # what _generate_content records for a real call
            ai_usage.record_failure(conn.status_key)
            raise outcome
        reply = outcome or _reply()
        ai_usage.record_success(conn.status_key, reply)
        return reply
    return caller


MESSAGES = [{"role": "system", "content": "整理記憶"}, {"role": "user", "content": "做了什麼"}]


def test_first_connection_and_model_answer_with_high_thinking(vertex):
    a, b = vertex
    calls = []
    result = asyncio.run(llm_gateway.complete(MESSAGES, "claude-mem", config=_config(a, b),
                                              caller=_caller({}, calls)))
    assert calls == [(a.status_key, "gemini-4-hydrogen", "high")]
    assert (result.connection, result.model, result.thinking_level) == (a.status_key, "gemini-4-hydrogen", "high")
    assert (result.prompt_tokens, result.completion_tokens, result.thoughts_tokens) == (100, 320, 300)
    rows = ai_usage.source_rows("claude-mem")
    assert [(r["connection_id"], r["model"], r["requests"], r["completion_tokens"]) for r in rows] == \
           [(a.id, "gemini-4-hydrogen", 1, 320)]
    assert ai_usage.summary(a.id)["today"]["requests"] == 1  # the totals still count it


def test_a_rate_limited_account_hands_over_to_the_next_account(vertex):
    a, b = vertex
    calls = []
    outcomes = {(a.status_key, "gemini-4-hydrogen"): FakeError(429, "RESOURCE_EXHAUSTED")}
    result = asyncio.run(llm_gateway.complete(MESSAGES, "claude-mem", config=_config(a, b),
                                              caller=_caller(outcomes, calls)))
    assert [c[:2] for c in calls] == [(a.status_key, "gemini-4-hydrogen"), (b.status_key, "gemini-4-hydrogen")]
    assert result.connection == b.status_key
    assert result.attempts == [f"{a.status_key}/gemini-4-hydrogen:429", f"{b.status_key}/gemini-4-hydrogen:ok"]
    failed = [r for r in ai_usage.source_rows("claude-mem") if r["failures"]]
    assert [(r["connection_id"], r["failures"]) for r in failed] == [(a.id, 1)]


def test_a_spend_cap_skips_the_account_and_a_model_failure_tries_flash(vertex):
    a, b = vertex
    calls = []
    outcomes = {(a.status_key, "gemini-4-hydrogen"): FakeError(403, "PERMISSION_DENIED: Spend cap breached"),
                (b.status_key, "gemini-4-hydrogen"): FakeError(503, "UNAVAILABLE: high demand")}
    result = asyncio.run(llm_gateway.complete(MESSAGES, "claude-mem", config=_config(a, b),
                                              caller=_caller(outcomes, calls)))
    assert [c[:2] for c in calls] == [(a.status_key, "gemini-4-hydrogen"), (b.status_key, "gemini-4-hydrogen"),
                                      (b.status_key, "gemini-3.8-flash")]
    assert (result.connection, result.model, result.thinking_level) == (b.status_key, "gemini-3.8-flash", "high")
    # the capped account waits behind the other one on the next call
    assert ai_status.unusable(a.status_key)


def test_flash_on_a_rate_limited_account_is_tried_after_every_account(vertex):
    a, b = vertex
    calls = []
    outcomes = {(a.status_key, "gemini-4-hydrogen"): FakeError(429, "RESOURCE_EXHAUSTED"),
                (b.status_key, "gemini-4-hydrogen"): FakeError(429, "RESOURCE_EXHAUSTED")}
    result = asyncio.run(llm_gateway.complete(MESSAGES, "claude-mem", config=_config(a, b),
                                              caller=_caller(outcomes, calls)))
    assert [c[:2] for c in calls][2:] == [(a.status_key, "gemini-3.8-flash")]
    assert result.model == "gemini-3.8-flash"


def test_everything_rate_limited_is_a_429(vertex):
    a, b = vertex
    outcomes = {(c.status_key, m): FakeError(429, "RESOURCE_EXHAUSTED")
                for c in (a, b) for m in ("gemini-4-hydrogen", "gemini-3.8-flash")}
    with pytest.raises(llm_gateway.GatewayError) as caught:
        asyncio.run(llm_gateway.complete(MESSAGES, "claude-mem", config=_config(a, b), caller=_caller(outcomes, [])))
    assert caught.value.status == 429 and len(caught.value.attempts) == 4


def test_the_order_and_a_low_thinking_level_come_from_the_file(vertex, tmp_path):
    a, b = vertex
    path = tmp_path / "llm_gateway.json"
    path.write_text(json.dumps({"connections": [b.id, a.id], "thinking_level": "low"}), encoding="utf-8")
    config = llm_gateway.load_config(path)
    assert config["connections"] == [b.id, a.id]
    assert config["thinking_level"] == "high"  # never below high
    calls = []
    asyncio.run(llm_gateway.complete(MESSAGES, "claude-mem", config=config, caller=_caller({}, calls)))
    assert calls[0][0] == b.status_key


def test_non_vertex_connections_are_never_used(vertex):
    a, _ = vertex
    other = ai_connections.create({"card": "inception", "key": "sk-test-1234567890"})
    calls = []
    asyncio.run(llm_gateway.complete(MESSAGES, "claude-mem", config=llm_gateway.check_config(
        {"connections": [other.id, a.id]}), caller=_caller({}, calls)))
    assert {c[0] for c in calls} == {a.status_key}


def test_messages_become_a_system_instruction_and_alternating_turns():
    system, contents = llm_gateway.to_gemini([
        {"role": "system", "content": "規則"}, {"role": "user", "content": "一"},
        {"role": "user", "content": [{"type": "text", "text": "二"}]}, {"role": "assistant", "content": "好"}])
    assert system == "規則"
    assert contents == [{"role": "user", "parts": [{"text": "一\n\n二"}]}, {"role": "model", "parts": [{"text": "好"}]}]


def _client(monkeypatch, vertex, outcomes=None):
    a, b = vertex
    monkeypatch.setattr(llm_gateway, "_call", _caller(outcomes or {}, []))
    monkeypatch.setattr(llm_gateway, "load_config", lambda path=None: _config(a, b))
    token = llm_gateway.ensure_token("claude-mem")
    return TestClient(llm_gateway.create_app()), {"Authorization": f"Bearer {token}"}


def test_the_endpoint_needs_the_token(monkeypatch, vertex):
    client, _ = _client(monkeypatch, vertex)
    assert client.post("/v1/chat/completions", json={"messages": MESSAGES}).status_code == 401
    assert client.post("/v1/chat/completions", json={"messages": MESSAGES},
                       headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/health").json()["service"] == "OmniKeep LLM gateway"


def test_token_is_stored_encrypted_and_stable(vertex):
    from contextlib import closing
    from app.database import get_db_connection
    token = llm_gateway.ensure_token("claude-mem")
    assert llm_gateway.ensure_token("claude-mem") == token
    with closing(get_db_connection()) as db:
        row = db.execute("SELECT value, is_secret FROM app_settings WHERE key = '_gateway.token.claude-mem'").fetchone()
    assert row["is_secret"] == 1 and token not in row["value"]
    assert llm_gateway.source_for(f"Bearer {token}") == "claude-mem"


def test_chat_completion_answers_like_openai(monkeypatch, vertex):
    client, headers = _client(monkeypatch, vertex)
    response = client.post("/v1/chat/completions", headers=headers,
                           json={"model": "gemini-4-hydrogen", "messages": MESSAGES, "temperature": 0.3})
    body = response.json()
    assert response.status_code == 200
    assert body["choices"][0]["message"] == {"role": "assistant", "content": "答案"}
    assert body["usage"]["completion_tokens_details"]["reasoning_tokens"] == 300
    assert response.headers["x-omnikeep-thinking"] == "high"


def test_streaming_sends_the_answer_usage_and_done(monkeypatch, vertex):
    client, headers = _client(monkeypatch, vertex)
    with client.stream("POST", "/v1/chat/completions", headers=headers,
                       json={"messages": MESSAGES, "stream": True, "stream_options": {"include_usage": True}}) as r:
        lines = [line for line in r.iter_lines() if line.startswith("data: ")]
    assert lines[-1] == "data: [DONE]"
    chunks = [json.loads(line[6:]) for line in lines[:-1]]
    assert "".join(c["choices"][0]["delta"].get("content", "") for c in chunks if c["choices"]) == "答案"
    assert chunks[-1]["usage"]["total_tokens"] == 420


def test_streaming_that_fails_at_once_keeps_the_status(monkeypatch, vertex):
    a, b = vertex
    outcomes = {(c.status_key, m): FakeError(429, "RESOURCE_EXHAUSTED")
                for c in (a, b) for m in ("gemini-4-hydrogen", "gemini-3.8-flash")}
    client, headers = _client(monkeypatch, vertex, outcomes)
    response = client.post("/v1/chat/completions", headers=headers, json={"messages": MESSAGES, "stream": True})
    assert response.status_code == 429
    assert response.json()["error"]["type"] == "rate_limit_error"


def test_setup_points_claude_mem_at_the_gateway_and_backs_up(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"CLAUDE_MEM_PROVIDER": "claude", "OTHER": "kept"}), encoding="utf-8")
    backup = llm_gateway_setup.connect_claude_mem("okgw-token", 5101, "gemini-4-hydrogen", path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["CLAUDE_MEM_PROVIDER"] == "openai-compatible" and data["OTHER"] == "kept"
    assert data["CLAUDE_MEM_OPENAI_COMPAT_BASE_URL"] == "http://127.0.0.1:5101/v1"
    assert data["CLAUDE_MEM_OPENAI_COMPAT_API_KEY"] == "okgw-token"
    assert json.loads(backup.read_text(encoding="utf-8"))["CLAUDE_MEM_PROVIDER"] == "claude"
