"""Binding a Telegram account as an OmniKeep owner with a one-time link.

The signed-in web app asks for a code and shows https://t.me/<bot>?start=<code>
(Telegram's deep-link start parameter: up to 64 of A-Z a-z 0-9 _ -). Opening it
sends "/start <code>" to the bot, which binds the sender. Codes live in the
database (so a separately run bot process sees them), only as a hash, expire
after ten minutes and work once. Nobody is ever bound just for messaging first.
Bound owners are saved as the app setting TELEGRAM_ALLOWED_USER_IDS
(app/app_settings.py), never written to .env.
"""
import hashlib
import logging
import secrets
import time
from typing import Optional, Tuple

from app.config import settings
from app.database import consume_telegram_pairing, get_telegram_pairing_expiry, set_telegram_pairing

logger = logging.getLogger("omnikeep.telegram_pairing")

PAIRING_TTL_SECONDS = 600


def _hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def create_pairing_code() -> Tuple[str, float]:
    code = secrets.token_urlsafe(24)  # 32 characters, all valid in a start parameter
    expires_at = time.time() + PAIRING_TTL_SECONDS
    set_telegram_pairing(_hash(code), expires_at)
    return code, expires_at


def redeem_pairing_code(code: str) -> bool:
    return bool(code) and consume_telegram_pairing(_hash(code), time.time())


def pending_pairing_expiry() -> Optional[float]:
    return get_telegram_pairing_expiry(time.time())


def bind_telegram_user(user_id: int) -> bool:
    """Allow user_id from now on; True when that was also saved and survives a restart."""
    ids = settings.telegram_allowed_ids
    if user_id not in ids:
        ids = [*ids, user_id]
    value = ",".join(str(i) for i in ids)
    try:
        from app.app_settings import save
        save({"TELEGRAM_ALLOWED_USER_IDS": value}, action="pair")  # also applies it
        return True
    except Exception as exc:
        logger.warning("Could not save the Telegram binding (%s)", type(exc).__name__)
        settings.TELEGRAM_ALLOWED_USER_IDS_RAW = value  # still allowed until a restart
        return False
