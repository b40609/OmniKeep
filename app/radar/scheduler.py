import asyncio
import html
from contextlib import closing
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.config import settings
from app.database import (
    get_all_radar_sources,
    get_db_connection,
    delete_item
)
from app.radar.adapters import get_adapter
from app.radar.recommender import score_item, rank_items_with_exploration
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

    saved_items = []
    for raw in raw_items:
        # Deduplication check in items table
        with closing(get_db_connection()) as conn:
            existing = conn.execute("SELECT id FROM items WHERE url = ?", (raw.url,)).fetchone()
        if existing:
            continue

        # Ingest and run two-stage analysis
        try:
            print(f"[Radar:Scheduler] Ingesting new item from {source['name']}: {raw.title}")
            item = await run_pipeline(content_input=raw.url, manual_category=None, origin="radar")
            
            # Check recommender score
            tags = item.get("tech_tags") or []
            score, is_blocked = score_item(tags, tier=source.get("tier", 2))
            
            if is_blocked:
                print(f"[Radar:Recommender] Item blocked by muted tag: {raw.title}")
                # Remove from inbox / database to prevent pollution
                delete_item(item["id"])
                continue

            # Cluster into events
            event_id = cluster_item_to_event(item)
            item["radar_event_id"] = event_id
            item["radar_score"] = score
            saved_items.append(item)
        except Exception as e:
            print(f"[Radar:Scheduler] Error analyzing {raw.url}: {e}")

    return saved_items

async def _safe_relevance_check(item: Dict[str, Any]) -> None:
    try:
        from app.watch.relevance import maybe_propose_for_item
        proposal = await maybe_propose_for_item(item)
        if proposal:
            print(f"[Radar:Relevance] Proposal created: {proposal['id']} for item {item.get('id')}")
    except Exception as e:
        print(f"[Radar:Relevance] Check failed for {item.get('id')}: {e}")


async def _push_digest_to_telegram(digest_info: Dict[str, Any], ranked_items: List[Dict[str, Any]]) -> None:
    """Deliver a compact digest to the owner's Telegram (best effort, silent on failure)."""
    try:
        if not digest_info or not digest_info.get("success"):
            return
        from app.bot.telegram_bot import get_telegram_bot
        bot = get_telegram_bot()
        if not bot:
            return
        titles = "\n".join(f"• {html.escape(it.get('title_l1', '')[:60])}" for it in ranked_items[:5])
        text = (
            f"📰 <b>{html.escape(digest_info.get('title', '雷達摘要'))}</b>\n\n{titles}\n\n"
            f"<i>完整摘要在工作台；滑卡請用 /deck。</i>"
        )
        for chat_id in settings.telegram_allowed_ids:
            await bot.send_message(chat_id, text)
    except Exception as e:
        print(f"[Radar:DigestPush] Telegram push failed: {e}")


async def run_radar_cycle(force: bool = False, auto_digest: bool = True) -> Dict[str, Any]:
    """
    Executes a radar scan across all active sources.
    Uses 80/20 algorithm to rank high-potential items into the review queue.
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

    # Rank newly detected items using 80/20 Epsilon-Greedy exploration
    ranked_items = rank_items_with_exploration(all_new_items, exploration_ratio=0.2)

    digest_info = None
    if auto_digest and len(ranked_items) >= 2:
        # Debounce and compile batched digest using top ranked items
        item_ids = [it["id"] for it in ranked_items]
        local_hour = datetime.now().astimezone().hour
        dtype = "evening" if 17 <= local_hour <= 23 else "morning"
        digest_info = await generate_radar_digest(item_ids, digest_type=dtype)
        await _push_digest_to_telegram(digest_info, ranked_items)

    from app.background import follow_up_pool
    for it in ranked_items:
        follow_up_pool.submit(lambda item=it: _safe_relevance_check(item))

    return {
        "sources_scanned": len(sources),
        "new_items_count": len(all_new_items),
        "new_items": [it["id"] for it in all_new_items],
        "ranked_items": [it["id"] for it in ranked_items],
        "digest": digest_info
    }

class RadarScheduler:
    """
    Background daemon scheduler for adaptive periodic radar scans.
    Runs inside the FastAPI lifespan context.
    """
    def __init__(self):
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self, initial_delay: float = 10.0):
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(initial_delay=initial_delay))
        print(f"[Radar:Scheduler] Background scheduler loop started (interval={settings.RADAR_INTERVAL_SECONDS}s).")

    async def _loop(self, initial_delay: float = 10.0):
        if initial_delay > 0:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=initial_delay)
                return
            except asyncio.TimeoutError:
                pass

        while not self._stop_event.is_set():
            try:
                print("[Radar:Scheduler] Starting periodic radar scan cycle...")
                res = await run_radar_cycle(force=False, auto_digest=True)
                print(f"[Radar:Scheduler] Cycle complete: {res['new_items_count']} new items detected across {res['sources_scanned']} sources.")
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Radar:Scheduler] Error during periodic cycle: {e}")

            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=float(settings.RADAR_INTERVAL_SECONDS)
                )
                break
            except asyncio.TimeoutError:
                continue

    async def stop(self):
        if not self._is_running:
            return
        print("[Radar:Scheduler] Stopping background scheduler...")
        self._stop_event.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._is_running = False
        print("[Radar:Scheduler] Background scheduler stopped.")

radar_scheduler = RadarScheduler()
