"""Items whose fetch got only an error / anti-bot page are fetched again later, in the background.

A site that is down for an hour, an X mirror that is out, a bot check that passes the next time:
the item is kept as "（擷取失敗）" and tried again 1 h after it was collected, then with the gap
doubling (2 h, 4 h, 8 h ...) for 7 days. An X post whose replies could not be read, and a video
whose transcript could not be read (app/parsers/transcript.py), are retried the same way. A try that still gets the error page costs one fetch and no AI call; the first one that
gets the content runs the normal pipeline on the URL, the same as collecting it again, which
rewrites the item in place.

The same loop analyses items that were kept while no AI was connected ("（尚未分析）",
app/pipeline.py): once a connection exists, a few per tick, oldest first, from their stored text.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.database import get_db_connection
from app.parsers.blocked import MAX_CHARS, detect_blocked_page
from app.parsers.transcript import TRANSCRIPT_MISSING
from app.parsers.x_posts import REPLIES_MISSING

logger = logging.getLogger("omnikeep.refetch")

RETRY_FOR = timedelta(days=7)
FIRST_GAP = timedelta(hours=1)
TICK_SECONDS = 600
PER_TICK = 10  # at most this many fetches per tick, so a backlog cannot burst
SOURCE_TYPES = ("web", "threads")  # content scraped from the page (pipeline.BLOCK_CHECKED_KINDS)

ANALYSE_PER_TICK = 5  # items kept without analysis that one tick analyses, so a backlog cannot burst
ANALYSE_GIVE_UP = 3  # failures after which this process leaves an item to the "現在分析" button

_last_try: Dict[str, datetime] = {}  # item id -> last try by this process
_analysis_failures: Dict[str, int] = {}  # item id -> failed analyses by this process


def _when(text: str) -> Optional[datetime]:
    try:
        value = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def incomplete(content: str, http_status: Optional[int] = None) -> bool:
    """The content is an error page, an X post whose replies could not be read, or a video without its transcript."""
    content = content or ""
    return bool(detect_blocked_page(content, http_status)) or REPLIES_MISSING in content or TRANSCRIPT_MISSING in content


def candidates(now: datetime) -> List[Dict[str, Any]]:
    """Items collected in the last RETRY_FOR whose stored content is an error page or lacks its replies / transcript."""
    marks = ",".join("?" * len(SOURCE_TYPES))
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT id, url, origin, content_raw, created_at, updated_at FROM items "
            f"WHERE created_at >= ? AND ((source_type IN ({marks}) AND length(coalesce(content_raw, '')) <= ?) "
            f"OR instr(content_raw, ?) > 0 OR instr(content_raw, ?) > 0) "
            f"ORDER BY created_at DESC",
            ((now - RETRY_FOR).isoformat(), *SOURCE_TYPES, MAX_CHARS, REPLIES_MISSING, TRANSCRIPT_MISSING)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows if incomplete(r["content_raw"])]


def due(item: Dict[str, Any], now: datetime) -> bool:
    created = _when(item["created_at"])
    if created is None:
        return False
    last = _last_try.get(item["id"])
    if last is None:
        # Not tried by this process yet. updated_at is no clue: the source annotation run, a
        # re-analysis or an edit rewrites it, and taking it as the last try pushed the next try of
        # an item rewritten on day 5 past the 7 days (seen 2026-11-08). So the first tick after a
        # start tries each waiting item once (PER_TICK at a time, no AI call while it is blocked).
        return now - created >= FIRST_GAP
    return now - last >= max(FIRST_GAP, last - created)


async def retry_one(item: Dict[str, Any], now: datetime) -> bool:
    """True when the content came this time and the item was analysed again."""
    from app.pipeline import BLOCK_CHECKED_KINDS, parse_url, run_pipeline
    _last_try[item["id"]] = now
    if TRANSCRIPT_MISSING in (item.get("content_raw") or ""):
        # A video: the download and speech to text are the slow part, so it is not parsed twice. A
        # transcript that still fails is kept as a fetch failure again, with no AI call.
        from app.database import get_item_by_id
        await run_pipeline(item["url"], origin=item.get("origin") or "manual")
        return TRANSCRIPT_MISSING not in ((get_item_by_id(item["id"]) or {}).get("content_raw") or "")
    parsed = await parse_url(item["url"])
    if parsed["kind"] in BLOCK_CHECKED_KINDS:
        content = parsed["content_raw"] or ""
        if detect_blocked_page(content, parsed.get("http_status")):
            return False
        had_post = not detect_blocked_page(item.get("content_raw") or "")
        if had_post and REPLIES_MISSING in content:
            return False  # nothing new: the post is saved already and the replies are still missing
    # The post now (its replies may still be missing: then it stays a candidate and is tried again).
    await run_pipeline(item["url"], origin=item.get("origin") or "manual")
    return True


async def run_once(now: Optional[datetime] = None) -> Dict[str, int]:
    now = now or datetime.now(timezone.utc)
    items = await asyncio.to_thread(candidates, now)
    stats = {"waiting": len(items), "tried": 0, "fixed": 0}
    for item in items:
        if stats["tried"] >= PER_TICK:
            break
        if not due(item, now):
            continue
        stats["tried"] += 1
        try:
            if await retry_one(item, now):
                stats["fixed"] += 1
                logger.info("[Refetch] %s: got the content this time and analysed it", item["url"])
        except Exception as exc:
            logger.warning("[Refetch] %s failed (%s: %s)", item["url"], type(exc).__name__, str(exc)[:200])
    waiting = {item["id"] for item in items}
    for item_id in list(_last_try):
        if item_id not in waiting:
            del _last_try[item_id]
    return stats


def waiting_for_analysis(limit: int = 50) -> List[Dict[str, Any]]:
    """Items kept while no AI was connected, oldest first (radar stubs have their own backfill)."""
    conn = get_db_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM items WHERE analysis_status = 'pending' AND origin != 'radar' "
            "ORDER BY created_at ASC LIMIT ?", (limit,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


async def analyse_waiting() -> Dict[str, int]:
    """Analyse a few of the items kept without analysis. Does nothing while no AI is connected.

    The first failure ends the tick: a rate limit or an outage would fail the rest as well.
    """
    from app.pipeline import analyse_saved_item
    from app.providers import ai_connected
    stats = {"waiting": 0, "analysed": 0, "failed": 0}
    if not ai_connected():
        return stats
    items = await asyncio.to_thread(waiting_for_analysis)
    stats["waiting"] = len(items)
    for item in items:
        if stats["analysed"] >= ANALYSE_PER_TICK:
            break
        if _analysis_failures.get(item["id"], 0) >= ANALYSE_GIVE_UP:
            continue
        try:
            await analyse_saved_item(item)
        except Exception as exc:
            _analysis_failures[item["id"]] = _analysis_failures.get(item["id"], 0) + 1
            stats["failed"] += 1
            logger.warning("[Refetch] analysis of %s failed (%s: %s)", item["url"], type(exc).__name__, str(exc)[:200])
            break
        _analysis_failures.pop(item["id"], None)
        stats["analysed"] += 1
    return stats


async def refetch_loop(tick_seconds: int = TICK_SECONDS, initial_delay: float = 120.0) -> None:
    await asyncio.sleep(initial_delay)
    while True:
        try:
            stats = await run_once()
            if stats["tried"]:
                logger.info("[Refetch] %s", stats)
        except Exception as exc:
            logger.error("[Refetch] tick failed (%s)", type(exc).__name__)
        try:
            stats = await analyse_waiting()
            if stats["analysed"] or stats["failed"]:
                logger.info("[Refetch] items kept without analysis: %s", stats)
        except Exception as exc:
            logger.error("[Refetch] analysis tick failed (%s)", type(exc).__name__)
        await asyncio.sleep(tick_seconds)
