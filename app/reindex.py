"""Audit and rebuild the stored item vectors (item_embeddings, mirrored into vec_items).

Until a7954f4 a vector made by the local hashed fallback was stored under
EMBEDDING_MODEL's name, so a "text-embedding-3-small" row may really be local-hash-v1,
which a remote query vector can never match. Local vectors are deterministic:
recomputing one from the item's text and getting the same numbers proves where a
row came from, without calling any API.
"""
import asyncio
import logging
from collections import Counter
from contextlib import closing
from typing import Any, Dict, List

import numpy as np

from app.config import settings
from app.database import get_db_connection, get_item_by_id
from app.vector import (
    LOCAL_EMBEDDING_MODEL,
    delete_item_embeddings,
    embedding_dim,
    generate_embedding_with_model,
    item_embedding_text,
    load_vec_extension,
    local_embedding,
    ollama_embedding_enabled,
    remote_embedding_model,
    store_item_embedding,
)

logger = logging.getLogger("omnikeep.reindex")

# Re-embedding stops after this many fallbacks in a row: the endpoint is down, and
# overwriting rows with more local vectors would not help.
MAX_FALLBACKS_IN_A_ROW = 3
# The background backfill: how often it looks, and how many items it embeds per look.
BACKFILL_TICK_SECONDS = 600
BACKFILL_BATCH = 50
SELF_HOSTED_BATCH = 100000


def target_model() -> str:
    """The model queries embed with when every configured service is up, so the
    one the index has to hold: the local Ollama runner first, then the
    OpenAI-compatible endpoint, then the local hash."""
    from app.vector import embedding_slot, target_embedding_model
    if embedding_slot():
        return target_embedding_model()
    if ollama_embedding_enabled():
        return settings.EMBEDDING_MODEL
    return remote_embedding_model() if settings.OPENAI_API_KEY else LOCAL_EMBEDDING_MODEL


def audit_embeddings() -> Dict[str, Any]:
    """Read-only report of what the index holds and which rows are wrong for the target."""
    dim = embedding_dim()
    target = target_model()
    with closing(get_db_connection()) as conn:
        items = {r["id"]: dict(r) for r in conn.execute(
            "SELECT id, title_l1, summary_l1, tech_tags, analysis_status FROM items")}
        rows = conn.execute("SELECT item_id, embedding, dim, model FROM item_embeddings").fetchall()
        vec_rows = None
        if load_vec_extension(conn):
            try:
                vec_rows = conn.execute("SELECT COUNT(*) FROM vec_items").fetchone()[0]
            except Exception:
                pass

    report: Dict[str, Any] = {
        "target_model": target, "dim": dim, "items": len(items), "rows": len(rows), "vec_rows": vec_rows,
        "labels": Counter(), "actual": Counter(),
        "mislabeled_local": [], "stale": [], "dim_mismatch": [], "orphans": [], "missing": [],
        "indexed": [],  # every vector that belongs to an existing item (for a full rebuild)
    }
    indexed = set()
    for row in rows:
        item_id = row["item_id"]
        indexed.add(item_id)
        report["labels"][row["model"]] += 1
        item = items.get(item_id)
        if item is None:
            report["orphans"].append(item_id)
            continue
        report["indexed"].append(item_id)
        if row["dim"] != dim:
            report["dim_mismatch"].append(item_id)
            report["stale"].append(item_id)
            continue
        stored = np.frombuffer(row["embedding"], dtype=np.float32)
        expected = np.asarray(local_embedding(item_embedding_text(item), dim), dtype=np.float32)
        proven_local = stored.shape == expected.shape and np.allclose(stored, expected, atol=1e-6)
        actual = LOCAL_EMBEDDING_MODEL if proven_local or row["model"] == LOCAL_EMBEDDING_MODEL else row["model"]
        report["actual"][actual] += 1
        if proven_local and row["model"] != LOCAL_EMBEDDING_MODEL:
            report["mislabeled_local"].append(item_id)
        if actual != target:
            report["stale"].append(item_id)
    # Radar stubs awaiting analysis are indexed once analysed, like any new item.
    report["missing"] = [i for i, item in items.items()
                         if i not in indexed and item["analysis_status"] != "pending"]
    return report


def relabel_proven_local(item_ids: List[str]) -> int:
    """Give rows proven to be local vectors their true label; the vectors stay as they are."""
    with closing(get_db_connection()) as conn, conn:
        return sum(conn.execute("UPDATE item_embeddings SET model = ? WHERE item_id = ?",
                                (LOCAL_EMBEDDING_MODEL, item_id)).rowcount for item_id in item_ids)


def orphan_vector_ids() -> List[str]:
    """Ids with a vector in item_embeddings or in the sqlite-vec mirror but no item."""
    with closing(get_db_connection()) as conn:
        ids = {r["item_id"] for r in conn.execute(
            "SELECT item_id FROM item_embeddings WHERE item_id NOT IN (SELECT id FROM items)")}
        if load_vec_extension(conn):
            try:
                ids |= {r["item_id"] for r in conn.execute(
                    "SELECT item_id FROM vec_items WHERE item_id NOT IN (SELECT id FROM items)")}
            except Exception:
                pass
    return sorted(ids)


def delete_orphan_vectors() -> int:
    """Remove the vectors of items that no longer exist; returns how many ids were cleaned."""
    orphans = orphan_vector_ids()
    if orphans:
        with closing(get_db_connection()) as conn, conn:
            delete_item_embeddings(conn, orphans, load_vec_extension(conn))
    return len(orphans)


async def reembed(item_ids: List[str], progress=lambda done, total: None) -> Dict[str, Any]:
    """Re-embed with the current configuration. A row is only overwritten by a vector
    from the target model; a fallback vector is discarded instead."""
    target = target_model()
    result: Dict[str, Any] = {"reembedded": 0, "fell_back": 0, "stopped": None}
    in_a_row = 0
    for done, item_id in enumerate(item_ids, 1):
        item = get_item_by_id(item_id)
        if item is None:
            continue
        vec, model = await generate_embedding_with_model(item_embedding_text(item))
        if model != target:
            result["fell_back"] += 1
            in_a_row += 1
            if in_a_row >= MAX_FALLBACKS_IN_A_ROW:
                result["stopped"] = f"{in_a_row} fallbacks in a row; is the embeddings endpoint reachable?"
                break
            continue
        in_a_row = 0
        store_item_embedding(item_id, vec, model=model)
        result["reembedded"] += 1
        progress(done, len(item_ids))
    return result


def target_is_self_hosted() -> bool:
    """Whether the target model runs on the operator's own Ollama runner: re-embedding
    with it costs nothing per item."""
    from app.vector import embedding_slot, _usable_entries
    entries = embedding_slot()
    if entries:
        usable = _usable_entries(entries)
        return bool(usable) and usable[0][0].kind == "ollama"
    return ollama_embedding_enabled()


def pending_item_ids(limit: int = BACKFILL_BATCH) -> List[str]:
    """Analysed items the configured model has yet to embed, newest first: the ones saved
    without a vector while it was down (app.vector.store_item_embedding), and the ones that only
    hold the hashed stand-in from before that rule. Empty when the hashed vectors are the
    configured choice. With a self-hosted model, rows made by another model count too, so
    switching the local model (setup picks one per machine) re-indexes on its own. With a
    cloud endpoint those are left to scripts/rebuild_embeddings.py: re-embedding everything
    is paid for per item there."""
    target = target_model()
    if target == LOCAL_EMBEDDING_MODEL:
        return []
    other_models = target_is_self_hosted()
    with closing(get_db_connection()) as conn:
        try:
            rows = conn.execute(
                """SELECT i.id FROM items i LEFT JOIN item_embeddings e ON e.item_id = i.id
                   WHERE COALESCE(i.analysis_status, '') != 'pending'
                     AND (e.item_id IS NULL OR e.model = ? OR (? AND e.model != ?))
                   ORDER BY i.created_at DESC LIMIT ?""",
                (LOCAL_EMBEDDING_MODEL, int(other_models), target, limit)).fetchall()
        except Exception:  # no item_embeddings table yet: nothing has been indexed here
            return []
    return [r["id"] for r in rows]


async def backfill_pending(limit: int = BACKFILL_BATCH) -> Dict[str, Any]:
    """Embed up to `limit` pending items with the configured model. A vector is only
    written when that model made it, so running this while it is still down changes nothing.
    A self-hosted model works through everything pending in one go (a model switch is a
    few minutes of local work), after vec_items is made again at the new width."""
    if target_is_self_hosted():
        limit = max(limit, SELF_HOSTED_BATCH)
    item_ids = pending_item_ids(limit)
    if not item_ids:
        return {"pending": 0, "reembedded": 0, "fell_back": 0, "stopped": None}
    from app.vector import init_vector_db
    init_vector_db()
    return {"pending": len(item_ids), **(await reembed(item_ids))}


async def backfill_loop(tick_seconds: int = BACKFILL_TICK_SECONDS, initial_delay: float = 90.0) -> None:
    await asyncio.sleep(initial_delay)
    while True:
        try:
            stats = await backfill_pending()
            if stats["reembedded"]:
                logger.info("[Reindex] Embedded %s item(s) that were waiting for the embedding model", stats["reembedded"])
        except Exception as exc:
            logger.error("[Reindex] backfill tick failed (%s)", type(exc).__name__)
        await asyncio.sleep(tick_seconds)
