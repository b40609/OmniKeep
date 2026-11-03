"""PWA Web Push: expose the VAPID public key and manage this owner's device subscriptions."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.database import delete_push_subscription, list_push_subscriptions, upsert_push_subscription
from app.push import push_configured, send_push, validate_endpoint, validate_keys

router = APIRouter(prefix="/api/push", tags=["Web Push"])


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class Subscription(BaseModel):
    """Shape of PushSubscription.toJSON() in the browser."""
    endpoint: str
    keys: SubscriptionKeys


class Unsubscribe(BaseModel):
    endpoint: str


@router.get("/config")
async def push_config():
    return {
        "configured": push_configured(),
        "public_key": settings.VAPID_PUBLIC_KEY if push_configured() else "",
        "subscriptions": len(list_push_subscriptions()),
    }


@router.post("/subscribe")
async def subscribe(sub: Subscription, request: Request):
    if not push_configured():
        raise HTTPException(503, "Web Push is not configured (VAPID keys missing)")
    try:
        validate_endpoint(sub.endpoint)
        validate_keys(sub.keys.p256dh, sub.keys.auth)
    except ValueError as exc:
        raise HTTPException(400, "Invalid push subscription") from exc
    upsert_push_subscription(sub.endpoint, sub.keys.p256dh, sub.keys.auth,
                             request.headers.get("user-agent", ""))
    return {"success": True}


@router.post("/unsubscribe")
async def unsubscribe(req: Unsubscribe):
    return {"success": True, "removed": delete_push_subscription(req.endpoint)}


@router.post("/test")
async def test_push():
    if not push_configured():
        raise HTTPException(503, "Web Push is not configured (VAPID keys missing)")
    result = await send_push("OmniKeep 推播測試", "收到這則通知，代表這台裝置的推播已經設定完成。", tag="push-test")
    return {"success": True, **result}
