"""
OmniKeep Vector Embedding Backfill Script.
Batch-processes existing items lacking embeddings using local Ollama (embeddinggemma-2)
and stores them into both item_embeddings (fallback) and vec_items (sqlite-vec).
"""

import sys
import json
import time
import struct
from pathlib import Path
from datetime import datetime, timezone
from typing import List, Dict, Any

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import httpx
import numpy as np

from app.app_settings import apply_overrides
from app.config import settings
from app.database import get_db_connection
from app.vector import load_vec_extension

apply_overrides()  # the Ollama address and model saved in the app win over .env

from app.embedding_profiles import model_dim  # noqa: E402
DIM = model_dim(settings.EMBEDDING_MODEL)
MODEL_NAME = settings.EMBEDDING_MODEL
OLLAMA_URL = getattr(settings, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
BATCH_SIZE = 25


def parse_tags(tags_raw: Any) -> str:
    if not tags_raw:
        return ""
    if isinstance(tags_raw, list):
        return " ".join(tags_raw)
    if isinstance(tags_raw, str):
        try:
            parsed = json.loads(tags_raw)
            if isinstance(parsed, list):
                return " ".join(parsed)
        except Exception:
            pass
        return tags_raw
    return ""


def backfill_embeddings():
    conn = get_db_connection()
    try:
        # 1. Query missing items
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, title_l1, summary_l1, tech_tags 
            FROM items 
            WHERE id NOT IN (SELECT item_id FROM item_embeddings)
            ORDER BY created_at DESC
        """)
        missing_rows = cursor.fetchall()
        total_missing = len(missing_rows)
        print(f"[Backfill] Found {total_missing} items lacking vector embeddings.")

        if total_missing == 0:
            print("[Backfill] All items already have embeddings. 100% coverage achieved!")
            return

        has_vec = load_vec_extension(conn)
        print(f"[Backfill] sqlite-vec extension available on connection: {has_vec}")
        print(f"[Backfill] Target model: {MODEL_NAME} | Dimensions: {DIM} | Batch size: {BATCH_SIZE}")

        total_processed = 0
        t_start = time.time()

        for i in range(0, total_missing, BATCH_SIZE):
            batch = missing_rows[i:i + BATCH_SIZE]
            batch_texts = []
            batch_ids = []

            for row in batch:
                i_id = row["id"]
                t_l1 = row["title_l1"] or ""
                s_l1 = row["summary_l1"] or ""
                tags = parse_tags(row["tech_tags"])
                clean_text = f"{t_l1} {s_l1} {tags}".strip()[:8000]
                if not clean_text:
                    clean_text = "OmniKeep item"
                batch_texts.append(clean_text)
                batch_ids.append(i_id)

            # Call Ollama embed endpoint
            try:
                resp = httpx.post(
                    f"{OLLAMA_URL}/api/embed",
                    json={"model": MODEL_NAME, "input": batch_texts},
                    timeout=60.0
                )
                if resp.status_code != 200:
                    print(f"[Backfill] ⚠️ Ollama API returned error {resp.status_code}: {resp.text}")
                    continue

                embs = resp.json().get("embeddings", [])
                if len(embs) != len(batch_ids):
                    print(f"[Backfill] ⚠️ Mismatch: expected {len(batch_ids)} embeddings, got {len(embs)}")
                    continue

                now_iso = datetime.now(timezone.utc).isoformat()
                fallback_records = []
                vec_records = []

                for item_id, raw_emb in zip(batch_ids, embs):
                    v = np.array(raw_emb[:DIM], dtype=np.float32)
                    norm = np.linalg.norm(v)
                    if norm > 1e-9:
                        v /= norm
                    else:
                        v[0] = 1.0

                    packed = struct.pack(f"{DIM}f", *v.tolist())
                    fallback_records.append((item_id, packed, DIM, MODEL_NAME, now_iso))
                    vec_records.append((item_id, packed))

                # Batch write to item_embeddings
                conn.executemany("""
                    INSERT INTO item_embeddings (item_id, embedding, dim, model, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(item_id) DO UPDATE SET
                        embedding = excluded.embedding,
                        dim = excluded.dim,
                        model = excluded.model,
                        updated_at = excluded.updated_at
                """, fallback_records)

                # Batch write to vec_items if available
                if has_vec:
                    for item_id, packed in vec_records:
                        try:
                            conn.execute("DELETE FROM vec_items WHERE item_id = ?", (item_id,))
                            conn.execute("INSERT INTO vec_items (item_id, embedding) VALUES (?, ?)", (item_id, packed))
                        except Exception as e:
                            pass

                conn.commit()
                total_processed += len(batch_ids)
                progress = (total_processed / total_missing) * 100.0
                elapsed = time.time() - t_start
                rate = total_processed / elapsed if elapsed > 0 else 0
                print(f"[{progress:5.1f}%] Processed {total_processed}/{total_missing} items ({rate:.1f} items/s)...")

            except Exception as e:
                print(f"[Backfill] ❌ Batch failed: {e}")

        total_elapsed = time.time() - t_start
        print(f"\n[Backfill] Finished backfilling {total_processed} items in {total_elapsed:.2f}s!")

        # Verify final count
        cursor.execute("SELECT COUNT(*) FROM items")
        total_items = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM item_embeddings")
        total_embs = cursor.fetchone()[0]
        coverage = (total_embs / total_items) * 100.0 if total_items > 0 else 0
        print(f"[Backfill] Total Items: {total_items} | Total Embeddings: {total_embs} | Coverage: {coverage:.1f}%")

    finally:
        conn.close()


if __name__ == "__main__":
    backfill_embeddings()
