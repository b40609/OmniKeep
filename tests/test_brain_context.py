"""Ask Brain sends a context window large enough for its citations (num_ctx),
caps citations and history, and keeps history when falling back to the cloud."""
import pytest

import app.brain as brain
from app.config import settings


class _Response:
    status_code = 200

    def json(self):
        return {"message": {"content": "依據文獻 [1] 的回答"}}


class _Client:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None):
        _Client.sent.append((url, json))
        return _Response()


@pytest.fixture
def stub_search(monkeypatch):
    seen = {}

    async def fake_search(query, limit=10, vector_weight=0.5, usable_only=False):
        seen["limit"] = limit
        return [{"id": "a", "title_l1": "文獻", "summary_l1": "摘要", "content_raw": "內容"}]

    monkeypatch.setattr(brain, "search_hybrid", fake_search)
    return seen


@pytest.mark.asyncio
async def test_local_brain_passes_num_ctx(monkeypatch, stub_search):
    _Client.sent = []
    monkeypatch.setattr(brain.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(settings, "BRAIN_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "BRAIN_NUM_CTX", 32768)

    res = await brain.ask_brain("問題")

    assert res["provider"] == "local_ollama_gpu"
    url, payload = _Client.sent[0]
    assert url.endswith("/api/chat")
    assert payload["options"]["num_ctx"] == 32768


@pytest.mark.asyncio
async def test_citation_limit_is_capped_by_setting(monkeypatch, stub_search):
    monkeypatch.setattr(brain.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(settings, "BRAIN_PROVIDER", "ollama")
    monkeypatch.setattr(settings, "BRAIN_MAX_CITATIONS", 3)

    await brain.ask_brain("問題", limit=50)

    assert stub_search["limit"] == 3


@pytest.mark.asyncio
async def test_history_is_capped_and_kept_in_cloud_fallback(monkeypatch, stub_search):
    prompts = []

    class FakeProvider:
        async def generate_text(self, prompt, system_prompt=None):
            prompts.append(prompt)
            return "雲端回答"

    # The cloud fallback is the brain slot (it follows analysis while empty).
    monkeypatch.setattr("app.providers.get_provider", lambda *a, **k: FakeProvider())
    history = [{"role": "user", "content": f"第{i}輪"} for i in range(6)]
    history.append({"role": "assistant", "content": "長" * 5000})

    res = await brain.ask_brain("追問", history=history, force_cloud=True)

    assert res["provider"] == "cloud_fallback"
    prompt = prompts[0]
    assert "【先前對話】" in prompt and "【使用者問題】\n追問" in prompt
    assert "第0輪" not in prompt and "第2輪" not in prompt  # only the last 4 turns
    assert "第3輪" in prompt
    assert "長" * brain.MAX_HISTORY_CHARS in prompt and "長" * (brain.MAX_HISTORY_CHARS + 1) not in prompt
