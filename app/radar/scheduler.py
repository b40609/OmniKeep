import asyncio
import html
from contextlib import closing
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from app.config import settings
from app.database import (
    get_all_radar_sources,
    get_db_connection,
    delete_item,
    save_item,
    get_pending_analysis_items,
    update_item_field,
    log_behavior_event,
    get_all_topic_weights,
    get_radar_settings
)
from app.radar.adapters import get_adapter
from app.radar.recommender import score_item_detailed, rank_items_with_exploration
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

def build_weight_index() -> List[tuple]:
    """Keyword index for the pre-gate: only trained (non-default) or muted topics."""
    return [
        (str(r["topic_tag"]).strip().casefold(), float(r["weight"]), bool(r["is_blocked"]))
        for r in get_all_topic_weights()
        if bool(r["is_blocked"]) or abs(float(r["weight"]) - 1.0) > 1e-9
    ]

def pregate_item(title: str, url: str, content: str, weight_index: List[tuple]) -> tuple:
    """Free local gate before any LLM spend.

    A muted-topic keyword hit blocks the item outright (no DB row, no Agnes
    call, no post-hoc delete). Otherwise returns a rough interest score from
    matched weights (same hybrid formula as score_item) — used only to RANK
    candidates for the analysis budget. No tags exist before analysis, so
    this is substring matching over title/URL/content, not score_item.
    """
    text = f"{title} {url} {content[:500]}".casefold()
    matched = []
    for tag, weight, blocked in weight_index:
        if tag and tag in text:
            if blocked:
                return -999.0, True
            matched.append(weight)
    if not matched:
        return 1.0, False
    return round(0.6 * max(matched) + 0.4 * (sum(matched) / len(matched)), 3), False

def _save_deferred_stub(raw) -> str:
    """Persist an unanalyzed radar candidate so nothing is lost to the cap."""
    return save_item({
        "url": raw.url,
        "source_type": raw.source_type,
        "category_name": "Inbox",
        "title_l1": (raw.title or "（待分析）")[:120],
        "summary_l1": "",
        "tech_tags": [],
        "deep_analysis": "",
        "content_raw": (raw.content or "")[:4000],
        "author": raw.author or "",
        "origin": "radar",
        "analysis_status": "pending",
    })

async def _backfill_pending(budget: int) -> List[Dict[str, Any]]:
    """Analyze oldest pending stubs first (cap overflow from earlier cycles)."""
    if budget <= 0:
        return []
    analyzed = []
    for stub in get_pending_analysis_items(budget):
        try:
            item = await _analyze_candidate(stub["url"], tier=2)
            if item:
                analyzed.append(item)
        except Exception as e:
            print(f"[Radar:Scheduler] Backfill failed for {stub['url']}: {e}")
    return analyzed

def _maybe_autostar(item: Dict[str, Any], detail: Dict[str, Any]) -> None:
    """Gate tiering: high-scoring items are bookmarked + behavior-logged."""
    if not settings.RADAR_AUTOSTAR_ENABLED:
        return
    if detail["score"] < settings.RADAR_AUTOSTAR_THRESHOLD:
        return
    update_item_field(item["id"], {"is_starred": 1})
    log_behavior_event("auto_star", item_id=item["id"], source="radar",
                       meta={"score": detail["score"], "reasons": detail["reasons"]})
    item["auto_starred"] = True

async def _analyze_candidate(url: str, tier: int = 2) -> Optional[Dict[str, Any]]:
    """Full two-stage analysis + post-shields + clustering + auto-star."""
    item = await run_pipeline(content_input=url, manual_category=None, origin="radar")
    tags = item.get("tech_tags") or []
    detail = score_item_detailed(tags, tier=tier)
    if detail["blocked"]:
        print(f"[Radar:Recommender] Item blocked by muted tag: {item.get('title_l1')}")
        delete_item(item["id"])
        return None
    event_id = cluster_item_to_event(item)
    item["radar_event_id"] = event_id
    item["radar_score"] = detail["score"]
    item["reasons"] = detail["reasons"]
    _maybe_autostar(item, detail)
    return item

async def _push_autostar_notices(items: List[Dict[str, Any]]) -> None:
    """Best-effort Telegram notice for auto-collected items; silent on failure."""
    starred = [it for it in items if it.get("auto_starred")]
    if not starred:
        return
    try:
        from app.bot.telegram_bot import get_telegram_bot
        bot = get_telegram_bot()
        if not bot:
            return
        lines = []
        for it in starred[:5]:
            reasons = "；".join(str(r) for r in (it.get("reasons") or [])[:2])
            lines.append(f"⭐ <b>{html.escape(it.get('title_l1', '')[:60])}</b>\n{html.escape(reasons)}")
        text = "🤖 <b>雷達自動收藏</b>\n\n" + "\n\n".join(lines)
        for chat_id in settings.telegram_allowed_ids:
            await bot.send_message(chat_id, text)
    except Exception as e:
        print(f"[Radar:AutoStar] Telegram push failed: {e}")


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

    Cost discipline (A-minimal): fetch → local pre-gate → dedupe → rank →
    analyze only the top candidates within the per-cycle LLM budget
    (CondenseIt order: sort → dedupe → limit → summarize). The rest are
    stored as pending stubs and backfilled in later cycles.
    """
    sources = get_all_radar_sources(only_active=True)
    weight_index = build_weight_index()

    # Pass 1 — fetch, pre-gate and dedupe everything locally (zero LLM cost)
    candidates = []
    for src in sources:
        try:
            adapter = get_adapter(src.get("source_type"))
            if not adapter:
                print(f"[Radar:Scheduler] Unknown source type: {src.get('source_type')}")
                continue
            if not is_source_due(src, force=force):
                continue
            raw_items = await adapter.fetch_latest(src)
        except Exception as e:
            print(f"[Radar:Scheduler] Failed to scan source {src.get('name')}: {e}")
            continue
        for raw in raw_items or []:
            with closing(get_db_connection()) as conn:
                row = conn.execute(
                    "SELECT id, analysis_status FROM items WHERE url = ?", (raw.url,)
                ).fetchone()
            if row and row["analysis_status"] != "pending":
                continue  # already ingested; pending stubs wait for backfill
            pg_score, blocked = pregate_item(raw.title, raw.url, raw.content or "", weight_index)
            if blocked:
                print(f"[Radar:Scheduler] Pre-gate dropped (muted topic): {raw.title}")
                if row:
                    delete_item(row["id"])
                continue
            candidates.append((raw, src, pg_score))

    # Load dynamic user settings
    try:
        cfg = get_radar_settings()
    except Exception as e:
        print(f"[Radar:Scheduler] Failed to get settings: {e}")
        cfg = {"max_analyze_per_cycle": 3, "notification_mode": "silent"}

    # Backfill oldest pending stubs first, then spend remaining budget on the
    # best-ranked new candidates
    budget = max(0, int(cfg.get("max_analyze_per_cycle") or settings.RADAR_MAX_ANALYZE_PER_CYCLE))
    all_new_items = await _backfill_pending(budget)
    budget -= len(all_new_items)

    candidates.sort(key=lambda c: c[2], reverse=True)
    deferred_count = 0
    for raw, src, _pg in candidates:
        if budget <= 0:
            _save_deferred_stub(raw)
            deferred_count += 1
            continue
        try:
            item = await _analyze_candidate(raw.url, tier=int(src.get("tier", 2)))
            budget -= 1
            if item:
                all_new_items.append(item)
        except Exception as e:
            print(f"[Radar:Scheduler] Error analyzing {raw.url}: {e}")

    # Rank newly detected items using 80/20 Epsilon-Greedy exploration
    ranked_items = rank_items_with_exploration(all_new_items, exploration_ratio=0.2)

    notification_mode = cfg.get("notification_mode", "silent")
    digest_info = None

    if notification_mode == "daily_digest":
        local_hour = datetime.now().astimezone().hour
        target_hour = int(cfg.get("daily_digest_hour", 8))
        if auto_digest and len(ranked_items) >= 2 and local_hour == target_hour:
            item_ids = [it["id"] for it in ranked_items]
            digest_info = await generate_radar_digest(item_ids, digest_type="daily")
            await _push_digest_to_telegram(digest_info, ranked_items)
    elif notification_mode == "vip_alert":
        vip_threshold = float(cfg.get("vip_threshold", 4.0))
        vip_items = [it for it in ranked_items if float(it.get("radar_score", 0.0)) >= vip_threshold]
        if vip_items:
            await _push_autostar_notices(vip_items)
    elif notification_mode == "legacy" or cfg.get("auto_digest_push") or cfg.get("auto_star_push"):
        if auto_digest and len(ranked_items) >= 2 and cfg.get("auto_digest_push"):
            item_ids = [it["id"] for it in ranked_items]
            local_hour = datetime.now().astimezone().hour
            dtype = "evening" if 17 <= local_hour <= 23 else "morning"
            digest_info = await generate_radar_digest(item_ids, digest_type=dtype)
            await _push_digest_to_telegram(digest_info, ranked_items)
        if cfg.get("auto_star_push"):
            await _push_autostar_notices(ranked_items)
    else:
        # Default 'silent': zero Telegram messages!
        pass

    from app.background import follow_up_pool
    for it in ranked_items:
        follow_up_pool.submit(lambda item=it: _safe_relevance_check(item))

    return {
        "sources_scanned": len(sources),
        "new_items_count": len(all_new_items),
        "new_items": [it["id"] for it in all_new_items],
        "ranked_items": [it["id"] for it in ranked_items],
        "deferred_count": deferred_count,
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
        self._wake_event = asyncio.Event()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running

    def wake(self):
        """Immediately wake up scheduler loop to apply new settings or run cycle."""
        self._wake_event.set()

    def start(self, initial_delay: float = 10.0):
        if self._is_running:
            return
        self._is_running = True
        self._stop_event.clear()
        self._wake_event.clear()
        self._task = asyncio.create_task(self._loop(initial_delay=initial_delay))
        print(f"[Radar:Scheduler] Background scheduler loop started.")

    async def _loop(self, initial_delay: float = 10.0):
        if initial_delay > 0:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=initial_delay)
                return
            except asyncio.TimeoutError:
                pass

        while not self._stop_event.is_set():
            try:
                cfg = get_radar_settings()
            except Exception as e:
                print(f"[Radar:Scheduler] Error loading settings in loop: {e}")
                cfg = {"enabled": True, "interval_minutes": 180, "max_analyze_per_cycle": 3}

            is_enabled = cfg.get("enabled", True)
            interval_minutes = cfg.get("interval_minutes", 180)

            if is_enabled and interval_minutes > 0:
                try:
                    print("[Radar:Scheduler] Starting periodic radar scan cycle...")
                    res = await run_radar_cycle(force=False, auto_digest=True)
                    print(f"[Radar:Scheduler] Cycle complete: {res['new_items_count']} new items detected across {res['sources_scanned']} sources.")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    print(f"[Radar:Scheduler] Error during periodic cycle: {e}")

            # Sleep duration in seconds
            sleep_seconds = float(interval_minutes * 60) if (is_enabled and interval_minutes > 0) else 3600.0

            # Wait until timeout, wake event, or stop event
            self._wake_event.clear()
            stop_task = asyncio.create_task(self._stop_event.wait())
            wake_task = asyncio.create_task(self._wake_event.wait())
            done, pending = await asyncio.wait(
                [stop_task, wake_task],
                timeout=sleep_seconds,
                return_when=asyncio.FIRST_COMPLETED
            )
            for p in pending:
                p.cancel()

            if stop_task in done and self._stop_event.is_set():
                break

    async def stop(self):
        if not self._is_running:
            return
        print("[Radar:Scheduler] Stopping background scheduler...")
        self._stop_event.set()
        self._wake_event.set()
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        self._is_running = False
        print("[Radar:Scheduler] Background scheduler stopped.")

radar_scheduler = RadarScheduler()
