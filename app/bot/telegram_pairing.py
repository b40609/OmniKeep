"""Binding a Telegram account as an OmniKeep owner with a one-time link.

The signed-in web app asks for a code and shows https://t.me/<bot>?start=<code>
(Telegram's deep-link start parameter: up to 64 of A-Z a-z 0-9 _ -). Opening it
sends "/start <code>" to the bot, which binds the sender. Codes live in the
database (so a separately run bot process sees them), only as a hash, expire
after ten minutes and work once. Nobody is ever bound just for messaging first.
"""
import hashlib
import logging
import secrets
import time
from pathlib import Path
from typing import Optional, Tuple

import dotenv

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


def _env_file() -> Optional[Path]:
    """The .env the settings were loaded from, as an absolute path (None while testing)."""
    env_file = settings.model_config.get("env_file")
    return Path(env_file).resolve() if env_file else None


def bind_telegram_user(user_id: int) -> bool:
    """Allow user_id from now on; True when that also reached .env and survives a restart."""
    ids = settings.telegram_allowed_ids
    if user_id not in ids:
        ids = [*ids, user_id]
    value = ",".join(str(i) for i in ids)
    settings.TELEGRAM_ALLOWED_USER_IDS_RAW = value
    env_file = _env_file()
    if env_file is None:
        return False
    try:
        dotenv.set_key(str(env_file), "TELEGRAM_ALLOWED_USER_IDS", value, quote_mode="never")
        return True
    except Exception as exc:
        logger.warning("Could not persist TELEGRAM_ALLOWED_USER_IDS to %s (%s)", env_file, type(exc).__name__)
        return False
