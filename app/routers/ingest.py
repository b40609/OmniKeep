import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.error_translate import classify, failure_message, is_ai_failure
from app.network import validate_url, UnsafeURL
from app.parsers.dead_link import DeadLinkError
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
    # Keep the text as a note even when it holds an address (the 新增 panel's choice).
    as_note: Optional[bool] = False


# A video longer than this is read in the queue even when the caller waits for the result: the
# 2026-11-18 trial's 2-hour video took over 2 minutes (subtitles, screen text, analysis) and the
# caller gave up at 120 s. The web page's 新增 and the API wait; Telegram always uses the queue.
LONG_VIDEO_SECONDS = 20 * 60


async def _long_video(url: str) -> int:
    """The length in seconds of a long YouTube video at this address, or 0 (not one, or not known)."""
    from app.parsers.youtube import fetch_youtube_metadata, is_youtube_shorts_url, is_youtube_url
    if not is_youtube_url(url) or is_youtube_shorts_url(url):
        return 0
    try:
        duration = int((await fetch_youtube_metadata(url)).get("duration") or 0)
    except Exception:
        return 0
    return duration if duration > LONG_VIDEO_SECONDS else 0


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
    as_note = bool(req.as_note) and not req.url
    if not as_note and (req.url or clean_input.lower().startswith(("http://", "https://"))):
        try:
            validate_url(clean_input)
        except UnsafeURL as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    # If async_mode requested (e.g. quick return for iOS shortcut / fast ingestion)
    if req.async_mode:
        task = create_ingest_task(url=clean_input, source="api", category=req.category)
        return {
            "success": True,
            "status": "queued",
            "task_id": task["id"],
            "message": "Content enqueued in persistent queue for two-stage analysis"
        }

    if not as_note and not req.page_title and not req.page_description:
        long_video = await _long_video(clean_input)
        if long_video:
            task = create_ingest_task(url=clean_input, source="api", category=req.category)
            minutes = round(long_video / 60)
            return {
                "success": True,
                "status": "queued",
                "task_id": task["id"],
                "message": f"影片約 {minutes} 分鐘，比較長，改在背景讀：讀完會出現在收件匣，通常要幾分鐘。",
            }

    # Otherwise process and return full item
    try:
        item = await run_pipeline(clean_input, req.category,
                                  page_title=_page_hint(req.page_title, 300),
                                  page_description=_page_hint(req.page_description, 1000),
                                  **({"as_note": True} if as_note else {}))
        return {
            "success": True,
            "status": "completed",
            "item": item
        }
    except UnsafeURL as exc:  # a redirect or an embedded link the pipeline refused
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except DeadLinkError as exc:  # 404, no such domain, a removed video: nothing was saved
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
