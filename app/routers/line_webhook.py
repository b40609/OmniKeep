import json
import logging
from fastapi import APIRouter, Request, Header, HTTPException, BackgroundTasks
from app.bot.line_bot import verify_line_signature, process_line_event

logger = logging.getLogger("omnikeep.line_router")

router = APIRouter(prefix="/api/line", tags=["LINE Bot"])

@router.post("/webhook")
async def line_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_line_signature: str = Header(None)
):
    body = await request.body()

    # 1. Verify LINE Signature
    if not verify_line_signature(body, x_line_signature):
        logger.warning("LINE Webhook 簽章驗證失敗 (Invalid signature)")
        raise HTTPException(status_code=400, detail="Invalid LINE Signature")

    # 2. Parse Webhook Events
    try:
        data = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    events = data.get("events", [])
    for event in events:
        # Process in background task to respond to LINE server within < 2 seconds
        background_tasks.add_task(process_line_event, event)

    return {"status": "ok", "events_count": len(events)}
