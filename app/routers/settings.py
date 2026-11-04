"""Settings page API: read, save, test and import settings without touching .env.

Credentials are write-only: responses carry "configured" and the last four
characters, never the value. Every route sits behind the API key gate.
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import ai_status, app_settings, services, vapid
from app.config import settings
from app.connection_checks import CHECKS, run_check

router = APIRouter(prefix="/api/settings", tags=["Settings"])


class SettingsUpdate(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)
    reset: List[str] = Field(default_factory=list)


class CheckRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


async def _after_change(changed: List[str]) -> None:
    if "TELEGRAM_BOT_TOKEN" in changed:
        await services.restart_telegram()


@router.get("")
async def read_settings():
    # Pick up values saved by another process (a separately run bot, the MCP server).
    await _after_change(app_settings.apply_overrides())
    return app_settings.describe()


@router.put("")
async def update_settings(body: SettingsUpdate):
    try:
        changed = app_settings.save(body.values, body.reset)
    except app_settings.SettingsError as exc:
        first = next(iter(exc.errors.values()), "設定有誤")
        return JSONResponse(status_code=400, content={"detail": first, "errors": exc.errors})
    await _after_change(changed)
    return {**app_settings.describe(), "changed": changed}


@router.post("/import-env")
async def import_env_values():
    imported = app_settings.import_env()
    return {**app_settings.describe(), "imported": imported}


@router.get("/audit")
async def settings_audit(limit: int = Query(50, ge=1, le=200), before: Optional[int] = Query(None, ge=1)):
    """Which setting changed, how and when; values are never recorded."""
    return app_settings.audit_log(limit, before)


@router.post("/push/regenerate")
async def regenerate_push_keys():
    """New Web Push key pair; every device has to switch push on again."""
    removed = vapid.regenerate()
    return {**app_settings.describe(), "removed_subscriptions": removed}


@router.post("/check/{service}")
async def check_connection(service: str, body: CheckRequest):
    if service not in CHECKS:
        raise HTTPException(404, "Unknown service")
    return await run_check(service, body.values)


def _needs_setup() -> bool:
    if settings.PRIMARY_LLM_PROVIDER == "gemini":
        return not settings.gemini_keys
    # Local servers such as Ollama need no key; the default OpenAI address does.
    return not settings.OPENAI_API_KEY and "api.openai.com" in settings.OPENAI_BASE_URL


@router.get("/status")
async def service_status():
    return {
        "services": ai_status.snapshot(),
        "needs_setup": _needs_setup(),
        "undecryptable": app_settings.describe()["secret_key"]["undecryptable"],
    }
