"""Long-running background services that settings changes can restart in place."""
import asyncio
import logging
from typing import Any, Optional

from app.config import settings

logger = logging.getLogger("omnikeep.services")

_telegram_task: Optional[asyncio.Task] = None
_telegram_bot: Any = None
_running = False  # background services are enabled in this process


async def supervise_telegram_polling(bot):
    """Restart a crashed/returned poller while the web service remains alive."""
    while True:
        try:
            await bot.run_polling()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram polling exited unexpectedly; restarting")
        else:
            logger.error("Telegram polling stopped unexpectedly; restarting")
        await asyncio.sleep(3)


def start_telegram() -> bool:
    """Start polling when a bot token is set; True when a poller is running."""
    global _telegram_task, _telegram_bot, _running
    _running = True
    if _telegram_task is not None and not _telegram_task.done():
        return True
    if not settings.TELEGRAM_BOT_TOKEN:
        return False
    from app.bot import telegram_bot
    bot = telegram_bot.get_telegram_bot()
    if bot is None:
        return False
    _telegram_bot = bot
    _telegram_task = asyncio.create_task(supervise_telegram_polling(bot))
    return True


async def stop_telegram_polling() -> None:
    global _telegram_task
    task, _telegram_task = _telegram_task, None
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def close_telegram_bot() -> None:
    """Close the bot's HTTP client and forget it, so the next one uses the current token."""
    global _telegram_bot
    bot, _telegram_bot = _telegram_bot, None
    from app.bot import telegram_bot
    singleton = telegram_bot._bot_instance
    if bot is not None:
        await bot.close()
    if singleton is not None and singleton is not bot:
        await singleton.close()
    telegram_bot._bot_instance = None


async def restart_telegram() -> None:
    """Apply a changed bot token: stop the old poller, start one with the new token."""
    await stop_telegram_polling()
    await close_telegram_bot()
    if _running:
        if start_telegram():
            logger.info("Telegram polling restarted with the token saved in the app")
        else:
            logger.info("Telegram polling stopped: no bot token configured")


async def shutdown() -> None:
    global _running
    _running = False
    await stop_telegram_polling()
    await close_telegram_bot()
