"""SQLite persistence and status transitions for item_evaluations."""
from __future__ import annotations

import json
import uuid
from contextlib import closing
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.database import get_db_connection
from app.eval.security import badge_meta

_STATUS_TO_AGENT_STATUS = {
    "approve_l2": "approved_l2",
    "approved_l2": "approved_l2",
    "on_demand": "on_demand",
    "reject": "rejected",
    "rejected": "rejected",
    "adopted": "adopted",
    "defer": "needs_decision",
}

_CANONICAL_DECISION = {
    "approve_l2": "approve_l2",
    "approved_l2": "approve_l2",
    "on_demand": "on_demand",
    "reject": "reject",
    "rejected": "reject",
    "adopted": "adopted",
    "defer": "defer",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(raw: Any, default: Any) -> Any:
    if isinstance(raw, type(default)):
        return raw
    if not raw:
        return default
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, type(default)) else default
    except Exception:
        return default


def _hydrate_eval(row) -> Dict[str, Any]:
    d = dict(row)
    d["l0"] = _load_json(d.get("l0_json"), {})
    d["l1"] = _load_json(d.get("l1_json"), {})
    d["l2_request"] = _load_json(d.get("l2_request_json"), {})
    d["l2_result"] = _load_json(d.get("l2_result_json"), {})
    d["community_counterpoints"] = _load_json(d.get("community_counterpoints_json"), [])
    d["security_badge_meta"] = badge_meta(d.get("security_badge") or "")
    return d


_SELECT_JOIN = """
    SELECT e.*,
           i.title_l1 AS item_title,
           i.summary_l1 AS item_summary,
           i.url AS item_url,
           i.category_name AS category_name,
           i.tech_tags AS item_tech_tags,
           i.user_note AS user_note,
           i.agent_status AS agent_status,
           i.intent AS item_intent
    FROM item_evaluations e
    JOIN items i ON i.id = e.item_id
"""


def create_evaluation(
    item_id: str,
    eval_track: str = "tool",
    adapter: str = "omnikit",
    target_repo: str = "",
    target_url: str = "",
    community_counterpoints: Optional[List[Dict[str, Any]]] = None,
    status: str = "queued",
) -> Dict[str, Any]:
    """Insert a new item_evaluations row and return its hydrated representation."""
    eval_id = f"eval_{uuid.uuid4().hex[:12]}"
    now = _now_iso()
    cp_json = json.dumps(community_counterpoints or [], ensure_ascii=False)
    with closing(get_db_connection()) as conn, conn:
        conn.execute(
            """
            INSERT INTO item_evaluations (
                id, item_id, eval_track, adapter, status,
                target_repo, target_url, community_counterpoints_json,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                eval_id,
                item_id,
                eval_track or "tool",
                adapter or "omnikit",
                status or "queued",
                target_repo or "",
                target_url or "",
                cp_json,
                now,
                now,
            ),
        )
    return get_evaluation(eval_id)  # type: ignore[return-value]


def get_evaluation(eval_id: str) -> Optional[Dict[str, Any]]:
    with closing(get_db_connection()) as conn:
        row = conn.execute(f"{_SELECT_JOIN} WHERE e.id = ?", (eval_id,)).fetchone()
    return _hydrate_eval(row) if row else None


def get_latest_evaluation_for_item(item_id: str) -> Optional[Dict[str, Any]]:
    with closing(get_db_connection()) as conn:
        row = conn.execute(
            f"{_SELECT_JOIN} WHERE e.item_id = ? ORDER BY e.created_at DESC, e.rowid DESC LIMIT 1",
            (item_id,),
        ).fetchone()
    return _hydrate_eval(row) if row else None


def list_evaluations(status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    """List evaluations filtered by queue status or final agent status."""
    where = ["(i.merged_into_id IS NULL OR i.merged_into_id = '')"]
    params: Dict[str, Any] = {"limit": max(1, min(limit, 200))}
    key = (status or "").strip().lower()
    if key == "needs_decision":
        where.append("(i.agent_status = 'needs_decision' OR (e.status = 'ready' AND (e.decision IS NULL OR e.decision = '' OR e.decision = 'defer')))")
    elif key == "evaluating":
        where.append("(e.status IN ('queued', 'running_l0', 'running_l1') OR i.agent_status IN ('queued', 'evaluating'))")
    elif key in ("approved_l2", "on_demand", "adopted", "rejected"):
        where.append("i.agent_status = :agent_status")
        params["agent_status"] = key
    elif key == "failed":
        where.append("(e.status = 'failed' OR i.agent_status = 'eval_failed')")

    sql = f"""
        {_SELECT_JOIN}
        WHERE {' AND '.join(where)}
          AND e.id = (
              SELECT e2.id FROM item_evaluations e2
              WHERE e2.item_id = e.item_id
              ORDER BY e2.created_at DESC, e2.rowid DESC
              LIMIT 1
          )
        ORDER BY e.updated_at DESC, e.rowid DESC
        LIMIT :limit
    """
    with closing(get_db_connection()) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_hydrate_eval(r) for r in rows]


def get_evaluation_counts() -> Dict[str, int]:
    """Count latest evaluations per queue bucket."""
    sql = """
        SELECT e.status AS eval_status, e.decision AS decision, i.agent_status AS agent_status
        FROM item_evaluations e
        JOIN items i ON i.id = e.item_id
        WHERE (i.merged_into_id IS NULL OR i.merged_into_id = '')
          AND e.id = (
              SELECT e2.id FROM item_evaluations e2
              WHERE e2.item_id = e.item_id
              ORDER BY e2.created_at DESC, e2.rowid DESC
              LIMIT 1
          )
    """
    counts = {
        "needs_decision": 0,
        "evaluating": 0,
        "approved_l2": 0,
        "on_demand": 0,
        "adopted": 0,
        "rejected": 0,
        "failed": 0,
        "total": 0,
    }
    with closing(get_db_connection()) as conn:
        rows = conn.execute(sql).fetchall()
    for row in rows:
        counts["total"] += 1
        agent_st = row["agent_status"] or ""
        eval_st = row["eval_status"] or ""
        decision = row["decision"] or ""
        if eval_st == "failed" or agent_st == "eval_failed":
            counts["failed"] += 1
        elif eval_st in ("queued", "running_l0", "running_l1") or agent_st in ("queued", "evaluating"):
            counts["evaluating"] += 1
        elif agent_st in ("approved_l2", "on_demand", "adopted", "rejected"):
            counts[agent_st] += 1
        elif agent_st == "needs_decision" or (eval_st == "ready" and decision in ("", "defer")):
            counts["needs_decision"] += 1
    return counts


def update_evaluation(eval_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    """Update allowed fields on an evaluation row."""
    allowed = {
        "eval_track",
        "adapter",
        "status",
        "target_repo",
        "target_url",
        "security_badge",
        "l0_json",
        "l1_json",
        "l2_request_json",
        "l2_result_json",
        "community_counterpoints_json",
        "decision",
        "decision_note",
        "trigger_when",
        "decided_at",
        "error_message",
    }
    updates: Dict[str, Any] = {}
    for k, v in fields.items():
        if k not in allowed:
            raise ValueError(f"Unsupported evaluation field: {k}")
        if k.endswith("_json") and not isinstance(v, str):
            updates[k] = json.dumps(v, ensure_ascii=False)
        else:
            updates[k] = v
    if not updates:
        return get_evaluation(eval_id)
    updates["updated_at"] = _now_iso()
    cols = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values()) + [eval_id]
    with closing(get_db_connection()) as conn, conn:
        conn.execute(f"UPDATE item_evaluations SET {cols} WHERE id = ?", vals)
    return get_evaluation(eval_id)


def apply_decision(
    eval_id: str,
    decision: str,
    note: str = "",
    trigger_when: str = "",
    l2_request: Optional[Dict[str, Any]] = None,
    l2_result: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Persist a decision on both item_evaluations and items.agent_status."""
    key = (decision or "").strip().lower()
    if key not in _STATUS_TO_AGENT_STATUS:
        raise ValueError(f"Unsupported decision: {decision}")

    existing = get_evaluation(eval_id)
    if not existing:
        return None

    now = _now_iso()
    next_agent_status = _STATUS_TO_AGENT_STATUS[key]
    canon_decision = _CANONICAL_DECISION[key]
    eval_updates: Dict[str, Any] = {
        "decision": canon_decision,
        "decision_note": note.strip(),
        "trigger_when": trigger_when.strip(),
        "decided_at": now,
        "updated_at": now,
    }
    if existing.get("status") in ("queued", "running_l0", "running_l1"):
        eval_updates["status"] = "ready"
    if l2_request is not None:
        eval_updates["l2_request_json"] = json.dumps(l2_request, ensure_ascii=False)
    if l2_result is not None:
        eval_updates["l2_result_json"] = json.dumps(l2_result, ensure_ascii=False)

    cols = ", ".join(f"{k} = ?" for k in eval_updates)
    vals = list(eval_updates.values()) + [eval_id]
    with closing(get_db_connection()) as conn, conn:
        conn.execute(f"UPDATE item_evaluations SET {cols} WHERE id = ?", vals)
        conn.execute(
            "UPDATE items SET agent_status = ?, updated_at = ? WHERE id = ?",
            (next_agent_status, now, existing["item_id"]),
        )
    return get_evaluation(eval_id)


def search_on_demand_items(query: str = "", limit: int = 10) -> List[Dict[str, Any]]:
    """Retrieve items marked as on_demand for Progressive Disclosure recall."""
    sql = f"""
        {_SELECT_JOIN}
        WHERE i.agent_status = 'on_demand'
          AND (i.merged_into_id IS NULL OR i.merged_into_id = '')
          AND e.id = (
              SELECT e2.id FROM item_evaluations e2
              WHERE e2.item_id = i.id
              ORDER BY e2.created_at DESC, e2.rowid DESC
              LIMIT 1
          )
        ORDER BY e.decided_at DESC, i.updated_at DESC
    """
    with closing(get_db_connection()) as conn:
        rows = [_hydrate_eval(r) for r in conn.execute(sql).fetchall()]

    terms = [t.casefold() for t in (query or "").strip().split() if t.strip()]
    if not terms:
        return rows[:max(1, limit)]

    scored: List[tuple] = []
    for row in rows:
        haystack = " ".join([
            str(row.get("trigger_when") or ""),
            str(row.get("decision_note") or ""),
            str(row.get("item_title") or ""),
            str(row.get("item_summary") or ""),
            str(row.get("target_repo") or ""),
            str(row.get("item_tech_tags") or ""),
            str(row.get("user_note") or ""),
        ]).casefold()
        trigger_text = str(row.get("trigger_when") or "").casefold()
        hits = sum(2 if t in trigger_text else (1 if t in haystack else 0) for t in terms)
        if hits > 0:
            scored.append((hits, row))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    return [pair[1] for pair in scored[:max(1, limit)]]
