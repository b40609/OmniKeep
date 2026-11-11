import asyncio
import html
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
from app.config import settings
from app.database import (
    get_all_radar_sources,
    delete_item,
    save_item,
    get_pending_analysis_items,
    update_item_field,
    log_behavior_event,
    get_all_topic_weights,
    get_radar_settings,
    get_last_radar_digest_at,
    get_latest_radar_digests,
    get_radar_items_updated_since,
    find_item_by_same_page,
)
from app.url_canon import canonical_url
from app.radar.adapters import get_adapter
from app.radar.recommender import score_item_detailed, rank_items_with_exploration
from app.radar.clustering import cluster_item_to_event
from app.radar.digest import generate_radar_digest
from app.pipeline import run_pipeline
from app.push import send_push

logger = logging.getLogger("omnikeep.radar")

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

def _fold(text: str) -> str:
    """Case and whitespace folded, the form tags and item text are compared in."""
    return " ".join(str(text).split()).casefold()

def build_weight_index() -> List[tuple]:
    """Keyword index for the pre-gate: only trained (non-default) or muted topics."""
    return [
        (_fold(r["topic_tag"]), float(r["weight"]), bool(r["is_blocked"]))
        for r in get_all_topic_weights()
        if bool(r["is_blocked"]) or abs(float(r["weight"]) - 1.0) > 1e-9
    ]

# Scripts written without spaces between words: kana, bopomofo, CJK ideographs, hangul.
_CJK = re.compile(
    "[ᄀ-ᇿ⺀-⿟々-〇぀-ヿ㄀-ㄯㆠ-ㇿ㐀-䶿"
    "一-鿿가-힯豈-﫿ｦ-ﾟ\U00020000-\U000323af]"
)
PREGATE_CONTENT_CHARS = 500  # how much of the content the pre-gate reads after the title
PREGATE_MIN_MUTE_LENGTH = 2  # a one-character muted tag ("c", "r", "車") is left to the tag check after analysis

def _joins_word(ch: str) -> bool:
    """A letter or digit that continues the word next to it (CJK characters stand alone)."""
    return ch.isalnum() and not _CJK.match(ch)

def tag_in_text(tag: str, text: str) -> bool:
    """Whether `tag` appears in `text` as a term of its own (both folded with _fold).

    The characters right before and after the hit must not be letters or digits, so "ai" is
    not found in "openai" or "email", nor "go" in "google". The tag is compared literally,
    symbols included ("c++", "c#", ".net", "node.js"). CJK text has no word boundaries: a CJK
    neighbour never counts as part of the word ("使用ai模型" has "ai"), and where the tag itself
    starts or ends with a CJK character that side needs no boundary, so a Chinese tag is found
    anywhere in the text.
    """
    if not tag:
        return False
    open_start, open_end = bool(_CJK.match(tag[0])), bool(_CJK.match(tag[-1]))
    start = text.find(tag)
    while start != -1:
        end = start + len(tag)
        if ((open_start or start == 0 or not _joins_word(text[start - 1]))
                and (open_end or end == len(text) or not _joins_word(text[end]))):
            return True
        start = text.find(tag, start + 1)
    return False

def _pregate_scan(title: str, content: str, weight_index: List[tuple]) -> tuple:
    """(the muted tag found or None, weights of the other tags found) in the title and the
    opening of the content. The link is not read: host names and paths hold words that say
    nothing about the topic (every Google News link has "google" in it)."""
    text = _fold(f"{title} {content[:PREGATE_CONTENT_CHARS]}")
    matched = []
    for tag, weight, blocked in weight_index:
        if blocked and len(tag) < PREGATE_MIN_MUTE_LENGTH:
            continue
        if not tag_in_text(tag, text):
            continue
        if blocked:
            return tag, []
        matched.append(weight)
    return None, matched

def muted_tag_hit(title: str, content: str, weight_index: List[tuple]) -> Optional[str]:
    """The muted tag (folded) the pre-gate finds in this item, or None."""
    return _pregate_scan(title, content, weight_index)[0]

def pregate_item(title: str, url: str, content: str, weight_index: List[tuple]) -> tuple:
    """Free local gate before any LLM spend.

    A muted-topic hit blocks the item outright (no DB row, no Agnes
    call, no post-hoc delete). Otherwise returns a rough interest score from
    matched weights (same hybrid formula as score_item) — used only to RANK
    candidates for the analysis budget. No tags exist before analysis, so
    this looks for the tags as whole terms (tag_in_text) in the title and the
    opening of the content, not score_item. `url` is not matched.
    """
    hit, matched = _pregate_scan(title, content, weight_index)
    if hit is not None:
        return -999.0, True
    if not matched:
        return 1.0, False
    return round(0.6 * max(matched) + 0.4 * (sum(matched) / len(matched)), 3), False

def _page_key(url: str) -> str:
    """One key per page for a cycle's bookkeeping (the same form the dedupe compares)."""
    return canonical_url(url, repo_level=False)

def _save_deferred_stub(raw) -> str:
    """Persist an unanalyzed radar candidate so nothing is lost to the cap.

    Only a page that is not stored yet gets a stub. save_item() is an upsert: writing a stub
    over an existing row (analyzed, or already waiting) would blank its summary, tags and
    analysis and set it back to pending.
    """
    existing = find_item_by_same_page(raw.url)
    if existing:
        return existing["id"]
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

async def _backfill_pending(budget: int, handled: Optional[set] = None) -> List[Dict[str, Any]]:
    """Analyze oldest pending stubs first (cap overflow from earlier cycles).

    Every page tried here is added to `handled` (see _page_key), whatever came of it
    (analyzed, dropped for a muted tag, failed), so the caller leaves it alone for the
    rest of the cycle.
    """
    if budget <= 0:
        return []
    analyzed = []
    for stub in get_pending_analysis_items(budget):
        if handled is not None:
            key = _page_key(stub["url"])
            if key in handled:
                continue
            handled.add(key)
        try:
            item = await _analyze_candidate(stub["url"], tier=2)
            if item:
                analyzed.append(item)
        except Exception as e:
            logger.warning(f"[Radar:Scheduler] Backfill failed for {stub['url']}: {e}")
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
        logger.info(f"[Radar:Recommender] Item blocked by muted tag: {item.get('title_l1')}")
        delete_item(item["id"])
        return None
    event_id = cluster_item_to_event(item)
    item["radar_event_id"] = event_id
    item["radar_score"] = detail["score"]
    item["reasons"] = detail["reasons"]
    _maybe_autostar(item, detail)
    return item

async def _push_items_to_telegram(items: List[Dict[str, Any]], heading: str) -> None:
    """Best-effort Telegram notice listing up to 5 items with their reasons; silent on failure."""
    if not items:
        return
    try:
        from app.bot.telegram_bot import get_telegram_bot
        bot = get_telegram_bot()
        if not bot:
            return
        lines = []
        for it in items[:5]:
            reasons = "；".join(str(r) for r in (it.get("reasons") or [])[:2])
            lines.append(f"<b>{html.escape(it.get('title_l1', '')[:60])}</b>\n{html.escape(reasons)}")
        text = f"<b>{heading}</b>\n\n" + "\n\n".join(lines)
        for chat_id in settings.telegram_allowed_ids:
            await bot.send_message(chat_id, text)
    except Exception as e:
        logger.warning(f"[Radar:Notify] Telegram push failed: {e}")


async def _push_text_to_line(text: str) -> None:
    """Best-effort LINE push to every allowed user; skipped when LINE is not set up."""
    if not settings.LINE_CHANNEL_ACCESS_TOKEN:
        return
    try:
        from app.bot.line_bot import push_line_messages
    except Exception as e:
        logger.warning(f"[Radar:Notify] LINE bot unavailable: {e}")
        return
    for user_id in settings.line_allowed_ids:
        try:
            # A LINE text message holds at most 5,000 characters.
            await push_line_messages(user_id, [{"type": "text", "text": text[:4900]}])
        except Exception as e:
            logger.warning(f"[Radar:Notify] LINE push failed: {e}")


async def _push_items_to_web(items: List[Dict[str, Any]], title: str, tag: str, bullet: str) -> None:
    if not items:
        return
    try:
        lines = "\n".join(f"{bullet} {it.get('title_l1', '')[:60]}" for it in items[:5])
        await send_push(title, lines, tag=tag)
    except Exception:
        logger.exception("Web Push for radar items failed")


async def _push_items_to_line(items: List[Dict[str, Any]], heading: str, bullet: str) -> None:
    if not items:
        return
    lines = "\n".join(f"{bullet} {it.get('title_l1', '')[:60]}" for it in items[:5])
    await _push_text_to_line(f"{heading}\n\n{lines}")


async def _safe_relevance_check(item: Dict[str, Any]) -> None:
    try:
        from app.watch.relevance import maybe_propose_for_item
        proposal = await maybe_propose_for_item(item)
        if proposal:
            logger.info(f"[Radar:Relevance] Proposal created: {proposal['id']} for item {item.get('id')}")
    except Exception as e:
        logger.warning(f"[Radar:Relevance] Check failed for {item.get('id')}: {e}")


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
            f"<b>{html.escape(digest_info.get('title', '雷達摘要'))}</b>\n\n{titles}\n\n"
            f"<i>完整戰報請至工作台查閱；卡片審閱請輸入 /deck。</i>"
        )
        for chat_id in settings.telegram_allowed_ids:
            await bot.send_message(chat_id, text)
    except Exception as e:
        logger.warning(f"[Radar:DigestPush] Telegram push failed: {e}")


async def _push_digest_to_web(digest_info: Dict[str, Any], ranked_items: List[Dict[str, Any]]) -> None:
    """PWA twin of _push_digest_to_telegram; independent of whether Telegram is set up."""
    if not digest_info or not digest_info.get("success"):
        return
    try:
        titles = "\n".join(f"• {it.get('title_l1', '')[:60]}" for it in ranked_items[:5])
        await send_push(f"📰 {digest_info.get('title', '雷達摘要')}", titles, tag="radar-digest")
    except Exception:
        logger.exception("Web Push for radar digest failed")


async def _push_digest_to_line(digest_info: Dict[str, Any], ranked_items: List[Dict[str, Any]]) -> None:
    if not digest_info or not digest_info.get("success"):
        return
    titles = "\n".join(f"• {it.get('title_l1', '')[:60]}" for it in ranked_items[:5])
    await _push_text_to_line(f"📰 {digest_info.get('title', '雷達摘要')}\n\n{titles}\n\n完整摘要請到 OmniKeep 查看。")


async def _announce_autostar(items: List[Dict[str, Any]]) -> None:
    """Auto-collected items only (legacy auto_star_push)."""
    starred = [it for it in items if it.get("auto_starred")]
    await _push_items_to_telegram(starred, "雷達精選推薦")
    await _push_items_to_web(starred, "🤖 雷達自動收藏", "radar-autostar", "⭐")
    await _push_items_to_line(starred, "🤖 雷達自動收藏", "⭐")


async def _announce_vip(items: List[Dict[str, Any]]) -> None:
    """vip_alert: every item that reached the threshold, whether or not auto-star collected it."""
    await _push_items_to_telegram(items, "雷達重要項目")
    await _push_items_to_web(items, "🔔 雷達重要項目", "radar-vip", "•")
    await _push_items_to_line(items, "🔔 雷達重要項目", "•")


async def _announce_digest(digest_info: Dict[str, Any], ranked_items: List[Dict[str, Any]]) -> None:
    await _push_digest_to_telegram(digest_info, ranked_items)
    await _push_digest_to_web(digest_info, ranked_items)
    await _push_digest_to_line(digest_info, ranked_items)


# ── Daily digest: on the owner's hour, independent of when scan cycles run ──

DAILY_DIGEST_GRACE_HOURS = 3     # a late start (machine asleep at the hour) still sends within this window
DAILY_DIGEST_MAX_ITEMS = 20      # keeps the digest prompt bounded
DIGEST_CHECK_SECONDS = 60.0
_daily_digest_running = False


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # CURRENT_TIMESTAMP rows are UTC


def daily_digest_due(now_local: datetime, target_hour: int, last_sent: Optional[datetime]) -> bool:
    """True while a digest slot is open (target hour up to the grace period) and nothing was sent in it."""
    grace = timedelta(hours=DAILY_DIGEST_GRACE_HOURS)
    for days_back in (0, 1):  # yesterday's slot can still be open just after midnight
        day = now_local - timedelta(days=days_back)
        slot = day.replace(hour=target_hour, minute=0, second=0, microsecond=0)
        if slot <= now_local < slot + grace:
            return last_sent is None or last_sent < slot
    return False


def _daily_digest_candidates(since: datetime) -> List[Dict[str, Any]]:
    """Radar items analyzed since `since` that no recent digest has covered yet."""
    covered = set()
    for digest in get_latest_radar_digests(limit=20):
        covered.update(digest.get("item_ids") or [])
    since_iso = since.astimezone(timezone.utc).isoformat()
    return [it for it in get_radar_items_updated_since(since_iso) if it["id"] not in covered]


async def maybe_send_daily_digest(cfg: Optional[Dict[str, Any]] = None,
                                  now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Send the daily digest once per day at daily_digest_hour, whenever scan cycles happen to run.

    Collects radar items analyzed since the previous daily digest (the last 24 hours the first
    time). Returns the digest, or None when it is not due or there is nothing to report.
    """
    global _daily_digest_running
    if _daily_digest_running:
        return None
    cfg = cfg if cfg is not None else get_radar_settings()
    if not cfg.get("enabled") or cfg.get("notification_mode") != "daily_digest":
        return None
    now_local = (now or datetime.now(timezone.utc)).astimezone()
    last_sent = _parse_ts(get_last_radar_digest_at("daily"))
    if not daily_digest_due(now_local, int(cfg.get("daily_digest_hour", 8)), last_sent):
        return None
    _daily_digest_running = True
    try:
        since = last_sent or (now_local - timedelta(hours=24))
        ranked = rank_items_with_exploration(_daily_digest_candidates(since), exploration_ratio=0.2)
        ranked = ranked[:DAILY_DIGEST_MAX_ITEMS]
        if not ranked:
            return None
        digest_info = await generate_radar_digest([it["id"] for it in ranked], digest_type="daily")
        await _announce_digest(digest_info, ranked)
        return digest_info
    finally:
        _daily_digest_running = False


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
    seen = set()  # canonical links already handled this cycle (the same story from two feeds)
    for src in sources:
        try:
            adapter = get_adapter(src.get("source_type"))
            if not adapter:
                logger.warning(f"[Radar:Scheduler] Unknown source type: {src.get('source_type')}")
                continue
            if not is_source_due(src, force=force):
                continue
            raw_items = await adapter.fetch_latest(src)
        except Exception as e:
            logger.warning(f"[Radar:Scheduler] Failed to scan source {src.get('name')}: {e}")
            continue
        for raw in raw_items or []:
            canon = canonical_url(raw.url, repo_level=False)
            if canon in seen:
                continue
            seen.add(canon)
            # Same page under another link (tracking parameters, youtu.be vs watch?v=) counts too;
            # another page of a known repository (a new release) does not.
            row = find_item_by_same_page(raw.url)
            if row and row["analysis_status"] != "pending":
                continue  # already ingested; pending stubs wait for backfill
            if row and row["url"] != raw.url:
                raw = raw.model_copy(update={"url": row["url"]})  # keep to the stub already saved
            pg_score, blocked = pregate_item(raw.title, raw.url, raw.content or "", weight_index)
            if blocked:
                hit = muted_tag_hit(raw.title, raw.content or "", weight_index)
                logger.info(f"[Radar:Scheduler] Pre-gate dropped (muted topic {hit!r}): {raw.title}")
                # The stub saved earlier goes only when the muted tag really is in this item's text.
                if row and hit is not None:
                    delete_item(row["id"])
                continue
            candidates.append((raw, src, pg_score))

    # Load dynamic user settings
    try:
        cfg = get_radar_settings()
    except Exception as e:
        logger.warning(f"[Radar:Scheduler] Failed to get settings: {e}")
        cfg = {"max_analyze_per_cycle": 3, "notification_mode": "silent"}

    # Backfill oldest pending stubs first, then spend remaining budget on the
    # best-ranked new candidates
    budget = max(0, int(cfg.get("max_analyze_per_cycle") or settings.RADAR_MAX_ANALYZE_PER_CYCLE))
    handled: set = set()  # pages the backfill dealt with in this cycle
    all_new_items = await _backfill_pending(budget, handled)
    handled.update(_page_key(it["url"]) for it in all_new_items if it.get("url"))
    budget -= len(all_new_items)

    candidates.sort(key=lambda c: c[2], reverse=True)
    deferred_count = 0
    for raw, src, _pg in candidates:
        # A pending stub is a candidate too (its source listed it again). When the backfill
        # just took it, analyzing it again or deferring it would undo that work.
        key = _page_key(raw.url)
        if key in handled:
            continue
        handled.add(key)  # one analysis per page per cycle
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
            logger.warning(f"[Radar:Scheduler] Error analyzing {raw.url}: {e}")

    # Rank newly detected items using 80/20 Epsilon-Greedy exploration
    ranked_items = rank_items_with_exploration(all_new_items, exploration_ratio=0.2)

    notification_mode = cfg.get("notification_mode", "silent")
    digest_info = None

    if notification_mode == "daily_digest":
        # The scheduler's digest check sends at the chosen hour even when no cycle runs then;
        # a cycle inside the slot just sends it sooner. Both go through the same once-a-day gate.
        if auto_digest:
            digest_info = await maybe_send_daily_digest(cfg)
    elif notification_mode == "vip_alert":
        vip_threshold = float(cfg.get("vip_threshold", 4.0))
        vip_items = [it for it in ranked_items if float(it.get("radar_score", 0.0)) >= vip_threshold]
        if vip_items:
            await _announce_vip(vip_items)
    elif notification_mode == "legacy" or cfg.get("auto_digest_push") or cfg.get("auto_star_push"):
        if auto_digest and len(ranked_items) >= 2 and cfg.get("auto_digest_push"):
            item_ids = [it["id"] for it in ranked_items]
            local_hour = datetime.now().astimezone().hour
            dtype = "evening" if 17 <= local_hour <= 23 else "morning"
            digest_info = await generate_radar_digest(item_ids, digest_type=dtype)
            await _announce_digest(digest_info, ranked_items)
        if cfg.get("auto_star_push"):
            await _announce_autostar(ranked_items)
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
        self._digest_task: Optional[asyncio.Task] = None
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
        # Fresh events for the loop starting us: an asyncio.Event stays bound to the
        # first event loop that waited on it, and a restarted scheduler may run in another.
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(self._loop(initial_delay=initial_delay))
        self._digest_task = asyncio.create_task(self._digest_loop(initial_delay=initial_delay))
        logger.info(f"[Radar:Scheduler] Background scheduler loop started.")

    async def _digest_loop(self, initial_delay: float = 10.0):
        """Checks every minute whether the daily digest is due; cheap when it is not (one DB read)."""
        delay = initial_delay
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=max(delay, 0.0))
                break
            except asyncio.TimeoutError:
                pass
            delay = DIGEST_CHECK_SECONDS
            try:
                await maybe_send_daily_digest()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[Radar:Digest] Daily digest check failed: {e}")

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
                logger.warning(f"[Radar:Scheduler] Error loading settings in loop: {e}")
                cfg = {"enabled": False, "interval_minutes": 180, "max_analyze_per_cycle": 3}

            is_enabled = cfg.get("enabled", False)
            interval_minutes = cfg.get("interval_minutes", 180)

            if is_enabled and interval_minutes > 0:
                try:
                    logger.info("[Radar:Scheduler] Starting periodic radar scan cycle...")
                    res = await run_radar_cycle(force=False, auto_digest=True)
                    logger.info(f"[Radar:Scheduler] Cycle complete: {res['new_items_count']} new items detected across {res['sources_scanned']} sources.")
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"[Radar:Scheduler] Error during periodic cycle: {e}")

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
        logger.info("[Radar:Scheduler] Stopping background scheduler...")
        self._stop_event.set()
        self._wake_event.set()
        tasks = [t for t in (self._task, self._digest_task) if t]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._is_running = False
        logger.info("[Radar:Scheduler] Background scheduler stopped.")

radar_scheduler = RadarScheduler()
