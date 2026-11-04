"""Web Push (VAPID) key pair: created when the server first starts, kept in the app's settings.

The private key is encrypted like every other credential (app.secret_box); the
public key is stored as is, since every browser receives it anyway. A pair
already in .env is used as it is: browsers subscribe to one public key, so a
new pair would silently orphan every existing subscription.
"""
import base64
import logging
from contextlib import closing
from typing import Any, Dict, Tuple

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app import app_settings
from app.config import settings
from app.database import get_db_connection

logger = logging.getLogger("omnikeep.vapid")

PUBLIC = "VAPID_PUBLIC_KEY"
PRIVATE = "VAPID_PRIVATE_KEY"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pair() -> Tuple[str, str]:
    """(public, private) as base64url: uncompressed P-256 point and raw 32-byte scalar."""
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _b64url(public), _b64url(private.private_numbers().private_value.to_bytes(32, "big"))


def _stored() -> Tuple[set, set]:
    values, broken, _ = app_settings._stored_values()
    return set(values) & app_settings.GENERATED_KEYS, broken & app_settings.GENERATED_KEYS


def _env_pair() -> bool:
    return all(app_settings.baseline_value(app_settings.SPEC_BY_KEY[key]) for key in (PUBLIC, PRIVATE))


def _subscriptions() -> int:
    with closing(get_db_connection()) as conn:
        return conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]


def status() -> Dict[str, Any]:
    stored, broken = _stored()
    if broken or stored == app_settings.GENERATED_KEYS:
        source = "app"
    elif _env_pair():
        source = "env"
    else:
        source = "none"
    return {
        "ready": bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY),
        "source": source,
        "undecryptable": bool(broken),
        "subscriptions": _subscriptions(),
    }


def _store(action: str) -> None:
    public, private = generate_pair()
    app_settings.save({PUBLIC: public, PRIVATE: private}, action=action, system=True)


def ensure() -> str:
    """Make sure the server can sign pushes; returns where the pair comes from.

    Never replaces a pair it cannot read: the right master key may still turn up
    (restored from a backup), and a new pair would orphan every subscription.
    """
    stored, broken = _stored()
    if broken:
        logger.warning("The saved Web Push key cannot be decrypted with the current master key; "
                       "push stays off until the key file is restored or the pair is regenerated in the app")
        return "undecryptable"
    if stored == app_settings.GENERATED_KEYS:
        return "app"
    if _env_pair():
        return "env"
    _store("generate")
    logger.info("Generated a Web Push key pair (stored encrypted in the app's settings)")
    return "generated"


def regenerate() -> int:
    """Replace the pair on request; returns how many subscriptions were dropped with the old one."""
    _store("regenerate")
    with closing(get_db_connection()) as conn, conn:
        removed = conn.execute("DELETE FROM push_subscriptions").rowcount
    logger.info("Regenerated the Web Push key pair; removed %d subscriptions bound to the old key", removed)
    return removed
