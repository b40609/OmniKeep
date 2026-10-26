"""
OmniKeep Vector Search & Embedding Engine (sqlite-vec & Hybrid RRF).
Provides fast local vector retrieval with sqlite-vec extension and pure numpy fallback.
Supports OpenAI text-embedding-3-small (dim 256) and deterministic local projections.
"""

import hashlib
import json
import logging
import math
import re
import struct
from contextlib import closing
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

from app.config import settings
from app.database import get_db_connection, get_item_by_id

logger = logging.getLogger("omnikeep.vector")

_SQLITE_VEC_AVAILABLE: Optional[bool] = None


def is_sqlite_vec_available() -> bool:
    """Check if sqlite-vec extension can be loaded into SQLite."""
    global _SQLITE_VEC_AVAILABLE
    if _SQLITE_VEC_AVAILABLE is not None:
        return _SQLITE_VEC_AVAILABLE
    try:
        import sqlite3
        import sqlite_vec
        with closing(sqlite3.connect(":memory:")) as conn:
            conn.enable_load_extension(True)
            sqlite_vec.load(conn)
            conn.enable_load_extension(False)
            res = conn.execute("SELECT vec_version()").fetchone()
            _SQLITE_VEC_AVAILABLE = bool(res)
    except Exception as e:
        logger.warning(f"[Vector] sqlite-vec extension unavailable, falling back to numpy: {e}")
        _SQLITE_VEC_AVAILABLE = False
    return _SQLITE_VEC_AVAILABLE


def load_vec_extension(conn) -> bool:
    """Attempts to load sqlite-vec on an existing connection."""
    if not is_sqlite_vec_available():
        return False
    try:
        import sqlite_vec
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return True
    except Exception as e:
        logger.debug(f"[Vector] Failed to load sqlite-vec on connection: {e}")
        return False


def init_vector_db():
    """Initializes the virtual vector table (if sqlite-vec supported) and fallback table."""
    dim = int(settings.EMBEDDING_DIM)
    with closing(get_db_connection()) as conn, conn:
        # 1. Fallback table (standard SQLite, blob-based)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS item_embeddings (
                item_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                dim INTEGER NOT NULL,
                model TEXT NOT NULL,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 2. sqlite-vec virtual table if available
        if load_vec_extension(conn):
            try:
                conn.execute(f"""
                    CREATE VIRTUAL TABLE IF NOT EXISTS vec_items USING vec0(
                        item_id text primary key,
                        embedding float[{dim}]
                    )
                """)
            except Exception as e:
                logger.warning(f"[Vector] Could not create vec_items virtual table: {e}")


def _deterministic_local_embedding(text: str, dim: int = 256) -> List[float]:
    """
    Deterministic projection from text tokens to a normalized float vector.
    Used for local testing or when no external embedding API is configured.
    """
    vec = np.zeros(dim, dtype=np.float32)
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", (text or "").lower())
    if not tokens:
        return (vec + 1e-5).tolist()

    for token in tokens:
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
        idx = h % dim
        sign = 1.0 if ((h >> 8) & 1) else -1.0
        vec[idx] += sign

    norm = np.linalg.norm(vec)
    if norm > 1e-9:
        vec /= norm
    else:
        vec[0] = 1.0
    return vec.tolist()


async def generate_embedding(text: str) -> List[float]:
    """Generates an embedding vector for the text using OpenAI or local projection."""
    dim = int(settings.EMBEDDING_DIM)
    clean_text = (text or "").strip()[:8000]
    if not clean_text:
        return [0.0] * dim

    api_key = settings.OPENAI_API_KEY
    if api_key and not getattr(settings, "OMNIKEEP_TESTING", False):
        try:
            import httpx
            from app.network import public_http_client
            async with public_http_client(timeout=15.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "input": clean_text,
                        "model": settings.EMBEDDING_MODEL,
                        "dimensions": dim
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    vec = data["data"][0]["embedding"]
                    return vec[:dim]
        except Exception as e:
            logger.warning(f"[Vector] OpenAI embedding failed ({e}), using local projection.")

    return _deterministic_local_embedding(clean_text, dim)


def store_item_embedding(item_id: str, embedding: List[float], model: str = "") -> bool:
    """Stores the embedding vector into both the fallback table and sqlite-vec table."""
    dim = len(embedding)
    packed = struct.pack(f"{dim}f", *embedding)
    now_iso = datetime.now(timezone.utc).isoformat()
    model_name = model or settings.EMBEDDING_MODEL

    with closing(get_db_connection()) as conn, conn:
        # Fallback table
        conn.execute("""
            INSERT INTO item_embeddings (item_id, embedding, dim, model, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(item_id) DO UPDATE SET
                embedding = excluded.embedding,
                dim = excluded.dim,
                model = excluded.model,
                updated_at = excluded.updated_at
        """, (item_id, packed, dim, model_name, now_iso))

        # sqlite-vec virtual table if supported
        if load_vec_extension(conn):
            try:
                conn.execute("""
                    INSERT INTO vec_items (item_id, embedding)
                    VALUES (?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        embedding = excluded.embedding
                """, (item_id, packed))
            except Exception as e:
                # If ON CONFLICT isn't supported in vec0, fallback to delete + insert
                try:
                    conn.execute("DELETE FROM vec_items WHERE item_id = ?", (item_id,))
                    conn.execute("INSERT INTO vec_items (item_id, embedding) VALUES (?, ?)", (item_id, packed))
                except Exception as inner_e:
                    logger.debug(f"[Vector] Could not insert into vec_items: {inner_e}")
    return True


def get_item_embedding(item_id: str) -> Optional[List[float]]:
    """Retrieves the stored embedding for an item."""
    with closing(get_db_connection()) as conn:
        row = conn.execute(
            "SELECT embedding, dim FROM item_embeddings WHERE item_id = ?", (item_id,)
        ).fetchone()
        if not row:
            return None
        dim = row["dim"]
        raw = row["embedding"]
        try:
            return list(struct.unpack(f"{dim}f", raw))
        except Exception:
            return None


def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """Calculates cosine similarity between two float vectors."""
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    sim = float(np.dot(a, b) / (norm_a * norm_b))
    return max(-1.0, min(1.0, sim))


def search_similar_items(
    query_vector: List[float],
    limit: int = 10,
    min_similarity: float = 0.3
) -> List[Dict[str, Any]]:
    """
    Search for items similar to query_vector using sqlite-vec MATCH or numpy fallback.
    Returns: list of dicts with item_id, similarity, distance.
    """
    dim = len(query_vector)
    packed = struct.pack(f"{dim}f", *query_vector)
    results: List[Dict[str, Any]] = []

    with closing(get_db_connection()) as conn:
        has_vec = load_vec_extension(conn)
        used_vec = False
        if has_vec:
            try:
                # sqlite-vec MATCH query
                cursor = conn.execute("""
                    SELECT item_id, distance
                    FROM vec_items
                    WHERE embedding MATCH ? AND k = ?
                    ORDER BY distance ASC
                """, (packed, limit * 2))
                for r in cursor.fetchall():
                    dist = float(r["distance"])
                    # Approximate cosine similarity from cosine distance: sim = 1.0 - dist
                    sim = max(0.0, round(1.0 - dist, 4))
                    if sim >= min_similarity:
                        results.append({
                            "item_id": r["item_id"],
                            "similarity": sim,
                            "distance": dist
                        })
                used_vec = True
            except Exception as e:
                logger.debug(f"[Vector] sqlite-vec MATCH failed, using numpy fallback: {e}")
                results = []

        if not used_vec or not results:
            # Fallback: numpy scan over item_embeddings
            cursor = conn.execute("SELECT item_id, embedding, dim FROM item_embeddings")
            candidates = []
            for r in cursor.fetchall():
                try:
                    c_dim = r["dim"]
                    if c_dim != dim:
                        continue
                    c_vec = struct.unpack(f"{c_dim}f", r["embedding"])
                    sim = cosine_similarity(query_vector, c_vec)
                    if sim >= min_similarity:
                        candidates.append({
                            "item_id": r["item_id"],
                            "similarity": round(sim, 4),
                            "distance": round(1.0 - sim, 4)
                        })
                except Exception:
                    continue
            candidates.sort(key=lambda x: x["similarity"], reverse=True)
            results = candidates[:limit]

    return results[:limit]


def search_hybrid(query: str, limit: int = 10, vector_weight: float = 0.5) -> List[Dict[str, Any]]:
    """
    Hybrid Search combining keyword search (FTS) and vector semantic search via Reciprocal Rank Fusion (RRF).
    """
    from app.database import get_items

    # 1. Lexical search (FTS)
    fts_items = get_items(query=query, limit=limit * 2)
    fts_ranks = {item["id"]: idx + 1 for idx, item in enumerate(fts_items)}

    # 2. Vector search
    q_vec = _deterministic_local_embedding(query, int(settings.EMBEDDING_DIM))
    vec_results = search_similar_items(q_vec, limit=limit * 2, min_similarity=0.1)
    vec_ranks = {r["item_id"]: idx + 1 for idx, r in enumerate(vec_results)}
    vec_sims = {r["item_id"]: r["similarity"] for r in vec_results}

    # 3. Reciprocal Rank Fusion (RRF)
    all_ids = set(fts_ranks.keys()) | set(vec_ranks.keys())
    if not all_ids:
        return []

    scored_items = []
    k_const = 60.0
    for i_id in all_ids:
        item = get_item_by_id(i_id)
        if not item:
            continue
        rank_fts = fts_ranks.get(i_id, 9999)
        rank_vec = vec_ranks.get(i_id, 9999)

        score_fts = 1.0 / (k_const + rank_fts)
        score_vec = 1.0 / (k_const + rank_vec)
        rrf_score = (1.0 - vector_weight) * score_fts + vector_weight * score_vec

        scored_items.append({
            **item,
            "rrf_score": round(rrf_score, 6),
            "similarity": vec_sims.get(i_id, 0.0),
            "fts_rank": rank_fts if rank_fts != 9999 else None,
            "vec_rank": rank_vec if rank_vec != 9999 else None
        })

    scored_items.sort(key=lambda x: x["rrf_score"], reverse=True)
    return scored_items[:limit]
