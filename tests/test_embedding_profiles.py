"""Each embedding model gets its own query format and stored width, and the sqlite-vec
mirror follows the width when the model changes."""
import struct
from contextlib import closing

import pytest

import app.vector as vector
from app.config import settings
from app.database import get_db_connection, init_db
from app.embedding_profiles import DEFAULT_DIM, model_dim, query_text, recommend


@pytest.mark.parametrize("model,dim", [
    ("embeddinggemma-2", 768),
    ("embeddinggemma-2:570m", 768),
    ("qwen3-embedding:0.6b", 1024),
    ("qwen3-embedding:4b", 1024),
    ("qwen3-embedding:8b", 1024),
    ("qwen3-embedding", 1024),
    ("hf.co/mradermacher/harrier-oss-v1-0.6b-GGUF:Q8_0", 1024),
    ("bge-m3:latest", 1024),
    ("text-embedding-3-small", DEFAULT_DIM),
])
def test_model_dim(model, dim, monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 0)
    assert model_dim(model) == dim


def test_fixed_dim_wins(monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 512)
    assert model_dim("qwen3-embedding:8b") == 512


def test_query_formats():
    assert query_text("embeddinggemma-2", "x") == "task: search result | query: x"
    assert query_text("qwen3-embedding:8b", "x").endswith("\nQuery:x")
    assert query_text("hf.co/mradermacher/harrier-oss-v1-0.6b-GGUF:Q8_0", "x").endswith("\nQuery: x")
    assert query_text("bge-m3", "x") == "x"
    assert query_text("unknown-model", "x") == "x"


def test_vec_items_follows_the_model_width(monkeypatch):
    init_db()
    with closing(get_db_connection()) as conn:
        if not vector.load_vec_extension(conn):
            pytest.skip("sqlite-vec not available")
    monkeypatch.setattr(vector, "target_embedding_model", lambda: "embeddinggemma-2")
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 0)
    vector.init_vector_db()
    with closing(get_db_connection()) as conn:
        vector.load_vec_extension(conn)
        assert vector._vec_table_dim(conn) == 768
        with conn:
            conn.execute("INSERT OR REPLACE INTO item_embeddings (item_id, embedding, dim, model) VALUES (?, ?, ?, ?)",
                         ("dimtest", struct.pack("1024f", *([0.0] * 1023 + [1.0])), 1024, "qwen3-embedding:0.6b"))

    monkeypatch.setattr(vector, "target_embedding_model", lambda: "qwen3-embedding:0.6b")
    vector.init_vector_db()
    with closing(get_db_connection()) as conn:
        vector.load_vec_extension(conn)
        assert vector._vec_table_dim(conn) == 1024
        assert conn.execute("SELECT COUNT(*) FROM vec_items WHERE item_id = 'dimtest'").fetchone()[0] == 1
        with conn:
            conn.execute("DELETE FROM item_embeddings WHERE item_id = 'dimtest'")
            conn.execute("DELETE FROM vec_items WHERE item_id = 'dimtest'")


@pytest.mark.parametrize("hardware,model", [
    ({"gpus": [{"name": "GPU", "vram_gb": 16.0}], "ram_gb": 63.8, "os": "Windows 11"}, "qwen3-embedding:8b"),
    ({"gpus": [{"name": "GPU", "vram_gb": 6.0}], "ram_gb": 16, "os": "Windows 11"}, "qwen3-embedding:4b"),
    ({"gpus": [], "ram_gb": 16, "os": "Windows 11"}, "hf.co/mradermacher/harrier-oss-v1-0.6b-GGUF:Q8_0"),
    ({"gpus": [], "ram_gb": 4, "os": "Linux 6"}, "hf.co/mykor/harrier-oss-v1-270m-GGUF:Q8_0"),
    ({"gpus": [], "ram_gb": 32, "os": "Darwin 24", "cpu": "arm"}, "qwen3-embedding:8b"),
    ({"gpus": [], "ram_gb": 8, "os": "Darwin 24", "cpu": "arm"}, "qwen3-embedding:4b"),
])
def test_recommend_by_hardware(hardware, model, monkeypatch):
    monkeypatch.setattr(settings, "EMBEDDING_DIM", 0)
    pick = recommend(hardware)
    assert pick["model"] == model
    assert pick["dim"] == model_dim(model)
