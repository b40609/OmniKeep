from fastapi import APIRouter, Query
from pydantic import BaseModel
from typing import Optional, Dict, Any

from app.database import log_behavior_event, get_behavior_stats, get_swipe_deck

router = APIRouter(prefix="/api/behavior", tags=["Behavior & Deck"])

VALID_EVENTS = {
    # training labels (swipes)
    "swipe_up", "swipe_down", "swipe_star",
    # non-label interactions
    "snooze", "view", "click", "star", "unstar", "archive", "unarchive",
    "share", "search", "proposal_approve", "proposal_dismiss",
}


class BehaviorEvent(BaseModel):
    event_type: str
    item_id: Optional[str] = None
    proposal_id: Optional[str] = None
    source: str = "pwa"
    meta: Optional[Dict[str, Any]] = None


@router.post("/event")
async def record_event(req: BehaviorEvent):
    if req.event_type not in VALID_EVENTS:
        return {"success": False, "error": f"unknown event_type '{req.event_type}'"}
    rec = log_behavior_event(req.event_type, req.item_id, req.proposal_id,
                             req.source, req.meta)
    return {"success": True, **rec}


@router.get("/deck")
async def deck(limit: int = Query(10, ge=1, le=50)):
    """Un-acted radar items for swipe UIs (Telegram /deck and the future PWA deck)."""
    items = get_swipe_deck(limit=limit)
    return {"count": len(items), "items": items}


@router.get("/stats")
async def stats(days: int = Query(7, ge=1, le=90)):
    return get_behavior_stats(days=days)
