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
import time
from contextlib import closing
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple

import numpy as np

from app import ai_status
from app.config import settings
from app.database import get_db_connection, get_item_by_id

logger = logging.getLogger("omnikeep.vector")

_SQLITE_VEC_AVAILABLE: Optional[bool] = None

# Model label recorded for vectors produced by the hashed bag-of-words fallback.
# Vectors from different models live in different spaces and must never be
# compared against each other, so the label has to say what really produced them.
LOCAL_EMBEDDING_MODEL = "local-hash-v1"
# Seconds the local runner gets for one embedding. It has to cover loading the model:
# a first load took 14 s on a machine where later ones took 2 s, and with the earlier
# 10 s limit the request was dropped and the model never got loaded.
OLLAMA_EMBED_TIMEOUT = 30.0
# A repeated warning is logged again after this many seconds, not once per process:
# "semantic search is off" has to stay visible in the log for as long as it is true.
WARN_AGAIN_AFTER = 600.0
_last_warned: Dict[Any, float] = {}


def _warn_now_and_then(key: Any, message: str, *args: Any) -> None:
    now = time.monotonic()
    if now - _last_warned.get(key, -WARN_AGAIN_AFTER) < WARN_AGAIN_AFTER:
        return
    _last_warned[key] = now
    logger.warning(message, *args)


class HybridResults(list):
    """The items of search_hybrid, plus `semantic`: what the vector side did for this
    query (see semantic_state). A plain list to every caller that only wants the items."""
    semantic: Dict[str, Any] = {}


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


async def _ollama_embedding(clean_text: str, dim: int, is_query: bool, base_url: Optional[str] = None,
                            model: Optional[str] = None, status_key: str = "ollama",
                            label: str = "") -> Optional[List[float]]:
    """embeddinggemma-2 (or EMBEDDING_MODEL) on the local Ollama runner.

    The runner is the operator's own loopback service, so it does not go
    through public_http_client (that one refuses local addresses by design).
    embeddinggemma uses an asymmetric prompt: queries carry a task prefix,
    documents are embedded as-is. The Matryoshka vector is cut to EMBEDDING_DIM
    and re-normalised. Without arguments: OLLAMA_BASE_URL and EMBEDDING_MODEL.
    """
    base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
    model = model or settings.EMBEDDING_MODEL
    prompt_input = f"task: search result | query: {clean_text}" if is_query else clean_text
    url = f"{base_url}/api/embed"
    try:
        import httpx
        async with httpx.AsyncClient(timeout=OLLAMA_EMBED_TIMEOUT, trust_env=False) as client:
            resp = await client.post(url, json={"model": model, "input": prompt_input})
        if resp.status_code == 200:
            embs = resp.json().get("embeddings") or []
            if embs and len(embs[0]) >= dim:
                ai_status.record_success(status_key, label)
                return _normalized(embs[0], dim)
            ai_status.record_failure(status_key, 200, f"{model} 沒有回傳 {dim} 維以上的向量", label)
            failure = f"no usable {dim}-dim vector in the response"
        else:
            ai_status.record_failure(status_key, resp.status_code, (resp.text or "")[:200], label)
            failure = f"HTTP {resp.status_code}"
    except Exception as e:
        ai_status.record_failure(status_key, None, f"連不上 {base_url}（{type(e).__name__}）", label)
        failure = type(e).__name__
    # Not at debug level: with this failing, nothing is indexed and questions lose their
    # semantic side, and the service log is where that gets looked up afterwards.
    _warn_now_and_then(("ollama-embedding", base_url, model, failure),
                       "[Vector] %s on the local runner at %s gave no embedding (%s).", model, base_url, failure)
    return None


async def _remote_embedding(clean_text: str, dim: int, api_url: str, api_key: str, model: str,
                            status_key: str = "embeddings", label: str = "") -> Optional[List[float]]:
    """One OpenAI-compatible /embeddings request (public addresses only)."""
    try:
        from app.network import public_http_client
        async with public_http_client(timeout=15.0) as client:
            resp = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "input": clean_text,
                    "model": model,
                    "dimensions": dim
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                vec = data["data"][0]["embedding"]
                ai_status.record_success(status_key, label)
                return list(vec[:dim])
            body = (getattr(resp, "text", "") or "")[:200]
            ai_status.record_failure(status_key, resp.status_code, body, label)
            logger.warning(
                "[Vector] Embedding request to %s returned HTTP %s, using the next fallback: %s",
                api_url, resp.status_code, body,
            )
    except Exception as e:
        ai_status.record_failure(status_key, None, f"{type(e).__name__}: {e}", label)
        logger.warning(f"[Vector] Embedding request to {api_url} failed ({e}), using the next fallback.")
    return None


def embedding_slot() -> List[Tuple[Any, str]]:
    """(connection, model) pairs of the embeddings slot (設定 › AI 服務商); empty = the older settings."""
    try:
        from app.ai_connections import resolve
        return resolve("embeddings")
    except Exception:
        return []


def _usable_entries(entries: List[Tuple[Any, str]]) -> List[Tuple[Any, str]]:
    """Unit tests (OMNIKEEP_TESTING=1) never reach a real Ollama runner on this machine."""
    testing = os.environ.get("OMNIKEEP_TESTING") == "1"
    return [(conn, model) for conn, model in entries
            if conn.kind == "openai" or (conn.kind == "ollama" and not testing)]


def target_embedding_model() -> str:
    """The model queries embed with when every configured service is up."""
    entries = embedding_slot()
    if entries:
        usable = _usable_entries(entries)
        return usable[0][1] if usable else LOCAL_EMBEDDING_MODEL
    if ollama_embedding_enabled():
        return settings.EMBEDDING_MODEL
    return remote_embedding_model() if settings.OPENAI_API_KEY else LOCAL_EMBEDDING_MODEL


async def generate_embedding_with_model(text: str, is_query: bool = False) -> Tuple[List[float], str]:
    """Generates an embedding vector and returns (vector, model_label).

    With connections in the embeddings slot, they are tried in order. Otherwise
    the older order: the local Ollama runner (EMBEDDING_MODEL, e.g. embeddinggemma-2),
    the OpenAI-compatible endpoint at OPENAI_BASE_URL. Then the hashed
    bag-of-words fallback. The label is the model that actually produced the
    vector, so vectors from different spaces are never mistaken for each other.
    Indexing and querying both go through here; set is_query for search queries.
    """
    dim = int(settings.EMBEDDING_DIM)
    clean_text = clean_embedding_text(text)
    entries = embedding_slot()
    if entries:
        if not clean_text:
            usable = _usable_entries(entries)
            return [0.0] * dim, (usable[0][1] if usable else LOCAL_EMBEDDING_MODEL)
        for conn, model in _usable_entries(entries):
            if conn.kind == "ollama":
                vec = await _ollama_embedding(clean_text, dim, is_query, conn.base_url, model,
                                              conn.status_key, conn.label)
            else:
                vec = await _remote_embedding(clean_text, dim, f"{conn.base_url.rstrip('/')}/embeddings",
                                              conn.key or "dummy-key", model, conn.status_key, conn.label)
            if vec is not None:
                return vec, model
        return _deterministic_local_embedding(clean_text, dim), LOCAL_EMBEDDING_MODEL

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
        remote_model = remote_embedding_model()
        vec = await _remote_embedding(clean_text, dim, embeddings_api_url(), api_key, remote_model)
        if vec is not None:
            return vec, remote_model

    # 3. Deterministic fallback
    return _deterministic_local_embedding(clean_text, dim), LOCAL_EMBEDDING_MODEL


async def generate_embedding(text: str, is_query: bool = False) -> List[float]:
    """Generates an embedding vector for the text (local Ollama, the configured
    OpenAI-compatible endpoint, or the local projection as fallback)."""
    vec, _model = await generate_embedding_with_model(text, is_query=is_query)
    return vec


def store_item_embedding(item_id: str, embedding: List[float], model: str = "") -> bool:
    """Stores the embedding vector into both the fallback table and sqlite-vec table.

    Returns False, storing nothing, for a hashed stand-in vector while a real model is
    configured (the runner was down or slow when the item was saved). Such a vector
    matches no query made by the real model, and a query that falls back the same way
    would be compared with those few rows only. The item keeps whatever vector it had
    and app.reindex.backfill_pending embeds it once the model answers again."""
    if model == LOCAL_EMBEDDING_MODEL and target_embedding_model() != LOCAL_EMBEDDING_MODEL:
        _warn_now_and_then(
            ("deferred-index", target_embedding_model()),
            "[Vector] %s did not answer, so new items are saved without a vector for now "
            "(keyword search finds them); they are indexed once it is back.", target_embedding_model())
        return False
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


def delete_item_embeddings(conn, item_ids: List[str], has_vec: bool) -> int:
    """Remove the stored vectors of these items on `conn` (the caller commits); returns how
    many item_embeddings rows went. `has_vec` is load_vec_extension(conn), called before
    any transaction was opened: the sqlite-vec mirror is only reachable with the extension
    loaded, and where it cannot load there is no mirror to clean."""
    removed = 0
    for item_id in item_ids:
        try:
            removed += conn.execute("DELETE FROM item_embeddings WHERE item_id = ?", (item_id,)).rowcount
        except Exception as e:  # no such table: nothing was ever indexed in this database
            logger.debug(f"[Vector] Could not delete from item_embeddings: {e}")
        if has_vec:
            try:
                conn.execute("DELETE FROM vec_items WHERE item_id = ?", (item_id,))
            except Exception as e:
                logger.debug(f"[Vector] Could not delete from vec_items: {e}")
    return removed


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
    Returns: list of dicts with item_id, similarity (cosine, 4 decimals) and distance
    (1 - similarity), best first; both paths give the same numbers for the same vectors.
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
                # vec_items was created without distance_metric, so `distance` (and the
                # neighbour order) is L2. The similarity comes from vec_distance_cosine on
                # each neighbour instead: 1 - L2 is not a cosine, and stored vectors are
                # not always unit length (a remote endpoint's vector is kept as returned).
                rows = conn.execute("""
                    SELECT item_id, vec_distance_cosine(embedding, ?) AS cosine_distance
                    FROM vec_items
                    WHERE embedding MATCH ? AND k = ?
                    ORDER BY distance ASC
                """, (packed, packed, k)).fetchall()
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
                    # NULL for a zero vector, which cosine_similarity() scores 0.0 as well.
                    cosine_distance = r["cosine_distance"]
                    sim = 0.0 if cosine_distance is None else max(-1.0, min(1.0, 1.0 - float(cosine_distance)))
                    if sim >= min_similarity:
                        results.append({
                            "item_id": r["item_id"],
                            "similarity": round(sim, 4),
                            "distance": round(1.0 - sim, 4)
                        })
                # L2 order and cosine order differ for vectors that are not unit length.
                results.sort(key=lambda x: x["similarity"], reverse=True)
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


def index_model_counts() -> Dict[str, int]:
    """How many stored vectors each model made."""
    try:
        with closing(get_db_connection()) as conn:
            rows = conn.execute("SELECT model, COUNT(*) AS n FROM item_embeddings GROUP BY model").fetchall()
    except Exception:  # no such table: nothing was ever indexed in this database
        return {}
    return {r["model"]: r["n"] for r in rows}


def semantic_state(query_model: str) -> Dict[str, Any]:
    """What the vector side can do for a query embedded by `query_model`.

    state        "ok": every stored vector is from the query's model.
                 "partial": most are; `not_indexed` rows from other models cannot match.
                 "empty": nothing is indexed yet.
                 "unavailable": the vector side must not be used for this query.
    reason       why it is unavailable: "embedding_unreachable" when a real model is
                 configured but the query only got the hashed stand-in, "model_mismatch"
                 when most of the index was made by another model than the query.
    query_model, index_model (the one most vectors are from), indexed, not_indexed.

    Vectors of two models are in unrelated spaces. Comparing the query with the handful
    of rows that happen to share its model returns whatever is least far among them,
    which reads as a confident citation of something irrelevant; so the minority side
    never answers."""
    counts = index_model_counts()
    mine = counts.get(query_model, 0)
    total = sum(counts.values())
    index_model = max(counts, key=lambda m: counts[m]) if counts else ""
    state, reason = "ok", ""
    if query_model == LOCAL_EMBEDDING_MODEL and target_embedding_model() != LOCAL_EMBEDDING_MODEL:
        state, reason = "unavailable", "embedding_unreachable"
    elif not total:
        state = "empty"
    elif mine < counts[index_model]:
        state, reason = "unavailable", "model_mismatch"
    elif mine < total:
        state = "partial"
    return {"state": state, "reason": reason, "query_model": query_model, "index_model": index_model,
            "indexed": mine, "not_indexed": total - mine}


def _warn_about_semantic_state(semantic: Dict[str, Any]) -> None:
    """Log when stored vectors come from another model than the query vector: those
    rows are in another space and need re-indexing."""
    if not semantic["not_indexed"]:
        return
    counts = index_model_counts()
    others = {m: n for m, n in counts.items() if m != semantic["query_model"]}
    skipped = " Semantic search is skipped for this query; only keywords are used." \
        if semantic["state"] == "unavailable" else ""
    _warn_now_and_then(
        ("model-mix", semantic["query_model"], tuple(sorted(others)), semantic["state"]),
        "[Vector] Query embeddings use model %r but %s stored vector(s) were indexed with %s; "
        "those items will not match semantically until re-indexed.%s",
        semantic["query_model"], sum(others.values()), ", ".join(f"{m!r} x{n}" for m, n in others.items()),
        skipped,
    )


# Categories whose items were set aside as junk; the taste profile and the tool
# resolver already leave them out (app.database, app.pipeline).
QUARANTINE_CATEGORIES = frozenset({"隔離區"})


def unusable_for_answers(item: Dict[str, Any]) -> bool:
    """An item with nothing to cite: its fetch failed and no analysis was made, it is a
    stub still waiting for analysis, or it sits in a quarantine category. Such items
    still show in the item list and the search box; they are only kept out of answers."""
    from app.pipeline import FETCH_FAILED_TAG
    return (FETCH_FAILED_TAG in (item.get("summary_l1") or "")
            or item.get("analysis_status") == "pending"
            or item.get("category_name") in QUARANTINE_CATEGORIES)


def _merge_hybrid_results(
    fts_items: List[Dict[str, Any]],
    q_vec: List[float],
    limit: int = 10,
    vector_weight: float = 0.5,
    model: Optional[str] = None,
    usable_only: bool = False,
) -> List[Dict[str, Any]]:
    """Reciprocal Rank Fusion of FTS ranks and vector ranks. An all-zero query
    vector (empty text) carries no meaning, so ranking then falls back to FTS.
    usable_only leaves out items with nothing to cite (unusable_for_answers)."""
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
        if not item or (usable_only and unusable_for_answers(item)):
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


async def search_hybrid(query: str, limit: int = 10, vector_weight: float = 0.5,
                        usable_only: bool = False) -> HybridResults:
    """
    Hybrid Search combining keyword search (FTS) and vector semantic search via Reciprocal Rank Fusion (RRF).
    The result is a list of items; its `semantic` attribute says what the vector side
    did (semantic_state), so a caller can tell the person when it was left out.
    usable_only: for answers and citations, leave out items with nothing to cite.
    """
    from app.database import search_candidates

    # 1. Lexical search. search_candidates returns matches best first (every word, then the
    #    terms of a query typed as a sentence, then any word), and that order is the lexical
    #    rank fused below.
    fts_items = search_candidates(query, limit=limit * 2)

    # 2. Vector search: same embedding path as indexing (app.pipeline), so the
    #    query vector is in the same space as the stored item vectors; only
    #    vectors labelled with the query's model are compared, and only when that
    #    model made most of the index.
    q_vec, q_model = await generate_embedding_with_model(query, is_query=True)
    semantic = semantic_state(q_model)
    _warn_about_semantic_state(semantic)
    if semantic["state"] == "unavailable":
        q_vec = [0.0] * len(q_vec)  # an all-zero query vector ranks by the lexical side alone
    results = HybridResults(
        _merge_hybrid_results(fts_items, q_vec, limit=limit, vector_weight=vector_weight, model=q_model,
                              usable_only=usable_only))
    results.semantic = semantic
    return results
