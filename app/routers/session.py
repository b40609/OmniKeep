"""
Session Bridge Router — account session visibility & one-click platform login.

Exposes the state of the cookie bridge (cookies.txt / CDP automation Chrome /
legacy extraction) so users can see which platforms are connected and open a
login window without touching the terminal.
"""

import asyncio
import http.cookiejar
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import settings
from app.parsers.cookie_manager import (
    _cdp_reachable,
    _fetch_cdp_cookies,
    ensure_cdp_browser,
    get_cookie_jar,
)

logger = logging.getLogger("omnikeep.session")

router = APIRouter(prefix="/api/session", tags=["Session Bridge"])

# platform id -> (display order, cookie domain keyword, login entry URL)
PLATFORM_DEFS: Dict[str, Dict[str, str]] = {
    "instagram": {"domain": "instagram", "login_url": "https://www.instagram.com/"},
    "facebook": {"domain": "facebook", "login_url": "https://www.facebook.com/"},
    "google": {"domain": "google", "login_url": "https://accounts.google.com/"},
    "x": {"domain": "x.com", "login_url": "https://x.com/login"},
}


class LoginRequest(BaseModel):
    platform: str


def _load_cookie_file_jar() -> Optional[http.cookiejar.CookieJar]:
    cookie_file = settings.BROWSER_COOKIE_FILE
    if not (cookie_file and Path(cookie_file).is_file()):
        return None
    try:
        jar = http.cookiejar.MozillaCookieJar(cookie_file)
        jar.load(ignore_discard=True, ignore_expires=True)
        return jar
    except Exception as e:
        logger.warning(f"[Session] cookie file parse failed: {e}")
        return None


def _platform_snapshot(jar: Optional[http.cookiejar.CookieJar]) -> List[Dict[str, Any]]:
    """Per-platform connection summary derived from cookie domains."""
    result: List[Dict[str, Any]] = []
    for pid, meta in PLATFORM_DEFS.items():
        count = 0
        if jar:
            count = sum(1 for c in jar if meta["domain"] in (c.domain or ""))
        result.append({"id": pid, "connected": count > 0, "cookies": count})
    return result


def _bridge_snapshot() -> Dict[str, Any]:
    cookie_file = settings.BROWSER_COOKIE_FILE
    file_ok = bool(cookie_file) and Path(cookie_file).is_file()
    cdp_ok = _cdp_reachable(settings.BROWSER_CDP_PORT, timeout=0.8)

    mode = "none"
    jar: Optional[http.cookiejar.CookieJar] = None
    if file_ok:
        mode = "cookiefile"
        jar = _load_cookie_file_jar()
    elif cdp_ok:
        mode = "cdp"
        try:
            jar = _fetch_cdp_cookies()
        except Exception as e:
            logger.warning(f"[Session] CDP cookie fetch failed during status: {e}")

    return {
        "mode": mode,
        "cdp_port": settings.BROWSER_CDP_PORT,
        "cdp_reachable": cdp_ok,
        "auto_launch": settings.BROWSER_CDP_AUTOLAUNCH,
        "profile_dir": settings.BROWSER_CDP_PROFILE_DIR,
        "cookie_file": cookie_file,
        "cookie_file_exists": file_ok,
        "total_cookies": len(jar) if jar else 0,
        "platforms": _platform_snapshot(jar),
    }


@router.get("/status")
async def session_status() -> Dict[str, Any]:
    """Passive snapshot of the cookie bridge. Never launches Chrome."""
    return {"bridge": _bridge_snapshot()}


@router.post("/refresh")
async def session_refresh() -> Dict[str, Any]:
    """Re-extract the cookie jar (may auto-launch the automation Chrome)."""
    await asyncio.to_thread(get_cookie_jar, True)
    return {"bridge": _bridge_snapshot()}


@router.post("/login")
async def session_login(req: LoginRequest) -> Dict[str, Any]:
    """Open the platform's login page in the automation Chrome window."""
    meta = PLATFORM_DEFS.get(req.platform)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {req.platform}")

    ok = await asyncio.to_thread(ensure_cdp_browser)
    if not ok:
        raise HTTPException(
            status_code=503,
            detail="無法啟動自動化 Chrome（CDP port 未開啟）。請確認本機已安裝 Chrome 或改用 cookies.txt 匯入。",
        )

    async def _open_tab() -> None:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{settings.BROWSER_CDP_PORT}")
            try:
                ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
                page = await ctx.new_page()
                await page.goto(meta["login_url"], timeout=30000)
                await page.bring_to_front()
            finally:
                await browser.close()  # detach only

    try:
        await asyncio.wait_for(_open_tab(), timeout=45)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"已啟動 Chrome 但開啟登入頁失敗: {e}")

    return {"success": True, "platform": req.platform, "url": meta["login_url"]}

@router.get("/local-auth")
async def get_local_auth(request: Request):
    """Zero-friction auto-auth for local users connecting via loopback (localhost)."""
    client_host = request.client.host if request.client else ""
    is_loopback = client_host in {"127.0.0.1", "::1", "localhost", "testclient"}
    if not (is_loopback and settings.LOCAL_AUTO_LOGIN):
        return {"authenticated": False, "api_key": ""}
    return {"authenticated": True, "api_key": settings.API_KEY}
