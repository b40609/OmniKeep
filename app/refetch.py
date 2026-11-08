"""Items whose fetch got only an error / anti-bot page are fetched again later, in the background.

A site that is down for an hour, an X mirror that is out, a bot check that passes the next time:
the item is kept as "（擷取失敗）" and tried again 1 h after it was collected, then with the gap
doubling (2 h, 4 h, 8 h ...) for 7 days. A try that still gets the error page costs one fetch and
no AI call; the first one that gets the content runs the normal pipeline on the URL, the same as
collecting it again, which rewrites the item in place.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.database import get_db_connection
from app.parsers.blocked import MAX_CHARS, detect_blocked_page

logger = logging.getLogger("omnikeep.refetch")

RETRY_FOR = timedelta(days=7)
FIRST_GAP = timedelta(hours=1)
TICK_SECONDS = 600
PER_TICK = 10  # at most this many fetches per tick, so a backlog cannot burst
SOURCE_TYPES = ("web", "threads")  # content scraped from the page (pipeline.BLOCK_CHECKED_KINDS)

_last_try: Dict[str, datetime] = {}  # item id -> last try by this process


def _when(text: str) -> Optional[datetime]:
    try:
        value = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def candidates(now: datetime) -> List[Dict[str, Any]]:
    """Items collected in the last RETRY_FOR whose stored content is an error page."""
    marks = ",".join("?" * len(SOURCE_TYPES))
    conn = get_db_connection()
    try:
        rows = conn.execute(
            f"SELECT id, url, origin, content_raw, created_at, updated_at FROM items "
            f"WHERE source_type IN ({marks}) AND created_at >= ? AND length(coalesce(content_raw, '')) <= ? "
            f"ORDER BY created_at DESC",
            (*SOURCE_TYPES, (now - RETRY_FOR).isoformat(), MAX_CHARS)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows if detect_blocked_page(r["content_raw"] or "")]


def due(item: Dict[str, Any], now: datetime) -> bool:
    created = _when(item["created_at"])
    if created is None:
        return False
    last = _last_try.get(item["id"]) or _when(item["updated_at"]) or created
    return now - last >= max(FIRST_GAP, last - created)


async def retry_one(item: Dict[str, Any], now: datetime) -> bool:
    """True when the content came this time and the item was analysed again."""
    from app.pipeline import BLOCK_CHECKED_KINDS, parse_url, run_pipeline
    _last_try[item["id"]] = now
    parsed = await parse_url(item["url"])
    if parsed["kind"] in BLOCK_CHECKED_KINDS and detect_blocked_page(parsed["content_raw"], parsed.get("http_status")):
        return False
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


async def refetch_loop(tick_seconds: int = TICK_SECONDS, initial_delay: float = 120.0) -> None:
    await asyncio.sleep(initial_delay)
    while True:
        try:
            stats = await run_once()
            if stats["tried"]:
                logger.info("[Refetch] %s", stats)
        except Exception as exc:
            logger.error("[Refetch] tick failed (%s)", type(exc).__name__)
        await asyncio.sleep(tick_seconds)
