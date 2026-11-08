"""One-time codes that sign a phone in: shown on a signed-in screen, scanned or typed on the phone.

An iPhone home-screen app keeps its own storage apart from Safari, so a key handed over in a link
signs only Safari in. A short code works in both places: the home-screen app's sign-in page takes
it too. The code stands in for the key and never contains it. One code at a time; it is used once,
expires after TTL seconds and is dropped after MAX_WRONG wrong tries. A restart forgets it.
"""
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # no 0/O or 1/I/L to misread
LENGTH = 8
TTL = 300
MAX_WRONG = 5

_lock = threading.Lock()
_state: Dict[str, Any] = {"code": "", "expires": 0.0, "wrong": 0, "used_at": 0.0}


def normalise(code: str) -> str:
    """What the phone typed, without spaces, dashes or case."""
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def create(now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    code = "".join(secrets.choice(ALPHABET) for _ in range(LENGTH))
    with _lock:
        _state.update(code=code, expires=now + TTL, wrong=0, used_at=0.0)
    return {"code": code, "expires_at": now + TTL}


def cancel() -> None:
    with _lock:
        _state.update(code="", expires=0.0, wrong=0, used_at=0.0)


def status(now: Optional[float] = None) -> Dict[str, Any]:
    now = time.time() if now is None else now
    with _lock:
        active = bool(_state["code"]) and now < _state["expires"]
        return {"active": active, "expires_at": _state["expires"] if active else 0.0, "used_at": _state["used_at"]}


def redeem(code: str, now: Optional[float] = None) -> bool:
    """True once for the current code; a wrong, expired or used code is False."""
    now = time.time() if now is None else now
    given = normalise(code)
    with _lock:
        expected = _state["code"]
        if not expected:
            return False
        if now >= _state["expires"]:
            _state.update(code="", expires=0.0)
            return False
        if secrets.compare_digest(given.encode(), expected.encode()):
            _state.update(code="", expires=0.0, wrong=0, used_at=now)
            return True
        _state["wrong"] += 1
        if _state["wrong"] >= MAX_WRONG:
            _state.update(code="", expires=0.0)
        return False


def phone_urls() -> List[str]:
    """Addresses a phone can open: this machine's Tailscale name, when the tailscale CLI is here."""
    from app.mcp_http import _tailscale_names
    names = _tailscale_names()
    dns = next((n.rstrip(".") for n in names if n and not n[0].isdigit() and not n.startswith("[")), "")
    return [f"https://{dns}"] if dns else []
