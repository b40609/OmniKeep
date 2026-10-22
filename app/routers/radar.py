from fastapi import APIRouter, HTTPException, BackgroundTasks, Query
from pydantic import BaseModel, HttpUrl
from typing import Optional, List, Dict, Any
from app.database import (
    get_all_radar_sources,
    get_radar_source,
    save_radar_source,
    delete_radar_source,
    get_all_topic_weights,
    tune_topic_signal,
    get_latest_radar_digests
)
from app.radar.recommender import tune_item_signal
from app.radar.scheduler import run_radar_cycle
from app.radar.digest import generate_radar_digest

router = APIRouter(prefix="/api/radar", tags=["Radar Intelligence Engine"])

# ── Pydantic Request Models ─────────────────────────────────

class SourceCreateRequest(BaseModel):
    name: str
    source_type: str  # 'youtube', 'github', 'rss'
    url: str
    tier: Optional[int] = 2
    check_interval_minutes: Optional[int] = 60

class FeedbackRequest(BaseModel):
    item_id: Optional[str] = None
    topic_tag: Optional[str] = None
    action: str  # 'boost' (Tune Up), 'dampen' (Tune Down), 'mute' (Shield), 'reset'

class ManualDigestRequest(BaseModel):
    item_ids: List[str]
    digest_type: Optional[str] = "custom"

# ── Signal Tuning Feedback Endpoints ────────────────────────

@router.post("/feedback")
async def handle_signal_tuning(req: FeedbackRequest):
    """
    Precision signal tuning (YouTube-style feedback without tacky emojis).
    Supports tuning a single topic tag or all tags of an entire item.
    """
    if req.action not in ["boost", "dampen", "mute", "reset"]:
        raise HTTPException(status_code=400, detail="Action must be 'boost', 'dampen', 'mute', or 'reset'")

    if req.topic_tag:
        res = tune_topic_signal(req.topic_tag, req.action)
        return {"success": True, "result": res}
    elif req.item_id:
        try:
            res = tune_item_signal(req.item_id, req.action)
            return {"success": True, "result": res}
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
    else:
        raise HTTPException(status_code=400, detail="Either 'topic_tag' or 'item_id' must be provided")

@router.get("/topics")
async def list_topics():
    """List all tracked tech tags and their current weights/mute status."""
    topics = get_all_topic_weights()
    return {"success": True, "topics": topics}

# ── Subscriptions Management ────────────────────────────────

@router.get("/sources")
async def list_sources():
    """List all configured intelligence sources with their learned rhythm and status."""
    sources = get_all_radar_sources()
    return {"success": True, "sources": sources}

@router.post("/sources")
async def create_or_update_source(req: SourceCreateRequest):
    """Add a new YouTube channel, GitHub repository/trending, or RSS feed."""
    valid_types = ["youtube", "github", "rss"]
    if req.source_type.lower() not in valid_types:
        raise HTTPException(status_code=400, detail=f"source_type must be one of {valid_types}")

    source_id = save_radar_source({
        "name": req.name,
        "source_type": req.source_type.lower(),
        "url": req.url,
        "tier": req.tier or 2,
        "check_interval_minutes": req.check_interval_minutes or 60
    })
    return {"success": True, "source_id": source_id}

@router.delete("/sources/{source_id}")
async def remove_source(source_id: str):
    ok = delete_radar_source(source_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"success": True, "message": "Source removed"}

# ── Scanning & Digest Endpoints ─────────────────────────────

@router.post("/scan")
async def trigger_radar_scan(
    background_tasks: BackgroundTasks,
    force: bool = Query(False, description="Force scan regardless of schedule or interval"),
    async_mode: bool = Query(True, description="Run scan in background")
):
    """
    Triggers an adaptive radar scan cycle across all active sources.
    Respects learned hot publication windows unless force=True.
    """
    if async_mode:
        background_tasks.add_task(run_radar_cycle, force=force)
        return {"success": True, "status": "queued", "message": "Adaptive radar scan started in background"}
    else:
        res = await run_radar_cycle(force=force)
        return {"success": True, "status": "completed", "result": res}

@router.get("/digests")
async def list_digests(limit: int = 10):
    digests = get_latest_radar_digests(limit=limit)
    return {"success": True, "digests": digests}

@router.post("/digest/generate")
async def create_custom_digest(req: ManualDigestRequest):
    res = await generate_radar_digest(req.item_ids, req.digest_type or "custom")
    return res
