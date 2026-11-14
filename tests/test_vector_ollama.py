"""Local Ollama embeddings (embeddinggemma-2) on top of the honest model labels.

The runner is tried first, its vectors are labelled with EMBEDDING_MODEL, the cloud
fallback is labelled with the model it really used, and search only compares vectors
that share the query's label.
"""
import asyncio
from unittest.mock import MagicMock

import numpy as np
import pytest

from app import reindex
from app.config import settings
from app.database import init_db, save_item
from app.vector import (
    LOCAL_EMBEDDING_MODEL,
    generate_embedding_with_model,
    init_vector_db,
    search_hybrid,
    store_item_embedding,
)
import app.vector as vector

DIM = 256


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    init_db()
    init_vector_db()
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "embeddinggemma-2")
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://llm.example.test/v1")


def _unit(i: int, size: int = 768):
    v = np.zeros(size, dtype=np.float32)
    v[i] = 3.0
    return v.tolist()


class _FakeClient:
    """Stands in for httpx.AsyncClient (Ollama) and public_http_client (cloud)."""

    def __init__(self, calls, ollama_ok=True):
        self.calls = calls
        self.ollama_ok = ollama_ok

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "json": json})
        resp = MagicMock()
        resp.text = ""
        if url.endswith("/api/embed"):
            if not self.ollama_ok:
                raise ConnectionError("ollama down")
            resp.status_code = 200
            resp.json.return_value = {"embeddings": [_unit(0 if "fastapi" in json["input"].lower() else 1)]}
        else:
            resp.status_code = 200
            resp.json.return_value = {"data": [{"embedding": _unit(2, DIM)}]}
        return resp


def _patch_clients(monkeypatch, calls, ollama_ok=True):
    monkeypatch.setattr(vector, "ollama_embedding_enabled", lambda: True)
    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: _FakeClient(calls, ollama_ok))
    monkeypatch.setattr("app.network.public_http_client", lambda **kw: _FakeClient(calls, ollama_ok))


def test_ollama_vector_is_cut_normalised_and_labelled(monkeypatch):
    calls = []
    _patch_clients(monkeypatch, calls)

    vec, model = asyncio.run(generate_embedding_with_model("FastAPI backend"))
    assert model == "embeddinggemma-2"
    assert len(vec) == 768  # the model's full width (app.embedding_profiles)
    assert vec[0] == pytest.approx(1.0)
    monkeypatch.setattr(vector.settings, "EMBEDDING_DIM", DIM)  # a fixed width cuts every model's vector
    assert len(asyncio.run(generate_embedding_with_model("FastAPI backend"))[0]) == DIM
    monkeypatch.setattr(vector.settings, "EMBEDDING_DIM", 0)
    calls[1:] = []
    assert calls[0]["url"] == "http://127.0.0.1:11434/api/embed"
    assert calls[0]["json"] == {"model": "embeddinggemma-2", "input": "FastAPI backend", "keep_alive": "30m"}

    asyncio.run(generate_embedding_with_model("FastAPI backend", is_query=True))
    assert calls[1]["json"]["input"] == "task: search result | query: FastAPI backend"


def test_cloud_fallback_uses_and_labels_the_real_model(monkeypatch):
    calls = []
    _patch_clients(monkeypatch, calls, ollama_ok=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "synthetic-key")

    vec, model = asyncio.run(generate_embedding_with_model("bread baking"))
    assert model == "text-embedding-3-small"  # not "embeddinggemma-2": that model never ran
    assert calls[-1]["url"] == "https://llm.example.test/v1/embeddings"
    assert calls[-1]["json"]["model"] == "text-embedding-3-small"


def test_no_runner_no_key_falls_back_to_local_hash(monkeypatch):
    calls = []
    _patch_clients(monkeypatch, calls, ollama_ok=False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    _vec, model = asyncio.run(generate_embedding_with_model("anything"))
    assert model == LOCAL_EMBEDDING_MODEL


def test_blank_ollama_url_skips_the_runner(monkeypatch):
    monkeypatch.setattr(settings, "OLLAMA_BASE_URL", "")
    monkeypatch.setenv("OMNIKEEP_TESTING", "0")
    assert vector.ollama_embedding_enabled() is False


def test_search_only_compares_vectors_with_the_query_model(monkeypatch):
    calls = []
    _patch_clients(monkeypatch, calls)
    same_space = save_item({"url": "https://example.test/gemma", "title_l1": "Starlette", "summary_l1": "ASGI"})
    other_space = save_item({"url": "https://example.test/cloud", "title_l1": "Sourdough", "summary_l1": "flour"})
    vec, model = asyncio.run(generate_embedding_with_model("fastapi web framework"))
    store_item_embedding(same_space, vec, model=model)
    # Same numbers, other model: in its own space this vector means something else.
    store_item_embedding(other_space, vec, model="text-embedding-3-small")

    results = asyncio.run(search_hybrid("FastAPI", limit=5))
    by_id = {r["id"]: r for r in results}
    assert by_id[same_space]["vec_rank"] == 1
    assert other_space not in by_id


def test_reindex_target_is_the_runner_model_when_enabled(monkeypatch):
    monkeypatch.setattr(reindex, "ollama_embedding_enabled", lambda: True)
    assert reindex.target_model() == "embeddinggemma-2"
    monkeypatch.setattr(reindex, "ollama_embedding_enabled", lambda: False)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "synthetic-key")
    assert reindex.target_model() == "text-embedding-3-small"
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    assert reindex.target_model() == LOCAL_EMBEDDING_MODEL
