"""Regression coverage for OpenAI-compatible endpoints returning raw strings."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.providers.openai_compatible import (
    OpenAICompatibleProvider, ProviderUnavailableError, extract_completion_content,
)
from app.parsers.reel import analyze_storyboard_vision
from app.database import create_ingest_task, get_ingest_task
from app.queue.worker import TaskWorker


def _completion(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


@pytest.mark.parametrize("response", [
    _completion("model answer"),
    {"choices": [{"message": {"content": "model answer"}}]},
    json.dumps({"choices": [{"message": {"content": "model answer"}}]}),
    "model answer",
    '"model answer"',
])
@pytest.mark.asyncio
async def test_generate_text_accepts_completion_and_string_responses(response):
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub")
    provider._chat = AsyncMock(return_value=response)
    assert await provider.generate_text("prompt") == "model answer"


@pytest.mark.parametrize("response", [
    _completion('{"category":"Inbox"}'),
    {"choices": [{"message": {"content": '{"category":"Inbox"}'}}]},
    json.dumps({"choices": [{"message": {"content": '{"category":"Inbox"}'}}]}),
    '{"category":"Inbox"}',
])
@pytest.mark.asyncio
async def test_generate_json_accepts_completion_and_string_responses(response):
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub")
    provider._chat = AsyncMock(return_value=response)
    assert await provider.generate_json("prompt") == {"category": "Inbox"}
    assert provider._chat.await_count == 1


@pytest.mark.asyncio
async def test_generate_json_falls_back_when_response_format_is_unsupported():
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub")
    provider._chat = AsyncMock(side_effect=[ValueError("unsupported response_format"),
                                            '```json\n{"category":"Inbox"}\n```'])
    assert await provider.generate_json("prompt") == {"category": "Inbox"}
    assert provider._chat.await_count == 2
    assert "response_format" not in provider._chat.call_args.kwargs


def test_invalid_completion_has_clear_error():
    with pytest.raises(ValueError, match="missing choices"):
        extract_completion_content({"unexpected": "payload"})


@pytest.mark.asyncio
async def test_blocked_html_response_is_not_retried_as_json():
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub")
    provider._chat = AsyncMock(return_value="\ufeff<!DOCTYPE html><html><body>Blocked</body></html>")
    with pytest.raises(ProviderUnavailableError, match="網路封鎖"):
        await provider.generate_json("prompt")
    assert provider._chat.await_count == 1


@pytest.mark.asyncio
async def test_json_with_bom_is_supported():
    provider = OpenAICompatibleProvider(api_key="test-only", model="stub")
    provider._chat = AsyncMock(return_value='\ufeff{"category":"Inbox"}')
    assert await provider.generate_json("prompt") == {"category": "Inbox"}


@pytest.mark.asyncio
async def test_worker_fails_blocked_provider_without_retry(isolated_runtime):
    task = create_ingest_task("https://example.org/blocked", chat_id=123, message_id=456)
    blocked = ProviderUnavailableError("AI 服務回傳網路封鎖頁面")
    with patch("app.queue.worker.run_pipeline", new=AsyncMock(side_effect=blocked)) as pipeline, \
         patch("app.queue.worker.notify_task_failed", new=AsyncMock()) as failed, \
         patch("app.queue.worker.notify_task_heartbeat", new=AsyncMock()):
        await TaskWorker()._process_task(task)
    stored = get_ingest_task(task["id"])
    assert stored["status"] == "failed"
    assert stored["retry_count"] == 0
    assert "網路封鎖" in stored["error_message"]
    pipeline.assert_awaited_once()
    failed.assert_awaited_once()


@pytest.mark.asyncio
async def test_reel_vision_accepts_string_response(isolated_runtime, monkeypatch):
    tile = isolated_runtime / "storyboard.jpg"
    tile.write_bytes(b"x" * 1025)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=AsyncMock(return_value="九宮格畫面辨識成功")
    )))
    monkeypatch.setattr("app.parsers.reel.get_primary_provider", lambda: SimpleNamespace(client=client, model="stub"))
    assert await analyze_storyboard_vision(str(tile)) == "九宮格畫面辨識成功"
