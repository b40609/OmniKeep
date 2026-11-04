import asyncio
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch, AsyncMock

import pytest
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.database import (
    save_item,
    get_item_by_id,
    init_db
)
from app.vector import (
    is_sqlite_vec_available,
    store_item_embedding,
    get_item_embedding,
    search_similar_items,
    search_hybrid,
    cosine_similarity,
    _deterministic_local_embedding
)
from app.snapshot import (
    save_html_snapshot,
    get_html_snapshot,
    has_html_snapshot,
    get_snapshot_info
)
from app.radar.clustering import cluster_item_to_event


# ── 1. sqlite-vec & Vector Search Tests ────────────────────────

def test_sqlite_vec_and_embedding_storage():
    # sqlite-vec extension should be available in this environment
    assert is_sqlite_vec_available() is True

    item_id_1 = f"vec_test_{uuid.uuid4().hex[:6]}"
    item_id_2 = f"vec_test_{uuid.uuid4().hex[:6]}"

    # Store embeddings
    vec1 = _deterministic_local_embedding("FastAPI async backend architecture", dim=256)
    vec2 = _deterministic_local_embedding("Cooking recipes for delicious bread", dim=256)

    assert store_item_embedding(item_id_1, vec1) is True
    assert store_item_embedding(item_id_2, vec2) is True

    # Retrieve embedding
    retrieved = get_item_embedding(item_id_1)
    assert retrieved is not None
    assert len(retrieved) == 256
    assert abs(retrieved[0] - vec1[0]) < 1e-5

    # Semantic search query close to item 1
    q_vec = _deterministic_local_embedding("FastAPI asynchronous web APIs", dim=256)
    results = search_similar_items(q_vec, limit=5, min_similarity=0.1)

    assert len(results) >= 1
    # item_id_1 should rank higher than item_id_2
    found_ids = [r["item_id"] for r in results]
    assert item_id_1 in found_ids
    idx1 = found_ids.index(item_id_1)
    if item_id_2 in found_ids:
        idx2 = found_ids.index(item_id_2)
        assert idx1 < idx2


def test_local_embedding_projection_and_cosine():
    v_a = _deterministic_local_embedding("Kubernetes container orchestration cluster")
    v_b = _deterministic_local_embedding("Kubernetes container orchestration cluster")
    v_c = _deterministic_local_embedding("Baking chocolate chip cookies in oven")

    # Determinism
    assert v_a == v_b
    assert v_a != v_c

    # Self-similarity is 1.0
    sim_self = cosine_similarity(v_a, v_b)
    assert abs(sim_self - 1.0) < 1e-5

    # Dissimilar topics have lower similarity
    sim_diff = cosine_similarity(v_a, v_c)
    assert sim_diff < sim_self


# ── 2. Monolith HTML Snapshot Tests ──────────────────────────

def test_monolith_html_snapshot_lifecycle():
    item_id = f"snap_item_{uuid.uuid4().hex[:8]}"
    sample_html = """
    <!DOCTYPE html>
    <html>
      <head><title>Test Article</title></head>
      <body>
        <h1>Breaking Research on Deep Learning</h1>
        <p>This is the archived body text.</p>
        <script>alert('malicious tracker');</script>
        <button onclick="badCode()">Click</button>
      </body>
    </html>
    """
    source_url = "https://tech-blog.example.com/deep-learning-breakthrough"

    # Initially has no snapshot
    assert has_html_snapshot(item_id) is False

    # Save snapshot
    path = save_html_snapshot(item_id, sample_html, source_url)
    assert path is not None
    assert has_html_snapshot(item_id) is True

    # Check content
    saved_html = get_html_snapshot(item_id)
    assert saved_html is not None
    assert "Breaking Research on Deep Learning" in saved_html
    assert "omnikeep-snapshot-banner" in saved_html
    assert "💾 OmniKeep 本地整頁快照存檔" in saved_html
    # Scripts and onclick should be sanitized away
    assert "<script" not in saved_html.lower()
    assert "badCode" not in saved_html

    # Check info
    info = get_snapshot_info(item_id)
    assert info["has_snapshot"] is True
    assert info["size_bytes"] > 0
    assert info["path"] == path


# ── 3. Vector Deduplication & Radar Clustering Tests ───────────

def test_vector_radar_clustering_deduplication():
    # Item A
    id_a = save_item({
        "url": "https://news.example/postgres-17-replication",
        "title_l1": "PostgreSQL 17 Logical Replication Deep Dive",
        "summary_l1": "Analyzing new streaming failover and replication protocols in Postgres",
        "tech_tags": ["PostgreSQL", "Database"],
        "origin": "radar"
    })
    vec_a = _deterministic_local_embedding("PostgreSQL 17 Logical Replication streaming failover")
    store_item_embedding(id_a, vec_a)

    item_a = get_item_by_id(id_a)
    event_id_1 = cluster_item_to_event(item_a)
    assert event_id_1 is not None

    # Item B discusses the same topic with different wording
    id_b = save_item({
        "url": "https://news.example/postgres-cdc-failover",
        "title_l1": "PostgreSQL 17 CDC Failover Benchmark",
        "summary_l1": "Measuring logical replication throughput and failover latency in PostgreSQL 17",
        "tech_tags": ["PostgreSQL", "Database"],
        "origin": "radar"
    })
    vec_b = _deterministic_local_embedding("PostgreSQL 17 Logical Replication failover CDC benchmark")
    store_item_embedding(id_b, vec_b)

    item_b = get_item_by_id(id_b)
    event_id_2 = cluster_item_to_event(item_b)

    # Item B should merge into Event 1 via vector similarity
    assert event_id_2 == event_id_1


# ── 4. Snapshot & Semantic Search API Endpoints ───────────────

@pytest.mark.asyncio
async def test_snapshot_and_semantic_search_api():
    from app.main import app

    # 1. Create item with snapshot
    item_id = save_item({
        "url": "https://example.com/vector-article",
        "title_l1": "Zero-Dependency SQLite Vector Extensions",
        "summary_l1": "High performance vector search natively in SQLite with C extensions",
        "tech_tags": ["SQLite", "Vector", "Search"],
        "origin": "radar"
    })
    vec = _deterministic_local_embedding("Zero-Dependency SQLite Vector Extensions performance search")
    store_item_embedding(item_id, vec)

    html_content = "<html><body><h1>SQLite Vector Rocks</h1></body></html>"
    save_html_snapshot(item_id, html_content, "https://example.com/vector-article")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        # GET Snapshot status
        res_status = await client.get(f"/api/items/{item_id}/snapshot/status")
        assert res_status.status_code == 200
        assert res_status.json()["has_snapshot"] is True

        # GET Snapshot HTML
        res_snap = await client.get(f"/api/items/{item_id}/snapshot")
        assert res_snap.status_code == 200
        assert "text/html" in res_snap.headers["content-type"]
        assert "SQLite Vector Rocks" in res_snap.text

        # GET Semantic Search
        res_search = await client.get("/api/items/search/semantic?q=SQLite+vector+search")
        assert res_search.status_code == 200
        results = res_search.json()
        assert len(results) >= 1
        assert any(r["id"] == item_id for r in results)
        assert "rrf_score" in results[0]


@pytest.mark.asyncio
async def test_dreampass_llm_model_and_radar_source_whitelist(monkeypatch):
    from app.main import app
    from app.radar.dreampass import run_dreampass_reflection

    # 1. Verify settings.OPENAI_MODEL resolves to PRIMARY_MODEL without AttributeError
    assert settings.OPENAI_MODEL == settings.PRIMARY_MODEL

    captured_payload = {}

    class DummyResp:
        status_code = 200
        def json(self):
            return {
                "choices": [{
                    "message": {
                        "content": '{"observations": ["LLM path works"], "suggested_profile": "AI Systems", "diff_summary": "+ AI Systems"}'
                    }
                }]
            }

    class DummyClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, headers=None, json=None):
            captured_payload["url"] = url
            captured_payload["json"] = json
            return DummyResp()

    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setattr("app.network.public_http_client", lambda timeout=30.0: DummyClient())

    prop = await run_dreampass_reflection(days=7)
    assert prop["suggested_profile"] == "AI Systems"
    assert captured_payload["json"]["model"] == settings.PRIMARY_MODEL

    # 2. Verify google_news and web_change source types are accepted by /api/radar/sources
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        for stype, url in [
            ("google_news", "https://news.google.com/rss/search?q=SQLite"),
            ("web_change", "https://example.com/changelog"),
        ]:
            res = await client.post("/api/radar/sources", json={
                "name": f"Test {stype}",
                "source_type": stype,
                "url": url,
                "tier": 1,
                "check_interval_minutes": 60
            })
            assert res.status_code == 200, res.text
            assert res.json()["success"] is True


@pytest.mark.asyncio
async def test_embedding_custom_base_url_and_gemini_async_offload(monkeypatch):
    from app.vector import generate_embedding
    from app.providers.gemini import GeminiProvider

    # 1. Verify generate_embedding uses settings.OPENAI_BASE_URL and maps default model to text-embedding-3-small
    captured = {}

    class DummyEmbedResp:
        status_code = 200
        def json(self):
            return {"data": [{"embedding": [0.25] * 256}]}

    class DummyHttpClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def post(self, url, headers=None, json=None):
            if "/api/embed" in url:
                raise RuntimeError("Ollama offline")
            captured["url"] = url
            captured["json"] = json
            return DummyEmbedResp()

    monkeypatch.setenv("OMNIKEEP_TESTING", "0")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-embed-key")
    monkeypatch.setattr(settings, "OPENAI_BASE_URL", "https://custom-llm.example.com/v1/")
    monkeypatch.setattr("app.network.public_http_client", lambda timeout=15.0: DummyHttpClient())

    vec = await generate_embedding("semantic query test", is_query=True)
    assert len(vec) == 256
    assert vec[0] == 0.25
    assert captured["url"] == "https://custom-llm.example.com/v1/embeddings"
    assert captured["json"]["model"] == "text-embedding-3-small"

    # 2. Verify GeminiProvider offloads synchronous generate_content via asyncio.to_thread
    thread_calls = []
    orig_to_thread = asyncio.to_thread

    async def spy_to_thread(func, *args, **kwargs):
        thread_calls.append(func)
        return await orig_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)

    class DummyModels:
        def generate_content(self, **kwargs):
            class R:
                text = '{"ok": true}'
            return R()

    class DummyGenaiClient:
        def __init__(self, api_key):
            self.models = DummyModels()

    import google.genai as genai_mod
    monkeypatch.setattr(genai_mod, "Client", DummyGenaiClient)

    prov = GeminiProvider(api_keys=["test-gemini-key"], model="gemini-2.5-flash")
    out_json = await prov.generate_json("test prompt")
    assert out_json == {"ok": True}
    assert len(thread_calls) == 1

