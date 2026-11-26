"""Last outcome of each AI connection's calls, so a dead key shows up in the app.

Entries are keyed by connection: "c<id>" for a connection saved under
設定 › AI 服務商 (app/ai_connections.py). The settings that predate connections
keep their old names ("llm", "embeddings", "gemini", "ollama") while no
connection has replaced them.

Calls already fall back quietly (analysis to a backup connection or a soft
result, embeddings to the local projection). Without this, a revoked key only
ever reached the service log. Each failure carries a Chinese hint
(app/error_translate.py); a failure a retry cannot fix (a disabled key) is
marked action_required and the fallback chain skips that connection until it
is edited or tested again. A connection that hit its rate limit gets a
cooldown during which the chain prefers the next one.
"""
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

SERVICES = ("llm", "embeddings", "gemini", "ollama")
LEGACY_LABELS = {"llm": "AI 分析", "embeddings": "雲端向量", "gemini": "Gemini", "ollama": "本機 Ollama 向量"}

_lock = threading.Lock()
_state: Dict[str, Dict[str, Any]] = {}

# Also catches providers' own half-masked echoes such as "sk-proj****1234".
_KEYLIKE = re.compile(r"\b((?:sk|wk|gsk|xai)-[A-Za-z0-9_\-*]{6,}|AIza[0-9A-Za-z_\-*]{10,})")
_extra_secrets: Dict[str, str] = {}  # secrets of saved connections, registered by app.ai_connections


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def register_secret(name: str, secret: str) -> None:
    """Make redact() hide a connection's key even when it does not look like one."""
    with _lock:
        if secret:
            _extra_secrets[name] = secret
        else:
            _extra_secrets.pop(name, None)


def redact(message: str) -> str:
    """Strip anything that looks like a credential, including the configured ones."""
    text = _KEYLIKE.sub("***", message or "")
    secrets = list(_extra_secrets.values())
    try:
        from app.config import settings
        secrets += [settings.OPENAI_API_KEY, *settings.gemini_keys]
    except Exception:  # noqa: BLE001 - redacting must never fail; saved connections' keys still apply
        pass
    for secret in secrets:
        for part in str(secret).split(","):
            part = part.strip()
            if part and len(part) >= 8:
                text = text.replace(part, "***")
    return text[:300]


def record_success(service: str, label: str = "") -> None:
    with _lock:
        was_quota = _state.get(service, {}).get("kind") == "quota"
        _state[service] = {"ok": True, "at": _now(), "status": None, "message": "", "hint": "",
                           "kind": "", "action_required": False, "fix_url": None,
                           "cooldown_until": 0.0, "cooldown_reason": "",
                           "label": label or _state.get(service, {}).get("label", "")}
    if was_quota:  # the cap was raised or the balance topped up: a new one is worth telling again
        _quota_alerted.discard(service)
        from app import owner_alert
        owner_alert.forget(_QUOTA_ALERT + service)


def record_failure(service: str, status: Optional[int], message: str, label: str = "") -> None:
    from app.error_translate import translate
    clean = redact(message)
    info = translate(status, clean)
    with _lock:
        previous = _state.get(service, {})
        _state[service] = {
            "ok": False, "at": _now(), "status": status, "message": clean,
            "hint": info["hint"], "kind": info["kind"], "action_required": info["action_required"],
            "fix_url": info["fix_url"], "cooldown_until": previous.get("cooldown_until", 0.0),
            "cooldown_reason": previous.get("cooldown_reason", ""),
            "label": label or previous.get("label", ""),
        }
    if info["kind"] == "quota":
        _alert_quota(service, label or previous.get("label", ""), info)


# A spend cap or an empty balance is told to the owner once (app/owner_alert.py), not on every
# refused call; _quota_alerted saves the database lookup after the first one in this process.
_QUOTA_ALERT = "quota."
_quota_alerted: set = set()


def _alert_quota(service: str, label: str, info: Dict[str, Any]) -> None:
    if service in _quota_alerted:
        return
    _quota_alerted.add(service)
    from app import owner_alert  # alert_once never raises
    body = info["hint"] + ("\n" + info["fix_url"] if info.get("fix_url") else "")
    owner_alert.alert_once(_QUOTA_ALERT + service, f"⚠️ {label or service}：額度或支出上限用完", body)


def set_cooldown(service: str, seconds: float, reason: str = "") -> None:
    """Prefer other connections for a while (after a rate limit, an outage, a model that went away).
    `reason` is what the settings page says about it, in the owner's words."""
    with _lock:
        entry = _state.setdefault(service, {"ok": False, "at": _now(), "status": None, "message": "",
                                            "hint": "", "kind": "", "action_required": False,
                                            "fix_url": None, "label": ""})
        until = time.time() + max(0.0, seconds)
        if until >= entry.get("cooldown_until", 0.0):
            entry["cooldown_until"] = until
            entry["cooldown_reason"] = reason


def get(service: str) -> Dict[str, Any]:
    with _lock:
        return dict(_state.get(service, {}))


def unusable(service: str) -> bool:
    """True while the chain should skip this connection: cooling down, or waiting for a person."""
    with _lock:
        entry = _state.get(service)
        if not entry:
            return False
        return bool(entry.get("action_required")) or entry.get("cooldown_until", 0.0) > time.time()


def forget(*services: str) -> None:
    """Drop stale outcomes after the settings for these services change."""
    with _lock:
        for service in services or list(_state):
            _state.pop(service, None)
        for service in services or list(_streaks):
            _streaks.pop(service, None)
        for service in services or list(_quota_alerted):
            _quota_alerted.discard(service)


# Failures in a row per connection (app/providers/chain.py pauses one that keeps failing);
# one success clears it, and so does editing the connection (forget).
_streaks: Dict[str, int] = {}


def bump_streak(service: str) -> int:
    with _lock:
        _streaks[service] = _streaks.get(service, 0) + 1
        return _streaks[service]


def clear_streak(service: str) -> None:
    with _lock:
        _streaks.pop(service, None)


def streak(service: str) -> int:
    with _lock:
        return _streaks.get(service, 0)


def snapshot() -> Dict[str, Dict[str, Any]]:
    now = time.time()
    with _lock:
        out = {}
        for name, value in _state.items():
            entry = dict(value)
            remaining = entry.pop("cooldown_until", 0.0) - now
            entry["cooldown_seconds"] = int(remaining) + 1 if remaining > 0 else 0
            if not entry.get("label"):
                entry["label"] = LEGACY_LABELS.get(name, name)
            out[name] = entry
        return out
