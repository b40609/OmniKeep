"""Shared authentication for REST and every remote MCP transport."""
import hashlib
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import settings


def configured_key() -> str:
    key = settings.API_KEY.strip()
    # Reject short/default credentials without retaining the old value in code.
    return key if len(key) >= 32 and len(set(key)) >= 12 else ""


def authenticated(headers) -> bool:
    key = configured_key()
    if not key:
        return False
    scheme, _, token = headers.get("authorization", "").partition(" ")
    provided = token.strip() if scheme.lower() == "bearer" else headers.get("x-api-key", "")
    return secrets.compare_digest(hashlib.sha256(provided.encode()).digest(),
                                  hashlib.sha256(key.encode()).digest())


async def verify_api_key(request: Request, call_next):
    """Default-deny HTTP gate, including mounted apps and future routes."""
    path = request.url.path
    public = (
        request.method in {"GET", "HEAD"}
        and (path in {"/", "/health"} or path.startswith("/static/"))
    ) or (request.method == "POST" and path == "/api/line/webhook")
    preflight = (
        request.method == "OPTIONS"
        and request.headers.get("origin")
        and request.headers.get("access-control-request-method")
    )
    if not public and not preflight:
        if not configured_key():
            return JSONResponse(
                status_code=503,
                content={"error": "Configure a strong API_KEY (32+ characters)"},
                headers={"Cache-Control": "no-store"},
            )
        if not authenticated(request.headers):
            return JSONResponse(
                status_code=401, content={"error": "Unauthorized"},
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )
    response = await call_next(request)
    if not public:
        response.headers["Cache-Control"] = "no-store"
    return response
