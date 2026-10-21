from fastapi import APIRouter, HTTPException, Header, Query, BackgroundTasks
from pydantic import BaseModel, HttpUrl
from typing import Optional, Dict, Any
from app.config import settings
from app.pipeline import run_pipeline

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])

class IngestRequest(BaseModel):
    url: str
    category: Optional[str] = None
    async_mode: Optional[bool] = False

def verify_api_key(x_api_key: Optional[str] = Header(None), token: Optional[str] = Query(None)):
    provided_key = x_api_key or token
    if not settings.API_KEY:
        return True
    if provided_key != settings.API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return True

@router.post("")
async def ingest_url(
    req: IngestRequest,
    background_tasks: BackgroundTasks,
    authenticated: bool = Query(True)
):
    url = req.url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        raise HTTPException(status_code=400, detail="Invalid URL protocol")

    # If async_mode requested (e.g. quick return for iOS shortcut)
    if req.async_mode:
        background_tasks.add_task(run_pipeline, url, req.category)
        return {
            "success": True,
            "status": "queued",
            "message": "URL enqueued for two-stage analysis"
        }

    # Otherwise process and return full item
    try:
        item = await run_pipeline(url, req.category)
        return {
            "success": True,
            "status": "completed",
            "item": item
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")
