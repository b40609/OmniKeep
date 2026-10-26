from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.network import validate_url, UnsafeURL
from app.pipeline import run_pipeline
from app.database import create_ingest_task

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])

class IngestRequest(BaseModel):
    url: Optional[str] = None
    content: Optional[str] = None
    text: Optional[str] = None
    category: Optional[str] = None
    async_mode: Optional[bool] = False

@router.post("")
async def ingest_url(
    req: IngestRequest,
):
    raw_input = req.content or req.text or req.url
    if not raw_input or not raw_input.strip():
        raise HTTPException(status_code=400, detail="請提供網址或文字段落內容 (URL or text is required)")

    clean_input = raw_input.strip()
    if req.url or clean_input.lower().startswith(("http://", "https://")):
        try:
            validate_url(clean_input)
        except UnsafeURL as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # If async_mode requested (e.g. quick return for iOS shortcut / fast ingestion)
    if req.async_mode:
        task = create_ingest_task(url=clean_input, source="api")
        return {
            "success": True,
            "status": "queued",
            "task_id": task["id"],
            "message": "Content enqueued in persistent queue for two-stage analysis"
        }

    # Otherwise process and return full item
    try:
        item = await run_pipeline(clean_input, req.category)
        return {
            "success": True,
            "status": "completed",
            "item": item
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Ingestion failed") from exc
