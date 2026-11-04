"""Audit and rebuild the stored item vectors (item_embeddings, mirrored into vec_items).

Until a7954f4 a vector made by the local hashed fallback was stored under
EMBEDDING_MODEL's name, so a "text-embedding-3-small" row may really be local-hash-v1,
which a remote query vector can never match. Local vectors are deterministic:
recomputing one from the item's text and getting the same numbers proves where a
row came from, without calling any API.
"""
from collections import Counter
from contextlib import closing
from typing import Any, Dict, List

import numpy as np

from app.config import settings
from app.database import get_db_connection, get_item_by_id
from app.vector import (
    LOCAL_EMBEDDING_MODEL,
    generate_embedding_with_model,
    item_embedding_text,
    load_vec_extension,
    local_embedding,
    ollama_embedding_enabled,
    remote_embedding_model,
    store_item_embedding,
)

# Re-embedding stops after this many fallbacks in a row: the endpoint is down, and
# overwriting rows with more local vectors would not help.
MAX_FALLBACKS_IN_A_ROW = 3


def target_model() -> str:
    """The model queries embed with when every configured service is up, so the
    one the index has to hold: the local Ollama runner first, then the
    OpenAI-compatible endpoint, then the local hash."""
    if ollama_embedding_enabled():
        return settings.EMBEDDING_MODEL
    return remote_embedding_model() if settings.OPENAI_API_KEY else LOCAL_EMBEDDING_MODEL


def audit_embeddings() -> Dict[str, Any]:
    """Read-only report of what the index holds and which rows are wrong for the target."""
    dim = int(settings.EMBEDDING_DIM)
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
