"""Requests and tokens per AI connection per day, shown in 設定 › AI 服務商.

Free tiers come with allowances that run out silently (Inception's one-time 100M tokens,
Itera's 30M a month, Requesty's 200 requests a day): counting what OmniKeep itself sent
lets the settings page show how much is left. Counts are local estimates, not the
provider's bill: requests made elsewhere with the same key are not seen, and a provider
that reports no usage adds requests without tokens. Recording never raises.
"""
import logging
import re
from contextlib import closing
from datetime import date, datetime
from typing import Any, Dict, Optional

from app.database import get_db_connection

logger = logging.getLogger("omnikeep.ai_usage")

_CONNECTION_KEY = re.compile(r"^c(\d+)$")
PERIODS = ("day", "month", "once")


def _today() -> str:
    return datetime.now().astimezone().date().isoformat()


def _connection_id(status_key: str) -> Optional[int]:
    m = _CONNECTION_KEY.match(status_key or "")
    return int(m.group(1)) if m else None


def _tokens(usage: Any, name: str) -> int:
    value = usage.get(name) if isinstance(usage, dict) else getattr(usage, name, None)
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _add(status_key: str, ok: bool, prompt: int = 0, completion: int = 0) -> None:
    connection_id = _connection_id(status_key)
    if connection_id is None:
        return  # the settings that predate connections have no row to show it on
    try:
        with closing(get_db_connection()) as db, db:
            db.execute(
                "INSERT INTO ai_usage (connection_id, day, requests, failures, prompt_tokens, completion_tokens) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(connection_id, day) DO UPDATE SET "
                "requests = requests + excluded.requests, failures = failures + excluded.failures, "
                "prompt_tokens = prompt_tokens + excluded.prompt_tokens, "
                "completion_tokens = completion_tokens + excluded.completion_tokens",
                (connection_id, _today(), 1 if ok else 0, 0 if ok else 1, prompt, completion))
    except Exception as exc:  # usage is a convenience; it must never break an analysis
        logger.debug("ai_usage record failed: %s", exc)


def record_success(status_key: str, response: Any) -> None:
    usage = response.get("usage") if isinstance(response, dict) else getattr(response, "usage", None)
    _add(status_key, True, _tokens(usage, "prompt_tokens"), _tokens(usage, "completion_tokens"))


def record_failure(status_key: str) -> None:
    _add(status_key, False)


def _totals(db, connection_id: int, since: Optional[str]) -> Dict[str, int]:
    sql = ("SELECT COALESCE(SUM(requests), 0), COALESCE(SUM(failures), 0), COALESCE(SUM(prompt_tokens), 0), "
           "COALESCE(SUM(completion_tokens), 0) FROM ai_usage WHERE connection_id = ?")
    params: list = [connection_id]
    if since:
        sql += " AND day >= ?"
        params.append(since)
    requests, failures, prompt, completion = db.execute(sql, params).fetchone()
    return {"requests": requests, "failures": failures, "tokens": prompt + completion,
            "prompt_tokens": prompt, "completion_tokens": completion}


def summary(connection_id: int, quota: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Today, this month and all time, plus how much of the card's allowance is used."""
    today = _today()
    month_start = date.fromisoformat(today).replace(day=1).isoformat()
    try:
        with closing(get_db_connection()) as db:
            out = {"today": _totals(db, connection_id, today), "month": _totals(db, connection_id, month_start),
                   "total": _totals(db, connection_id, None)}
    except Exception as exc:
        logger.debug("ai_usage summary failed: %s", exc)
        return {}
    if quota and quota.get("period") in PERIODS:
        window = {"day": "today", "month": "month", "once": "total"}[quota["period"]]
        unit = "tokens" if quota.get("tokens") else "requests"
        limit = int(quota.get(unit) or 0)
        if limit > 0:
            used = out[window][unit]
            out["quota"] = {"unit": unit, "period": quota["period"], "limit": limit, "used": used,
                            "percent": round(min(used / limit, 1.0) * 100, 1)}
    return out
