"""OpenRouter OAuth PKCE (S256) flow for one-click API key provisioning.

Official flow (https://openrouter.ai/docs/guides/overview/auth/oauth):
  1. The server generates `code_verifier`, SHA-256 `code_challenge`, and a one-time `state`.
  2. The browser redirects to `https://openrouter.ai/auth` with `callback_url`,
     `code_challenge`, and `code_challenge_method=S256`. OpenRouter accepts localhost /
     127.0.0.1 callback URLs on any port as well as normal http(s) origins.
  3. OpenRouter redirects back to `callback_url?code=...`.
  4. The signed-in frontend posts `code` and `state` to OmniKeep; the server exchanges
     them at `POST https://openrouter.ai/api/v1/auth/keys` and saves the returned key
     encrypted without ever sending the plaintext key back to the browser.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import secrets
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlencode, urlsplit, urlunsplit

import httpx

logger = logging.getLogger("omnikeep.openrouter_oauth")

AUTH_URL = "https://openrouter.ai/auth"
EXCHANGE_URL = "https://openrouter.ai/api/v1/auth/keys"
TTL = 600.0
MAX_PENDING = 16
EXCHANGE_TIMEOUT = 20.0

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_lock = threading.Lock()
_pending: Dict[str, Dict[str, Any]] = {}


class OpenRouterOAuthError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def clear() -> None:
    """Drop all pending PKCE challenges (used by tests)."""
    with _lock:
        _pending.clear()


def _prune(now: float) -> None:
    expired = [k for k, v in _pending.items() if now - float(v["created_at"]) > TTL]
    for k in expired:
        _pending.pop(k, None)
    while len(_pending) > MAX_PENDING:
        oldest = min(_pending.items(), key=lambda kv: float(kv[1]["created_at"]))[0]
        _pending.pop(oldest, None)


def validate_callback_url(raw: str) -> str:
    """Normalize callback_url to a clean http(s) origin + path with no query or fragment."""
    value = (raw or "").strip()
    if not value or len(value) > 500 or _CONTROL.search(value) or any(ch.isspace() for ch in value):
        raise OpenRouterOAuthError("回呼網址格式不正確", 400)
    parts = urlsplit(value)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        raise OpenRouterOAuthError("回呼網址必須是 http:// 或 https:// 開頭", 400)
    if parts.username or parts.password:
        raise OpenRouterOAuthError("回呼網址不能包含帳號或密碼", 400)
    path = parts.path or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc, path, "", ""))


def code_challenge_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def start(
    callback_url: str,
    *,
    connection_id: Optional[int] = None,
    slot: str = "",
    now: Optional[float] = None,
) -> Dict[str, str]:
    """Create a one-time PKCE challenge and return the OpenRouter authorization URL and state."""
    clean_url = validate_callback_url(callback_url)
    verifier = secrets.token_urlsafe(48)
    challenge = code_challenge_s256(verifier)
    state = secrets.token_urlsafe(24)
    ts = time.time() if now is None else float(now)

    with _lock:
        _prune(ts)
        _pending[state] = {
            "code_verifier": verifier,
            "created_at": ts,
            "connection_id": connection_id,
            "slot": (slot or "").strip(),
        }
        _prune(ts)

    query = urlencode({
        "callback_url": clean_url,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    return {"auth_url": f"{AUTH_URL}?{query}", "state": state}


async def exchange(
    code: str,
    state: str,
    *,
    now: Optional[float] = None,
) -> Tuple[str, Dict[str, Any]]:
    """Verify state, trade the one-time authorization code at OpenRouter, and return (api_key, meta)."""
    clean_code = (code or "").strip()
    clean_state = (state or "").strip()
    if not clean_code or len(clean_code) > 512 or _CONTROL.search(clean_code) or any(ch.isspace() for ch in clean_code):
        raise OpenRouterOAuthError("OpenRouter 授權碼格式不正確，請重新登入。", 400)
    if not clean_state:
        raise OpenRouterOAuthError("登入驗證狀態遺失，請再按一次「用 OpenRouter 一鍵登入」。", 400)

    ts = time.time() if now is None else float(now)
    with _lock:
        _prune(ts)
        entry = _pending.pop(clean_state, None)
    if entry is None:
        raise OpenRouterOAuthError("登入驗證已過期或無效，請再按一次「用 OpenRouter 一鍵登入」。", 400)

    payload = {
        "code": clean_code,
        "code_verifier": entry["code_verifier"],
        "code_challenge_method": "S256",
    }
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=EXCHANGE_TIMEOUT, follow_redirects=False) as client:
            resp = await client.post(EXCHANGE_URL, json=payload, headers=headers)
    except httpx.TimeoutException:
        raise OpenRouterOAuthError("連線 OpenRouter 逾時，請稍後再試。", 504)
    except httpx.RequestError as exc:
        logger.warning("OpenRouter OAuth exchange request failed (%s)", type(exc).__name__)
        raise OpenRouterOAuthError("無法連線到 OpenRouter，請檢查網路後再試。", 502)

    if resp.status_code in (400, 401, 403):
        logger.info("OpenRouter OAuth exchange rejected (HTTP %s)", resp.status_code)
        raise OpenRouterOAuthError("OpenRouter 授權碼無效、已用過或已過期，請重新登入。", 400)
    if resp.status_code < 200 or resp.status_code >= 300:
        logger.warning("OpenRouter OAuth exchange failed (HTTP %s)", resp.status_code)
        raise OpenRouterOAuthError(f"OpenRouter 回應失敗（HTTP {resp.status_code}），請稍後再試。", 502)

    try:
        body = resp.json()
    except ValueError:
        raise OpenRouterOAuthError("OpenRouter 回傳格式異常，請稍後再試。", 502)

    key = body.get("key") if isinstance(body, dict) else None
    if not isinstance(key, str) or not key.strip() or _CONTROL.search(key) or any(ch.isspace() for ch in key.strip()):
        raise OpenRouterOAuthError("OpenRouter 沒有回傳有效的 API 金鑰，請稍後再試。", 502)

    meta = {"connection_id": entry["connection_id"], "slot": entry["slot"]}
    return key.strip(), meta
