"""API endpoints for mobile tool evaluation queue, reports, and human decisions."""
from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.database import get_item_by_id
from app.eval.runner import decide_evaluation, enqueue_evaluation_for_item, run_evaluation
from app.eval.store import get_evaluation, get_evaluation_counts, list_evaluations

router = APIRouter(prefix="/api", tags=["Evaluations"])


class TriggerEvaluateRequest(BaseModel):
    user_note: Optional[str] = None
    eval_track: Optional[str] = None
    sync: bool = False


class EvaluationDecisionRequest(BaseModel):
    decision: Literal["approve_l2", "on_demand", "reject", "defer"]
    note: str = ""
    trigger_when: str = ""


@router.get("/evaluations")
async def list_agent_evaluations(
    status: Optional[str] = Query(
        None,
        description="Filter bucket: needs_decision | evaluating | approved_l2 | on_demand | adopted | rejected | failed",
    ),
    limit: int = Query(50, ge=1, le=200),
):
    return {
        "evaluations": list_evaluations(status=status, limit=limit),
        "counts": get_evaluation_counts(),
    }


@router.get("/evaluations/{eval_id}")
async def get_agent_evaluation(eval_id: str):
    ev = get_evaluation(eval_id)
    if not ev:
        raise HTTPException(status_code=404, detail="找不到這筆評估報告")
    return ev


@router.post("/items/{item_id}/evaluate")
async def trigger_item_evaluation(item_id: str, req: Optional[TriggerEvaluateRequest] = None):
    item = get_item_by_id(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="找不到該收藏項目")
    body = req or TriggerEvaluateRequest()
    ev = enqueue_evaluation_for_item(
        item_id=item_id,
        user_note=(body.user_note or "").strip(),
        eval_track=(body.eval_track or "").strip(),
        run_in_background=not body.sync,
    )
    if body.sync:
        ev = await run_evaluation(ev["id"])
    return {
        "success": True,
        "evaluation": ev,
    }


@router.post("/evaluations/{eval_id}/decide")
async def submit_evaluation_decision(eval_id: str, req: EvaluationDecisionRequest):
    updated, writeback = await decide_evaluation(
        eval_id=eval_id,
        decision=req.decision,
        note=req.note,
        trigger_when=req.trigger_when,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="找不到這筆評估報告")
    return {
        "success": True,
        "evaluation": updated,
        "writeback": writeback,
    }
