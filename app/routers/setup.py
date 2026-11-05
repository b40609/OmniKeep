"""Setup routes behind the agent-driven first run (app/setup_flow.py, docs/agent_setup_skill_design.md).

The MCP tools call the writing routes here, so a change made from an agent
takes effect in the running service at once. Every route sits behind the API key gate.
"""
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app import setup_flow

router = APIRouter(prefix="/api/setup", tags=["Setup"])


class PeekRequest(BaseModel):
    url: str
    max_chars: int = 3000


class CheckSourcesRequest(BaseModel):
    sources: List[Any] = Field(default_factory=list)
    recent: int = 3


class PreviewRequest(BaseModel):
    answers: Any = None


class ApplyRequest(BaseModel):
    answers: Any = None
    confirm_code: str = ""


class OpmlRequest(BaseModel):
    content: str = Field(min_length=1, max_length=setup_flow.MAX_IMPORT_BYTES)


def _bad_request(exc: setup_flow.SetupError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/scan")
async def scan():
    return await setup_flow.scan()


@router.post("/peek")
async def peek(req: PeekRequest):
    try:
        return await setup_flow.peek(req.url, req.max_chars)
    except setup_flow.SetupError as exc:
        raise _bad_request(exc) from exc


@router.post("/check-sources")
async def check_sources(req: CheckSourcesRequest):
    try:
        return await setup_flow.check_sources(req.sources, req.recent)
    except setup_flow.SetupError as exc:
        raise _bad_request(exc) from exc


@router.get("/provider-options")
async def provider_options():
    return await setup_flow.list_provider_options()


@router.post("/preview")
async def preview(req: PreviewRequest):
    try:
        return setup_flow.preview(req.answers)
    except setup_flow.SetupError as exc:
        raise _bad_request(exc) from exc


@router.post("/apply")
async def apply(req: ApplyRequest) -> Dict[str, Any]:
    try:
        result = setup_flow.apply(req.answers, req.confirm_code)
    except setup_flow.SetupError as exc:
        raise _bad_request(exc) from exc
    # The scheduler re-reads the toggle and interval now instead of at its next tick.
    from app.radar.scheduler import radar_scheduler
    radar_scheduler.wake()
    return result


@router.post("/run-radar")
async def run_radar():
    return await setup_flow.run_radar_once()


@router.post("/import-opml")
async def import_opml(req: OpmlRequest):
    try:
        return setup_flow.import_opml(req.content)
    except setup_flow.SetupError as exc:
        raise _bad_request(exc) from exc
