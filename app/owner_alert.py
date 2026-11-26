"""Tell the owner, once, about something only a person can fix.

Used for: a connection that hit its spend cap or ran out of balance (app/ai_status.py), a source
of the local gateway over its daily cap or past its end date (app/llm_gateway.py), the service
restarted after it stopped answering (scripts/watchdog.ps1 via scripts/alert_owner.py), and a
Telegram message skipped after failing again and again (app/bot/telegram_bot.py).

It goes out through the channels OmniKeep already uses to reach its owner, and nowhere else:
the bound Telegram accounts (TELEGRAM_ALLOWED_USER_IDS), the subscribed PWA devices (Web Push)
and the bound LINE accounts. Each channel that is not set up is skipped.

alert_once() remembers what it sent in app_settings ("_alert.<key>", the time it was sent), so
a restart or a second process (the gateway runs beside the server) does not send it again;
forget() lets it be sent again once the problem is over. Nothing here ever raises.
"""
import asyncio
import html
import logging
import sqlite3
import threading
from contextlib import closing
from datetime import datetime, timezone
from typing import Dict, Optional, Set

logger = logging.getLogger("omnikeep.owner_alert")

PREFIX = "_alert."
_tasks: Set["asyncio.Task"] = set()  # keeps fire-and-forget sends alive until they finish


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def claim(key: str) -> bool:
    """True the first time `key` is claimed (until forget(key)); False afterwards or on error."""
    try:
        from app.database import get_db_connection
        with closing(get_db_connection()) as db, db:
            cursor = db.execute(
                "INSERT OR IGNORE INTO app_settings (key, value, is_secret, updated_at) VALUES (?, ?, 0, ?)",
                (PREFIX + key, _now(), _now()))
            return cursor.rowcount == 1
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        logger.warning("Owner alert %s could not be recorded (%s); not sent", key, type(exc).__name__)
        return False


def sent_at(key: str) -> Optional[str]:
    try:
        from app.database import get_db_connection
        with closing(get_db_connection()) as db:
            row = db.execute("SELECT value FROM app_settings WHERE key = ?", (PREFIX + key,)).fetchone()
        return row["value"] if row else None
    except (sqlite3.Error, OSError, RuntimeError):
        return None


def forget(key: str) -> None:
    try:
        from app.database import get_db_connection
        with closing(get_db_connection()) as db, db:
            db.execute("DELETE FROM app_settings WHERE key = ?", (PREFIX + key,))
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        logger.debug("Owner alert %s could not be cleared: %s", key, exc)


async def send(title: str, body: str, tag: str = "omnikeep-alert") -> Dict[str, int]:
    """Send now on every channel that is set up; returns how many deliveries went out."""
    counts = {"telegram": 0, "web_push": 0, "line": 0}
    try:
        # The gateway and the scripts do not run init_db(): pick up the settings saved in the app
        # (the Telegram token and bound accounts usually live there, not in .env).
        from app.app_settings import apply_overrides
        apply_overrides()
    except Exception as exc:  # noqa: BLE001 - never raises; .env values still work
        logger.debug("Owner alert: saved settings not applied (%s)", exc)
    from app.config import settings
    try:
        from app.bot.telegram_bot import get_telegram_bot
        bot = get_telegram_bot()
        if bot:
            text = f"<b>{html.escape(title)}</b>\n\n{html.escape(body)}"
            for chat_id in settings.telegram_allowed_ids:
                try:
                    result = await bot.send_message(chat_id, text)
                    if result.get("ok", True):
                        counts["telegram"] += 1
                except Exception as exc:  # noqa: BLE001 - one channel failing must not stop the others
                    logger.warning("Owner alert to Telegram failed: %s", type(exc).__name__)
    except Exception as exc:  # noqa: BLE001 - one channel failing must not stop the others
        logger.warning("Owner alert: Telegram unavailable (%s)", type(exc).__name__)
    try:
        from app.push import send_push
        counts["web_push"] = (await send_push(title, body, tag=tag)).get("sent", 0)
    except Exception as exc:  # noqa: BLE001 - one channel failing must not stop the others
        logger.warning("Owner alert: Web Push failed (%s)", type(exc).__name__)
    if settings.LINE_CHANNEL_ACCESS_TOKEN:
        try:
            from app.bot.line_bot import push_line_messages
            for user_id in settings.line_allowed_ids:
                try:
                    await push_line_messages(user_id, [{"type": "text", "text": f"{title}\n\n{body}"[:4900]}])
                    counts["line"] += 1
                except Exception as exc:  # noqa: BLE001 - one channel failing must not stop the others
                    logger.warning("Owner alert to LINE failed: %s", type(exc).__name__)
        except Exception as exc:  # noqa: BLE001 - one channel failing must not stop the others
            logger.warning("Owner alert: LINE unavailable (%s)", type(exc).__name__)
    logger.warning("Owner alert sent: %s (%s)", title, ", ".join(f"{k} {v}" for k, v in counts.items()))
    return counts


def _fire(title: str, body: str, tag: str) -> None:
    """Send in the background, from async code or from a plain thread."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        task = loop.create_task(send(title, body, tag))
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)
        return
    threading.Thread(target=lambda: asyncio.run(send(title, body, tag)), name="owner-alert", daemon=True).start()


def alert_once(key: str, title: str, body: str, tag: Optional[str] = None) -> bool:
    """Send `title`/`body` unless `key` was already sent (and not forgotten); True when sent now.

    Returns at once: the delivery runs in the background.
    """
    if not claim(key):
        return False
    _fire(title, body, (tag or key)[:32])
    return True


async def alert_once_async(key: str, title: str, body: str, tag: Optional[str] = None) -> Optional[Dict[str, int]]:
    """alert_once() that waits for the delivery (for scripts); None when it was already sent."""
    if not claim(key):
        return None
    return await send(title, body, (tag or key)[:32])
