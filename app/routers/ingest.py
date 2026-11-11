import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.error_translate import classify, failure_message, is_ai_failure
from app.network import validate_url, UnsafeURL
from app.pipeline import run_pipeline
from app.database import create_ingest_task

logger = logging.getLogger("omnikeep.ingest")

router = APIRouter(prefix="/api/ingest", tags=["Ingestion"])

class IngestRequest(BaseModel):
    url: Optional[str] = None
    content: Optional[str] = None
    text: Optional[str] = None
    category: Optional[str] = None
    async_mode: Optional[bool] = False
    # The page's title and description as the user's browser shows them (bookmarklet).
    page_title: Optional[str] = None
    page_description: Optional[str] = None


def _page_hint(value: Optional[str], limit: int) -> str:
    return " ".join((value or "").split())[:limit]


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
        item = await run_pipeline(clean_input, req.category,
                                  page_title=_page_hint(req.page_title, 300),
                                  page_description=_page_hint(req.page_description, 1000))
        return {
            "success": True,
            "status": "completed",
            "item": item
        }
    except UnsafeURL as exc:  # a redirect or an embedded link the pipeline refused
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Ingestion failed for %s", clean_input[:200])
        raise HTTPException(status_code=_failure_status(exc), detail=failure_message(exc)) from exc


def _failure_status(exc: Exception) -> int:
    """503 when the AI is busy or unreachable for now (worth trying again later), 502 when it
    answered but cannot be used as it is (key, model, unusable output), 500 for the rest.
    Never 401 / 403: callers read those as OmniKeep refusing their own key."""
    if not is_ai_failure(exc):
        return 500
    return 503 if classify(exc)["kind"] in ("rate_limit", "server", "connection") else 502
