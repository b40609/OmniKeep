"""Background evaluation orchestration (Layer 0 + Layer 1 only)."""
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.background import follow_up_pool
from app.database import get_item_by_id, get_sub_entities_for_parent, update_item_field
from app.eval.adapter import build_layer2_request, get_evaluator_adapter
from app.eval.security import BADGE_EXECUTABLE
from app.eval.store import (
    apply_decision,
    create_evaluation,
    get_evaluation,
    get_latest_evaluation_for_item,
    update_evaluation,
)
from app.parsers.github_repo import repo_from_url

logger = logging.getLogger("omnikeep.eval.runner")

_GITHUB_URL_RE = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.I)


def infer_eval_track(item: Dict[str, Any], explicit_track: str = "") -> str:
    """Determine evaluation track: V1 executes 'tool' end-to-end and reserves 'rule'/'project'."""
    explicit = (explicit_track or item.get("eval_track") or "").strip().lower()
    if explicit in ("tool", "rule", "project"):
        return explicit
    if (item.get("intent") or "").strip().lower() == "project_ref":
        return "project"
    return "tool"


def extract_eval_target(item: Dict[str, Any]) -> Tuple[str, str]:
    """Resolve (target_repo, target_url) prioritizing GitHub repositories over social wrapper posts."""
    url = str(item.get("url") or "").strip()
    repo_tuple = repo_from_url(url)
    if repo_tuple:
        return f"{repo_tuple[0]}/{repo_tuple[1]}", f"https://github.com/{repo_tuple[0]}/{repo_tuple[1]}"

    for sub in get_sub_entities_for_parent(str(item.get("id") or "")):
        sub_url = str(sub.get("target_canonical_url") or "").strip()
        if "[疑似候選]" in (sub.get("mention_context") or ""):
            continue
        sub_repo = repo_from_url(sub_url)
        if sub_repo:
            return f"{sub_repo[0]}/{sub_repo[1]}", f"https://github.com/{sub_repo[0]}/{sub_repo[1]}"

    match = _GITHUB_URL_RE.search(str(item.get("content_raw") or ""))
    if match:
        slug = match.group(1).removesuffix(".git")
        return slug, f"https://github.com/{slug}"

    return "", url


async def run_evaluation(eval_id: str) -> Dict[str, Any]:
    """Execute read-only L0/L1 evaluation for an evaluation row and notify via Web Push."""
    evaluation = get_evaluation(eval_id)
    if not evaluation:
        raise ValueError(f"Evaluation not found: {eval_id}")

    item = get_item_by_id(evaluation["item_id"])
    if not item:
        raise ValueError(f"Item not found for evaluation {eval_id}: {evaluation['item_id']}")

    adapter = get_evaluator_adapter()
    target_repo, target_url = evaluation.get("target_repo") or "", evaluation.get("target_url") or ""
    if not target_url:
        target_repo, target_url = extract_eval_target(item)

    update_evaluation(
        eval_id,
        status="running_l0",
        adapter=adapter.name,
        target_repo=target_repo,
        target_url=target_url,
    )
    update_item_field(item["id"], {"agent_status": "evaluating", "eval_track": evaluation["eval_track"]})

    counterpoints: List[Dict[str, Any]] = evaluation.get("community_counterpoints") or item.get("community_counterpoints") or []
    request_payload = {
        "schema_version": "1.0",
        "request_id": eval_id,
        "source_item_id": item["id"],
        "eval_track": evaluation["eval_track"],
        "target_url": target_url,
        "target_repo": target_repo,
        "user_note": item.get("user_note") or "",
        "source_summary": item.get("summary_l1") or "",
        "community_counterpoints": counterpoints,
        "max_layer": 1,
    }

    try:
        result = await adapter.evaluate(request_payload)
        l1 = dict(result.get("layer1") or {})
        if result.get("slot_comparison") and "slot_comparison" not in l1:
            l1["slot_comparison"] = result["slot_comparison"]
        if result.get("suggested_action") and "suggested_action" not in l1:
            l1["suggested_action"] = result["suggested_action"]

        updated = update_evaluation(
            eval_id,
            status="ready",
            adapter=adapter.name,
            target_repo=(result.get("layer0") or {}).get("repo") or target_repo,
            target_url=(result.get("layer0") or {}).get("url") or target_url,
            security_badge=result.get("security_badge") or BADGE_EXECUTABLE,
            l0_json=result.get("layer0") or {},
            l1_json=l1,
            error_message="",
        )
        update_item_field(item["id"], {"agent_status": "needs_decision"})
    except Exception as exc:
        logger.warning("[Eval:Runner] Evaluation %s failed: %s", eval_id, exc)
        updated = update_evaluation(
            eval_id,
            status="failed",
            adapter=adapter.name,
            error_message=str(exc)[:600],
        )
        update_item_field(item["id"], {"agent_status": "eval_failed"})

    if updated:
        try:
            from app.push import notify_evaluation_ready
            await notify_evaluation_ready(updated, item)
        except Exception as push_exc:
            logger.warning("[Eval:Runner] Push notification failed for %s: %s", eval_id, push_exc)
    return updated or {}


def enqueue_evaluation_for_item(
    item_id: str,
    user_note: str = "",
    eval_track: str = "",
    run_in_background: bool = True,
) -> Dict[str, Any]:
    """Create a queued evaluation for an item and schedule background execution if requested."""
    item = get_item_by_id(item_id)
    if not item:
        raise ValueError(f"Item not found: {item_id}")

    item_updates: Dict[str, Any] = {"intent": "agent_eval", "agent_status": "queued"}
    if user_note and user_note.strip():
        item_updates["user_note"] = user_note.strip()
    track = infer_eval_track(item, eval_track)
    item_updates["eval_track"] = track
    update_item_field(item_id, item_updates)

    refreshed = get_item_by_id(item_id) or item
    target_repo, target_url = extract_eval_target(refreshed)
    adapter = get_evaluator_adapter()
    evaluation = create_evaluation(
        item_id=item_id,
        eval_track=track,
        adapter=adapter.name,
        target_repo=target_repo,
        target_url=target_url,
        community_counterpoints=refreshed.get("community_counterpoints") or [],
        status="queued",
    )

    if run_in_background:
        eval_id = evaluation["id"]
        if not follow_up_pool.submit(lambda eid=eval_id: run_evaluation(eid)):
            logger.info("[Eval:Runner] follow_up_pool inactive; evaluation %s remains queued", eval_id)
    return evaluation


async def decide_evaluation(
    eval_id: str,
    decision: str,
    note: str = "",
    trigger_when: str = "",
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Record a decision on an evaluation and propagate writeback to the active adapter."""
    evaluation = get_evaluation(eval_id)
    if not evaluation:
        return None, {"synced": False, "reason": "not_found"}

    item = get_item_by_id(evaluation["item_id"])
    key = (decision or "").strip().lower()
    l2_req = build_layer2_request(evaluation, item, note=note) if key in ("approve_l2", "approved_l2") else None
    updated = apply_decision(eval_id, decision=key, note=note, trigger_when=trigger_when, l2_request=l2_req)
    if not updated:
        return None, {"synced": False, "reason": "update_failed"}

    l1 = updated.get("l1") or {}
    payload = {
        "schema_version": "1.0",
        "tool_id": l1.get("tool_id") or updated.get("target_repo") or updated["item_id"],
        "target_repo": updated.get("target_repo") or "",
        "target_url": updated.get("target_url") or (item or {}).get("url") or "",
        "decision": updated.get("decision") or key,
        "decision_note": note.strip(),
        "trigger_when": trigger_when.strip(),
        "source_item_id": updated["item_id"],
        "eval_id": eval_id,
        "decided_at": updated.get("decided_at") or "",
    }
    adapter = get_evaluator_adapter()
    writeback = await adapter.record_decision(payload)
    return updated, writeback


async def decide_item_latest_evaluation(
    item_id: str,
    decision: str,
    note: str = "",
    trigger_when: str = "",
) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """Ensure an evaluation row exists for item_id and apply the decision (used by MCP loop)."""
    item = get_item_by_id(item_id)
    if not item:
        return None, {"synced": False, "reason": "item_not_found"}

    latest = get_latest_evaluation_for_item(item_id)
    if not latest:
        target_repo, target_url = extract_eval_target(item)
        adapter = get_evaluator_adapter()
        latest = create_evaluation(
            item_id=item_id,
            eval_track=infer_eval_track(item),
            adapter=adapter.name,
            target_repo=target_repo,
            target_url=target_url,
            community_counterpoints=item.get("community_counterpoints") or [],
            status="ready",
        )
    return await decide_evaluation(latest["id"], decision=decision, note=note, trigger_when=trigger_when)
