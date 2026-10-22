import asyncio
from datetime import datetime, timezone
from typing import List, Dict, Any
from app.database import (
    get_all_radar_sources,
    get_db_connection
)
from app.radar.adapters import get_adapter
from app.radar.recommender import score_item
from app.radar.clustering import cluster_item_to_event
from app.radar.digest import generate_radar_digest
from app.pipeline import run_pipeline

def is_source_due(source: Dict[str, Any], force: bool = False) -> bool:
    if force:
        return True
    
    last_fetched_iso = source.get("last_fetched_at")
    if not last_fetched_iso:
        return True

    now = datetime.now(timezone.utc)
    try:
        last_dt = datetime.fromisoformat(last_fetched_iso.replace("Z", "+00:00"))
        minutes_passed = (now - last_dt).total_seconds() / 60.0
    except Exception:
        return True

    # Check if currently inside the source's learned Hot Window (Local Time)
    local_hour = datetime.now().astimezone().hour
    hot_hours = source.get("hot_hours") or []

    if local_hour in hot_hours:
        # Hot Window: High-frequency adaptive probe every 15 minutes
        return minutes_passed >= 15.0
    else:
        # Off-peak: standard check interval (e.g. 60 - 180 min)
        interval = source.get("check_interval_minutes") or 60
        return minutes_passed >= float(interval)

async def scan_single_source(source: Dict[str, Any], force: bool = False) -> List[Dict[str, Any]]:
    if not is_source_due(source, force=force):
        return []

    source_type = source.get("source_type")
    adapter = get_adapter(source_type)
    if not adapter:
        print(f"[Radar:Scheduler] Unknown source type: {source_type}")
        return []

    raw_items = await adapter.fetch_latest(source)
    if not raw_items:
        return []

    conn = get_db_connection()
    cursor = conn.cursor()

    saved_items = []
    for raw in raw_items:
        # Deduplication check in items table
        cursor.execute("SELECT id FROM items WHERE url = ?", (raw.url,))
        existing = cursor.fetchone()
        if existing:
            continue

        # Ingest and run two-stage analysis
        try:
            print(f"[Radar:Scheduler] Ingesting new item from {source['name']}: {raw.title}")
            item = await run_pipeline(content_input=raw.url, manual_category=None)
            
            # Check recommender score
            tags = item.get("tech_tags") or []
            score, is_blocked = score_item(tags, tier=source.get("tier", 2))
            
            if is_blocked:
                print(f"[Radar:Recommender] Item blocked by muted tag: {raw.title}")
                continue

            # Cluster into events
            event_id = cluster_item_to_event(item)
            item["radar_event_id"] = event_id
            item["radar_score"] = score
            saved_items.append(item)
        except Exception as e:
            print(f"[Radar:Scheduler] Error analyzing {raw.url}: {e}")

    conn.close()
    return saved_items

async def run_radar_cycle(force: bool = False, auto_digest: bool = True) -> Dict[str, Any]:
    """
    Executes a radar scan across all active sources.
    If multiple new items arrive, debounces and generates a synthesized digest.
    """
    sources = get_all_radar_sources(only_active=True)
    all_new_items = []

    for src in sources:
        try:
            new_items = await scan_single_source(src, force=force)
            all_new_items.extend(new_items)
        except Exception as e:
            print(f"[Radar:Scheduler] Failed to scan source {src.get('name')}: {e}")

    digest_info = None
    if auto_digest and len(all_new_items) >= 2:
        # Debounce and compile batched digest
        item_ids = [it["id"] for it in all_new_items]
        local_hour = datetime.now().astimezone().hour
        dtype = "evening" if 17 <= local_hour <= 23 else "morning"
        digest_info = await generate_radar_digest(item_ids, digest_type=dtype)

    return {
        "sources_scanned": len(sources),
        "new_items_count": len(all_new_items),
        "new_items": [it["id"] for it in all_new_items],
        "digest": digest_info
    }
