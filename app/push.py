"""Web Push delivery to subscribed PWA clients (RFC 8030 / 8291 / 8292).

Payloads are encrypted with aes128gcm (http-ece) and authenticated with a
VAPID JWT (py-vapid). Requests go through the public-network client, so a
stored endpoint can never point the server at loopback or private hosts.
"""
import asyncio
import base64
import json
import logging
import re
import time
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

import http_ece
from cryptography.hazmat.primitives.asymmetric import ec
from py_vapid import Vapid02

from app.config import settings
from app.database import (
    delete_push_subscription,
    get_item_by_id,
    list_push_subscriptions,
    record_push_result,
)
from app.network import UnsafeURL, public_http_client, validate_url

logger = logging.getLogger("omnikeep.push")

DEFAULT_SUBJECT = "https://github.com/b40609/OmniKeep"
# Apple: Topic is at most 32 URL/filename-safe Base64 characters.
_TOPIC = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
# Push services accept 4096-byte encrypted bodies; keep text well under that.
_MAX_BODY_CHARS = 400
# The PWA opens 監看中心 on its 提案 tab for this link (frontend/src/lib/push.ts).
PROPOSALS_URL = "/?open=proposals"


def push_configured() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def validate_endpoint(endpoint: str) -> str:
    if urlsplit(endpoint).scheme != "https":
        raise UnsafeURL("Push endpoints must use https")
    return validate_url(endpoint)


def validate_keys(p256dh: str, auth: str) -> None:
    receiver = b64url_decode(p256dh)
    if len(receiver) != 65 or receiver[0] != 0x04 or len(b64url_decode(auth)) != 16:
        raise ValueError("Invalid push subscription keys")
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver)


def encrypt_payload(payload: bytes, p256dh: str, auth: str) -> bytes:
    # A fresh ECDH key per message, as RFC 8291 requires.
    return http_ece.encrypt(
        payload,
        private_key=ec.generate_private_key(ec.SECP256R1()),
        dh=b64url_decode(p256dh),
        auth_secret=b64url_decode(auth),
        version="aes128gcm",
    )


def vapid_headers(endpoint: str) -> Dict[str, str]:
    parts = urlsplit(endpoint)
    claims = {
        "aud": f"{parts.scheme}://{parts.netloc}",
        # Apple rejects tokens that expire more than a day ahead.
        "exp": int(time.time()) + 12 * 3600,
        "sub": settings.VAPID_SUBJECT or DEFAULT_SUBJECT,
    }
    signer = Vapid02.from_string(settings.VAPID_PRIVATE_KEY)
    # py-vapid's own check accepts an https subject only without a path, so it
    # refused DEFAULT_SUBJECT and failed every push sent without VAPID_SUBJECT.
    # RFC 8292 allows any https URI; the settings page already insists on mailto:/https:.
    signer.conf["no-strict"] = True
    return signer.sign(claims)


async def _deliver(client, sub: Dict[str, Any], payload: bytes, ttl: int, topic: Optional[str]) -> str:
    endpoint = sub["endpoint"]
    host = urlsplit(endpoint).hostname or "?"
    try:
        validate_endpoint(endpoint)
        headers = {
            "TTL": str(ttl),
            "Urgency": "normal",
            "Content-Encoding": "aes128gcm",
            "Content-Type": "application/octet-stream",
            **vapid_headers(endpoint),
        }
        if topic:
            headers["Topic"] = topic
        res = await client.post(endpoint, content=encrypt_payload(payload, sub["p256dh"], sub["auth"]),
                                headers=headers)
    except Exception as exc:
        # The endpoint URL is a bearer capability; log only its host.
        logger.warning("Web Push to %s failed: %s", host, type(exc).__name__)
        record_push_result(endpoint, error=type(exc).__name__)
        return "failed"
    if res.status_code in (404, 410):
        delete_push_subscription(endpoint)
        logger.info("Removed expired Web Push subscription on %s", host)
        return "removed"
    if 200 <= res.status_code < 300:
        record_push_result(endpoint)
        return "sent"
    logger.warning("Web Push to %s rejected: HTTP %s", host, res.status_code)
    record_push_result(endpoint, error=f"HTTP {res.status_code}")
    return "failed"


async def send_push(title: str, body: str, url: str = "/", tag: Optional[str] = None,
                    ttl: int = 24 * 3600) -> Dict[str, int]:
    """Notify every subscribed device; never raises, returns per-outcome counts."""
    counts = {"sent": 0, "removed": 0, "failed": 0}
    if not push_configured():
        return counts
    subs = list_push_subscriptions()
    if not subs:
        return counts
    if len(body) > _MAX_BODY_CHARS:
        body = body[:_MAX_BODY_CHARS - 1] + "…"
    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url if url.startswith("/") and not url.startswith("//") else "/",
        "tag": tag,
    }, ensure_ascii=False).encode("utf-8")
    topic = tag if tag and _TOPIC.match(tag) else None
    try:
        async with public_http_client(timeout=15.0) as client:
            outcomes = await asyncio.gather(*(_deliver(client, s, payload, ttl, topic) for s in subs))
    except Exception:
        logger.exception("Web Push delivery aborted")
        return counts
    for outcome in outcomes:
        counts[outcome] += 1
    return counts


async def notify_new_proposal(proposal: Dict[str, Any]) -> Dict[str, int]:
    """Announce a newly saved pending proposal (Telegram has no counterpart); never raises."""
    try:
        card = get_item_by_id(proposal["item_id"]) or {}
        scores = (f"影響 {float(proposal['impact']):g} · 信心 {float(proposal['confidence']):g}"
                  f" · 成本 {float(proposal['effort']):g}")
        # One tag per proposal, so a second proposal doesn't replace the first notification.
        return await send_push("📋 新的待決提案", f"{card.get('title_l1') or '新提案'}\n{scores}",
                               url=PROPOSALS_URL, tag=f"proposal-{proposal['id']}")
    except Exception:
        logger.exception("Web Push for new proposal failed")
        return {"sent": 0, "removed": 0, "failed": 0}
