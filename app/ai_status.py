"""Last outcome of each AI service call, so a dead key shows up in the app.

Calls already fall back quietly (analysis to a soft result, embeddings to the
local projection). Without this, a revoked key only ever reached the service log.
"""
import re
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

SERVICES = ("llm", "embeddings", "gemini", "ollama")

_lock = threading.Lock()
_state: Dict[str, Dict[str, Any]] = {}

# Also catches providers' own half-masked echoes such as "sk-proj****1234".
_KEYLIKE = re.compile(r"\b(sk-[A-Za-z0-9_\-*]{6,}|AIza[0-9A-Za-z_\-*]{10,})")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(message: str) -> str:
    """Strip anything that looks like a credential, including the configured ones."""
    text = _KEYLIKE.sub("***", message or "")
    try:
        from app.config import settings
        for secret in (settings.OPENAI_API_KEY, *settings.gemini_keys):
            if secret and len(secret) >= 8:
                text = text.replace(secret, "***")
    except Exception:
        pass
    return text[:300]


def record_success(service: str) -> None:
    with _lock:
        _state[service] = {"ok": True, "at": _now(), "status": None, "message": ""}


def record_failure(service: str, status: Optional[int], message: str) -> None:
    with _lock:
        _state[service] = {"ok": False, "at": _now(), "status": status, "message": redact(message)}


def forget(*services: str) -> None:
    """Drop stale outcomes after the settings for these services change."""
    with _lock:
        for service in services or SERVICES:
            _state.pop(service, None)


def snapshot() -> Dict[str, Dict[str, Any]]:
    with _lock:
        return {name: dict(value) for name, value in _state.items()}
