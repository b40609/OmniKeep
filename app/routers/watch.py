from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

from app.config import settings
from app.database import (
    WATCH_PRESETS,
    add_watch_target,
    get_watch_targets,
    get_watch_target,
    update_watch_target,
    delete_watch_target,
    get_proposals,
    decide_proposal,
    get_backup_runs,
)
from app.watch.scanner import scan_target, scan_target_by_id
from app.backup import run_backup_async

router = APIRouter(prefix="/api/watch", tags=["Watch & Proposals"])


class TargetCreate(BaseModel):
    name: str
    path: str
    target_type: str = "folder"          # folder | desktop_risk
    preset: str = "balanced"             # open | balanced | strict | custom
    read_scope: Optional[Dict[str, bool]] = None
    outbound_consent: Optional[Dict[str, bool]] = None


class TargetUpdate(BaseModel):
    name: Optional[str] = None
    path: Optional[str] = None
    preset: Optional[str] = None
    read_scope: Optional[Dict[str, bool]] = None
    outbound_consent: Optional[Dict[str, bool]] = None
    is_active: Optional[bool] = None


class ProposalDecide(BaseModel):
    status: str                          # approved | dismissed
    user_impact: Optional[float] = None
    user_confidence: Optional[float] = None
    user_effort: Optional[float] = None
    reason: str = ""


@router.get("/presets")
async def list_presets():
    return WATCH_PRESETS


@router.get("/targets")
async def list_targets():
    return get_watch_targets()


@router.post("/targets")
async def create_target(req: TargetCreate):
    if req.preset not in WATCH_PRESETS and not (req.read_scope or req.outbound_consent):
        raise HTTPException(400, f"preset must be one of {list(WATCH_PRESETS)} or provide custom toggles")
    if req.preset == "custom" and not (req.read_scope and req.outbound_consent):
        raise HTTPException(400, "custom preset requires explicit read_scope and outbound_consent")
    from pathlib import Path
    if not Path(req.path).exists():
        raise HTTPException(400, f"path does not exist: {req.path}")
    return add_watch_target(req.name, req.path, req.target_type,
                            req.preset if req.preset in WATCH_PRESETS else "custom",
                            req.read_scope, req.outbound_consent)


@router.patch("/targets/{target_id}")
async def patch_target(target_id: str, req: TargetUpdate):
    updates = {k: v for k, v in req.model_dump().items() if v is not None}
    if "preset" in updates and updates["preset"] in WATCH_PRESETS:
        p = WATCH_PRESETS[updates["preset"]]
        updates.setdefault("read_scope", p["read"])
        updates.setdefault("outbound_consent", p["outbound"])
    target = update_watch_target(target_id, updates)
    if not target:
        raise HTTPException(404, "target not found")
    return target


@router.delete("/targets/{target_id}")
async def remove_target(target_id: str):
    if not delete_watch_target(target_id):
        raise HTTPException(404, "target not found")
    return {"success": True}


@router.post("/targets/{target_id}/scan")
async def trigger_scan(target_id: str, background_tasks: BackgroundTasks):
    target = get_watch_target(target_id)
    if not target:
        raise HTTPException(404, "target not found")
    if not target["is_active"]:
        raise HTTPException(400, "target is inactive")
    background_tasks.add_task(scan_target_by_id, target_id)
    return {"success": True, "status": "scanning", "target_id": target_id}


@router.get("/proposals")
async def list_proposals(status: Optional[str] = None, limit: int = 50):
    from app.database import get_item_by_id
    rows = get_proposals(status=status, limit=limit)
    for r in rows:
        item = get_item_by_id(r["item_id"]) or {}
        r["title_l1"] = item.get("title_l1", "")
        r["summary_l1"] = item.get("summary_l1", "")
        r["tech_tags"] = item.get("tech_tags", "")
    return rows


@router.post("/proposals/{proposal_id}/decide")
async def decide(proposal_id: str, req: ProposalDecide):
    corrections = {k: v for k, v in {
        "impact": req.user_impact, "confidence": req.user_confidence,
        "effort": req.user_effort}.items() if v is not None}
    result = decide_proposal(proposal_id, req.status, corrections, req.reason)
    if not result:
        raise HTTPException(400, "invalid proposal id or status (approved|dismissed)")
    return result


# ── Backup endpoints ─────────────────────────────────────────────

@router.post("/backup/run")
async def backup_now(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_backup_async)
    return {"success": True, "status": "queued", "sink": settings.BACKUP_SINK}


@router.get("/backup/status")
async def backup_status():
    return {
        "sink": settings.BACKUP_SINK,
        "backup_dir": settings.BACKUP_DIR,
        "keep": settings.BACKUP_KEEP,
        "backup_hour": settings.BACKUP_HOUR,
        "runs": get_backup_runs(limit=10),
    }
