"""Regression test for review-20261102 bug 1.

Dream Pass read a non-existent ``settings.OPENAI_MODEL`` so its LLM path
always raised AttributeError and silently fell back to the heuristic.
"""
import asyncio
import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.database import init_db, set_interest_profile


@pytest.fixture(autouse=True)
def _db():
    init_db()


def _mock_http_client(resp):
    client = AsyncMock()
    client.post = AsyncMock(return_value=resp)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


# ── Bug 1: Dream Pass LLM path ───────────────────────────────────────────

def test_dreampass_llm_path_uses_primary_model(monkeypatch):
    from app.radar.dreampass import run_dreampass_reflection

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-dreampass")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://llm.example.test/v1/")
    monkeypatch.setattr(settings, "PRIMARY_MODEL", "test-primary-model")
    set_interest_profile("關注分散式系統。")

    llm_json = {
        "observations": ["最近偏好向量資料庫", "對前端框架興趣下降"],
        "suggested_profile": "LLM 產出的新畫像：關注分散式系統與向量資料庫。",
        "diff_summary": "＋ 向量資料庫\n－ 前端框架",
    }
    resp = MagicMock()
    resp.status_code = 200
    resp.text = ""
    resp.json.return_value = {"choices": [{"message": {"content": json.dumps(llm_json, ensure_ascii=False)}}]}
    client = _mock_http_client(resp)

    with patch("app.radar.dreampass.public_http_client", return_value=client):
        prop = asyncio.run(run_dreampass_reflection(days=7))

    # The LLM result, not the heuristic, must be what gets recorded.
    assert prop["suggested_profile"] == llm_json["suggested_profile"]
    assert prop["diff_summary"] == llm_json["diff_summary"]
    assert "向量資料庫" in prop["observations"]

    client.post.assert_awaited_once()
    args, kwargs = client.post.await_args
    assert args[0] == "https://llm.example.test/v1/chat/completions"
    assert kwargs["json"]["model"] == "test-primary-model"
    assert kwargs["headers"]["Authorization"] == "Bearer sk-test-dreampass"


def test_dreampass_llm_failure_is_logged_not_swallowed(monkeypatch, caplog):
    from app.radar.dreampass import run_dreampass_reflection

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-dreampass")
    client = AsyncMock()
    client.post = AsyncMock(side_effect=RuntimeError("boom-from-llm"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.radar.dreampass.public_http_client", return_value=client), \
            caplog.at_level(logging.WARNING, logger="omnikeep.dreampass"):
        prop = asyncio.run(run_dreampass_reflection(days=7))

    # Falls back to heuristic ...
    assert prop["id"]
    assert prop["suggested_profile"]
    # ... but the failure is visible in the logs with the exception type.
    msgs = [r.getMessage() for r in caplog.records if r.name == "omnikeep.dreampass"]
    assert any("RuntimeError" in m and "boom-from-llm" in m for m in msgs), msgs


def test_dreampass_llm_non_200_is_logged(monkeypatch, caplog):
    from app.radar.dreampass import run_dreampass_reflection

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-dreampass")
    resp = MagicMock()
    resp.status_code = 429
    resp.text = "rate limited"
    client = _mock_http_client(resp)

    with patch("app.radar.dreampass.public_http_client", return_value=client), \
            caplog.at_level(logging.WARNING, logger="omnikeep.dreampass"):
        prop = asyncio.run(run_dreampass_reflection(days=7))

    assert prop["id"]
    msgs = [r.getMessage() for r in caplog.records if r.name == "omnikeep.dreampass"]
    assert any("429" in m for m in msgs), msgs
