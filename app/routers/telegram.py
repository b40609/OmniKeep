"""Telegram owner binding from the signed-in web app (one-time t.me pairing links)."""
from fastapi import APIRouter, HTTPException

from app.bot.telegram_bot import get_telegram_bot
from app.bot.telegram_pairing import create_pairing_code, pending_pairing_expiry
from app.config import settings

router = APIRouter(prefix="/api/telegram", tags=["Telegram"])


@router.get("/status")
async def telegram_status():
    return {
        "configured": bool(settings.TELEGRAM_BOT_TOKEN),
        "bound_user_ids": settings.telegram_allowed_ids,
        "pairing_expires_at": pending_pairing_expiry(),
    }


@router.post("/pairing")
async def create_pairing():
    bot = get_telegram_bot()
    if not bot:
        raise HTTPException(503, "TELEGRAM_BOT_TOKEN is not configured")
    try:
        username = await bot.get_username()
    except Exception as exc:
        raise HTTPException(502, "Could not reach Telegram to look up the bot") from exc
    if not username:
        raise HTTPException(502, "Telegram did not return the bot's username")
    code, expires_at = create_pairing_code()
    return {"link": f"https://t.me/{username}?start={code}", "expires_at": expires_at}
