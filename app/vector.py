"""
OmniKeep Vector Search & Embedding Engine (sqlite-vec & Hybrid RRF).
Provides fast local vector retrieval with sqlite-vec extension and pure numpy fallback.
Supports local Ollama embeddinggemma-2, OpenAI-compatible endpoints (dim 256) and deterministic local projections.
"""

import hashlib
import json
import logging
import math
import os
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

# Model label recorded for vectors produced by the hashed bag-of-words fallback.
# Vectors from different models live in different spaces and must never be
# compared against each other, so the label has to say what really produced them.
LOCAL_EMBEDDING_MODEL = "local-hash-v1"
_warned_model_mix: set = set()


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


def item_embedding_text(item: Dict[str, Any]) -> str:
    """The text an item's vector is made from: title, summary and tags as stored."""
    tags = item.get("tech_tags") or []
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except ValueError:
            tags = []
    return f"{item.get('title_l1') or ''} {item.get('summary_l1') or ''} {' '.join(str(t) for t in tags)}"


def clean_embedding_text(text: str) -> str:
    return (text or "").strip()[:8000]


def local_embedding(text: str, dim: int) -> List[float]:
    """Exactly what the local fallback stores for this text, so it can be recognised later."""
    clean_text = clean_embedding_text(text)
    return _deterministic_local_embedding(clean_text, dim) if clean_text else [0.0] * dim


def embeddings_api_url() -> str:
    """OpenAI-compatible embeddings endpoint derived from OPENAI_BASE_URL
    (so Ollama / DeepSeek / proxies work the same way chat completions do)."""
    return f"{settings.OPENAI_BASE_URL.rstrip('/')}/embeddings"


def remote_embedding_model() -> str:
    """Model name sent to the OpenAI-compatible endpoint. embeddinggemma-2 only
    exists on the local Ollama runner, so the cloud fallback uses OpenAI's model."""
    model = settings.EMBEDDING_MODEL
    return "text-embedding-3-small" if model == "embeddinggemma-2" else model


def ollama_embedding_enabled() -> bool:
    """The local Ollama runner is tried first unless OLLAMA_BASE_URL is blank.
    Unit tests (OMNIKEEP_TESTING=1) never reach a real runner on this machine."""
    return bool((settings.OLLAMA_BASE_URL or "").strip()) and os.environ.get("OMNIKEEP_TESTING") != "1"


def _normalized(vec: List[float], dim: int) -> List[float]:
    v = np.array(vec[:dim], dtype=np.float32)
    norm = np.linalg.norm(v)
    if norm > 1e-9:
        v /= norm
    return v.tolist()


async def _ollama_embedding(clean_text: str, dim: int, is_query: bool) -> Optional[List[float]]:
    """embeddinggemma-2 (or EMBEDDING_MODEL) on the local Ollama runner.

    OLLAMA_BASE_URL is the operator's own loopback service, so it does not go
    through public_http_client (that one refuses local addresses by design).
    embeddinggemma uses an asymmetric prompt: queries carry a task prefix,
    documents are embedded as-is. The Matryoshka vector is cut to EMBEDDING_DIM
    and re-normalised.
    """
    prompt_input = f"task: search result | query: {clean_text}" if is_query else clean_text
    url = f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/embed"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
            resp = await client.post(url, json={"model": settings.EMBEDDING_MODEL, "input": prompt_input})
        if resp.status_code == 200:
            embs = resp.json().get("embeddings") or []
            if embs and len(embs[0]) >= dim:
                return _normalized(embs[0], dim)
            logger.debug("[Vector] Ollama returned no usable %s-dim embedding, checking fallback...", dim)
        else:
            logger.debug("[Vector] Ollama embedding returned HTTP %s, checking fallback...", resp.status_code)
    except Exception as e:
        logger.debug(f"[Vector] Local Ollama embedding failed ({e}), checking fallback...")
    return None


async def generate_embedding_with_model(text: str, is_query: bool = False) -> Tuple[List[float], str]:
    """Generates an embedding vector and returns (vector, model_label).

    Tried in order: the local Ollama runner (EMBEDDING_MODEL, e.g. embeddinggemma-2),
    the OpenAI-compatible endpoint at OPENAI_BASE_URL, then the hashed
    bag-of-words fallback. The label is the model that actually produced the
    vector, so vectors from different spaces are never mistaken for each other.
    Indexing and querying both go through here; set is_query for search queries.
    """
    dim = int(settings.EMBEDDING_DIM)
    clean_text = clean_embedding_text(text)
    api_key = settings.OPENAI_API_KEY
    if not clean_text:
        return [0.0] * dim, (settings.EMBEDDING_MODEL if api_key else LOCAL_EMBEDDING_MODEL)

    # 1. Local runner (Ollama, embeddinggemma-2 by default)
    if ollama_embedding_enabled():
        vec = await _ollama_embedding(clean_text, dim, is_query)
        if vec is not None:
            return vec, settings.EMBEDDING_MODEL

    # 2. OpenAI-compatible endpoint
    if api_key and not getattr(settings, "OMNIKEEP_TESTING", False):
        api_url = embeddings_api_url()
        remote_model = remote_embedding_model()
        try:
            from app.network import public_http_client
            async with public_http_client(timeout=15.0) as client:
                resp = await client.post(
                    api_url,
                    headers={"Authorization": f"Bearer {api_key}"},
                    json={
                        "input": clean_text,
                        "model": remote_model,
                        "dimensions": dim
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    vec = data["data"][0]["embedding"]
                    return list(vec[:dim]), remote_model
                logger.warning(
                    "[Vector] Embedding request to %s returned HTTP %s, using local projection: %s",
                    api_url, resp.status_code, (getattr(resp, "text", "") or "")[:200],
                )
        except Exception as e:
            logger.warning(f"[Vector] Embedding request to {api_url} failed ({e}), using local projection.")

    # 3. Deterministic fallback
    return _deterministic_local_embedding(clean_text, dim), LOCAL_EMBEDDING_MODEL


async def generate_embedding(text: str, is_query: bool = False) -> List[float]:
    """Generates an embedding vector for the text (local Ollama, the configured
    OpenAI-compatible endpoint, or the local projection as fallback)."""
    vec, _model = await generate_embedding_with_model(text, is_query=is_query)
    return vec


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
    min_similarity: float = 0.3,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search for items similar to query_vector using sqlite-vec MATCH or numpy fallback.
    With `model`, only vectors labelled with that model are compared: vectors from
    another model live in another space and their similarity means nothing.
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
                # sqlite-vec MATCH query; vec_items has no model column, so with a
                # model filter fetch more neighbours and drop the other models after.
                k = limit * 2 if model is None else limit * 8
                rows = conn.execute("""
                    SELECT item_id, distance
                    FROM vec_items
                    WHERE embedding MATCH ? AND k = ?
                    ORDER BY distance ASC
                """, (packed, k)).fetchall()
                allowed = None
                if model is not None and rows:
                    ids = [r["item_id"] for r in rows]
                    placeholders = ",".join("?" * len(ids))
                    allowed = {
                        r["item_id"] for r in conn.execute(
                            f"SELECT item_id FROM item_embeddings WHERE model = ? AND item_id IN ({placeholders})",
                            (model, *ids),
                        ).fetchall()
                    }
                for r in rows:
                    if allowed is not None and r["item_id"] not in allowed:
                        continue
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
            if model is None:
                cursor = conn.execute("SELECT item_id, embedding, dim FROM item_embeddings")
            else:
                cursor = conn.execute(
                    "SELECT item_id, embedding, dim FROM item_embeddings WHERE model = ?", (model,)
                )
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


def _warn_if_index_model_mismatch(query_model: str) -> None:
    """Log (once per model set) when stored vectors come from a different model
    than the query vector: those rows are in another space and need re-indexing."""
    try:
        with closing(get_db_connection()) as conn:
            rows = conn.execute(
                "SELECT model, COUNT(*) AS n FROM item_embeddings GROUP BY model"
            ).fetchall()
    except Exception:
        return
    others = {r["model"]: r["n"] for r in rows if r["model"] != query_model}
    if not others:
        return
    key = (query_model, tuple(sorted(others)))
    if key in _warned_model_mix:
        return
    _warned_model_mix.add(key)
    logger.warning(
        "[Vector] Query embeddings use model %r but %s stored vector(s) were indexed with %s; "
        "those items will not match semantically until re-indexed.",
        query_model, sum(others.values()), ", ".join(f"{m!r} x{n}" for m, n in others.items()),
    )


def _merge_hybrid_results(
    fts_items: List[Dict[str, Any]],
    q_vec: List[float],
    limit: int = 10,
    vector_weight: float = 0.5,
    model: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion of FTS ranks and vector ranks. An all-zero query
    vector (empty text) carries no meaning, so ranking then falls back to FTS."""
    fts_ranks = {item["id"]: idx + 1 for idx, item in enumerate(fts_items)}
    has_valid_vector = any(v != 0.0 for v in q_vec)

    if has_valid_vector:
        vec_results = search_similar_items(q_vec, limit=limit * 2, min_similarity=0.1, model=model)
        vec_ranks = {r["item_id"]: idx + 1 for idx, r in enumerate(vec_results)}
        vec_sims = {r["item_id"]: r["similarity"] for r in vec_results}
    else:
        vec_ranks = {}
        vec_sims = {}
        vector_weight = 0.0

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


async def search_hybrid(query: str, limit: int = 10, vector_weight: float = 0.5) -> List[Dict[str, Any]]:
    """
    Hybrid Search combining keyword search (FTS) and vector semantic search via Reciprocal Rank Fusion (RRF).
    """
    from app.database import get_items

    # 1. Lexical search (FTS)
    fts_items = get_items(query=query, limit=limit * 2)

    # 2. Vector search: same embedding path as indexing (app.pipeline), so the
    #    query vector is in the same space as the stored item vectors; only
    #    vectors labelled with the query's model are compared.
    q_vec, q_model = await generate_embedding_with_model(query, is_query=True)
    _warn_if_index_model_mismatch(q_model)
    return _merge_hybrid_results(fts_items, q_vec, limit=limit, vector_weight=vector_weight, model=q_model)
