"""Regression tests for review-20261102 bug 3.

Semantic search built the *query* vector with the local hashed bag-of-words
projection even when items were indexed with the remote embedding model, so
the two sides lived in different vector spaces. The embeddings URL was also
hard-coded to api.openai.com instead of following OPENAI_BASE_URL.
"""
import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.config import settings
from app.database import init_db, save_item
from app.vector import (
    LOCAL_EMBEDDING_MODEL,
    _deterministic_local_embedding,
    embeddings_api_url,
    generate_embedding_with_model,
    init_vector_db,
    search_hybrid,
    store_item_embedding,
)


@pytest.fixture(autouse=True)
def _db():
    init_db()
    init_vector_db()


def _fake_remote_embedding(text: str, dim: int):
    """A stand-in 'semantic' model that is deliberately NOT the local hash:
    everything about FastAPI maps to one direction, everything else to another."""
    vec = np.zeros(dim, dtype=np.float32)
    if "fastapi" in text.lower():
        vec[0] = 1.0
    else:
        vec[1] = 1.0
    return vec.tolist()


def _mock_embedding_client(dim: int, calls: list):
    async def post(url, headers=None, json=None):
        calls.append({"url": url, "headers": headers, "json": json})
        resp = MagicMock()
        resp.status_code = 200
        resp.text = ""
        resp.json.return_value = {"data": [{"embedding": _fake_remote_embedding(json["input"], dim)}]}
        return resp

    client = AsyncMock()
    client.post = AsyncMock(side_effect=post)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def test_embeddings_url_follows_base_url(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "http://ollama.local:11434/v1/")
    assert embeddings_api_url() == "http://ollama.local:11434/v1/embeddings"


def test_generate_embedding_posts_to_configured_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-embed-test")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://llm.example.test/v1")
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "test-embed-model")
    calls = []
    client = _mock_embedding_client(int(settings.EMBEDDING_DIM), calls)

    with patch("app.network.public_http_client", return_value=client):
        vec, model = asyncio.run(generate_embedding_with_model("FastAPI async backend"))

    assert model == "test-embed-model"
    assert len(vec) == int(settings.EMBEDDING_DIM)
    assert calls[0]["url"] == "https://llm.example.test/v1/embeddings"
    assert calls[0]["json"]["model"] == "test-embed-model"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-embed-test"


def test_generate_embedding_labels_local_fallback(monkeypatch):
    # No key -> local projection, and the label must say so (it used to be
    # recorded as the remote model name).
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    vec, model = asyncio.run(generate_embedding_with_model("hello world"))
    assert model == LOCAL_EMBEDDING_MODEL
    assert vec == _deterministic_local_embedding("hello world", int(settings.EMBEDDING_DIM))

    # Key set but endpoint failing -> still local, still labelled local.
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-embed-test")
    client = AsyncMock()
    client.post = AsyncMock(side_effect=RuntimeError("endpoint down"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    with patch("app.network.public_http_client", return_value=client):
        vec, model = asyncio.run(generate_embedding_with_model("hello world"))
    assert model == LOCAL_EMBEDDING_MODEL


def test_search_hybrid_query_uses_same_embedding_space_as_index(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-embed-test")
    monkeypatch.setattr(settings, "EMBEDDING_MODEL", "test-embed-model")
    dim = int(settings.EMBEDDING_DIM)
    calls = []
    client = _mock_embedding_client(dim, calls)

    # Titles/summaries share no tokens with the query, so FTS and the local
    # bag-of-words projection can't produce the hit; only the fake remote
    # model (shared by index and query) can.
    with patch("app.network.public_http_client", return_value=client):
        id_fastapi = save_item({
            "url": "https://example.test/a",
            "title_l1": "Starlette-based Python web framework",
            "summary_l1": "ASGI, pydantic, dependency injection",
            "tech_tags": ["asgi"],
        })
        vec, model = asyncio.run(generate_embedding_with_model("fastapi web framework"))
        store_item_embedding(id_fastapi, vec, model=model)

        id_other = save_item({
            "url": "https://example.test/b",
            "title_l1": "Sourdough starter maintenance",
            "summary_l1": "flour, water, patience",
            "tech_tags": ["baking"],
        })
        vec, model = asyncio.run(generate_embedding_with_model("bread baking"))
        store_item_embedding(id_other, vec, model=model)

        results = asyncio.run(search_hybrid("FastAPI", limit=5))

    # The query went through the remote embedding path (3rd call), not the local hash.
    assert len(calls) == 3 and calls[-1]["json"]["input"] == "FastAPI"

    by_id = {r["id"]: r for r in results}
    assert id_fastapi in by_id
    assert by_id[id_fastapi]["vec_rank"] == 1
    assert by_id[id_fastapi]["similarity"] > 0.99
    assert by_id[id_fastapi]["fts_rank"] is None  # no lexical overlap: this is a vector hit
    if id_other in by_id:
        assert by_id[id_other]["similarity"] < 0.5


def test_search_hybrid_still_works_fully_local(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    item_id = save_item({
        "url": "https://example.test/c",
        "title_l1": "Zero-Dependency SQLite Vector Extensions",
        "summary_l1": "vector search natively in SQLite",
        "tech_tags": ["SQLite", "Vector"],
    })
    vec, model = asyncio.run(generate_embedding_with_model("SQLite vector search extensions"))
    assert model == LOCAL_EMBEDDING_MODEL
    store_item_embedding(item_id, vec, model=model)

    results = asyncio.run(search_hybrid("SQLite vector search", limit=5))
    assert any(r["id"] == item_id and r["vec_rank"] == 1 for r in results)


def test_search_hybrid_warns_on_index_model_mismatch(monkeypatch, caplog):
    import app.vector as vector_mod
    monkeypatch.setattr(vector_mod, "_last_warned", {})
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")

    item_id = save_item({"url": "https://example.test/d", "title_l1": "Old row", "summary_l1": "", "tech_tags": []})
    store_item_embedding(item_id, _deterministic_local_embedding("old row"), model="text-embedding-3-small")

    with caplog.at_level(logging.WARNING, logger="omnikeep.vector"):
        asyncio.run(search_hybrid("old row", limit=5))
        asyncio.run(search_hybrid("old row", limit=5))

    msgs = [r.getMessage() for r in caplog.records if r.name == "omnikeep.vector" and "re-indexed" in r.getMessage()]
    assert len(msgs) == 1, msgs  # warned once, not on every query
    assert "text-embedding-3-small" in msgs[0] and LOCAL_EMBEDDING_MODEL in msgs[0]
