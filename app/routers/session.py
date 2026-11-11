"""
Session Bridge Router — account session visibility & one-click platform login.

Exposes the state of the cookie bridge (cookies.txt / CDP automation Chrome /
legacy extraction) so users can see which platforms are connected and open a
login window without touching the terminal.
"""

import asyncio
import http.cookiejar
import ipaddress
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import pairing
from app.config import settings
from app.security import configured_key
from app.parsers.cookie_manager import (
    PLAYWRIGHT_MISSING,
    _cdp_reachable,
    _fetch_cdp_cookies,
    ensure_cdp_browser,
    get_cookie_jar,
    playwright_installed,
    restore_headless_cdp_browser,
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

# Specific cookie names required to consider a platform actually authenticated
PLATFORM_AUTH_COOKIES: Dict[str, set[str]] = {
    "instagram": {"sessionid"},
    "facebook": {"c_user"},
    "x": {"auth_token"},
    "google": {"SID", "SSID", "__Secure-1PSID"},
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
    """Per-platform connection summary derived from authenticating cookie tokens."""
    result: List[Dict[str, Any]] = []
    for pid, meta in PLATFORM_DEFS.items():
        count = 0
        is_connected = False
        required_auth = PLATFORM_AUTH_COOKIES.get(pid, set())
        if jar:
            matching = [c for c in jar if meta["domain"] in (c.domain or "")]
            count = len(matching)
            if required_auth:
                is_connected = any(c.name in required_auth and bool(c.value) for c in matching)
            else:
                is_connected = count > 0
        result.append({"id": pid, "connected": is_connected, "cookies": count})
    return result


def _bridge_snapshot() -> Dict[str, Any]:
    cookie_file = settings.BROWSER_COOKIE_FILE
    file_ok = bool(cookie_file) and Path(cookie_file).is_file()
    cdp_ok = _cdp_reachable(settings.BROWSER_CDP_PORT, timeout=0.8)
    has_playwright = playwright_installed()

    mode = "none"
    jar: Optional[http.cookiejar.CookieJar] = None
    if file_ok:
        mode = "cookiefile"
        jar = _load_cookie_file_jar()
    elif cdp_ok and has_playwright:
        mode = "cdp"
        try:
            jar = _fetch_cdp_cookies()
        except Exception as e:
            logger.warning(f"[Session] CDP cookie fetch failed during status: {e}")

    return {
        "mode": mode,
        "playwright_installed": has_playwright,
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
    """Refresh login cookies, then return the login browser to headless mode."""
    await asyncio.to_thread(get_cookie_jar, True)
    if not await asyncio.to_thread(restore_headless_cdp_browser):
        logger.warning("[Session] Could not restore background Chrome after refresh")
    return {"bridge": _bridge_snapshot()}


@router.post("/login")
async def session_login(req: LoginRequest) -> Dict[str, Any]:
    """Open the platform's login page in the automation Chrome window."""
    meta = PLATFORM_DEFS.get(req.platform)
    if not meta:
        raise HTTPException(status_code=404, detail=f"Unknown platform: {req.platform}")
    if not playwright_installed():
        raise HTTPException(status_code=503, detail=PLAYWRIGHT_MISSING)

    ok = await asyncio.to_thread(ensure_cdp_browser, visible=True)
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

# A reverse proxy on the same machine (Tailscale serve, cloudflared, ngrok...)
# connects from loopback on behalf of a remote device. These are the headers
# such proxies add; seeing any of them means the real client is not local.
_PROXY_HEADERS = {"forwarded", "via", "x-real-ip", "cf-connecting-ip", "true-client-ip"}
_PROXY_HEADER_PREFIXES = ("x-forwarded-", "tailscale-")


def _came_through_proxy(request: Request) -> bool:
    return any(
        name in _PROXY_HEADERS or name.startswith(_PROXY_HEADER_PREFIXES)
        for name in request.headers.keys()
    )


def _is_trusted_client(client_host: str) -> bool:
    if not client_host:
        return False
    if client_host in {"127.0.0.1", "::1", "localhost", "testclient"}:
        return True
    try:
        ip = ipaddress.ip_address(client_host)
        return ip.is_loopback
    except ValueError:
        return False


# The names a browser on this machine reaches it by; any port (a dev server proxies from its own).
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "[::1]"}
_AUTHORITY = re.compile(r"(\[[0-9a-f:.]+\]|[a-z0-9.-]+)(?::(\d{1,5}))?")
_DEFAULT_PORTS = {"http": 80, "https": 443}


def _authority(value: str) -> Optional[Tuple[str, Optional[int]]]:
    """(host, port) of a Host header or of an origin's authority; None when it is not one."""
    match = _AUTHORITY.fullmatch(value.strip().lower())
    if not match:
        return None
    return match.group(1), int(match.group(2)) if match.group(2) else None


def _asked_by_own_local_page(request: Request) -> bool:
    """True when the request names this machine and no other site's page is behind it.

    Host: a page that rebinds its own domain to 127.0.0.1 (DNS rebinding) reaches this
    port from loopback, but the browser still sends that domain as Host.
    Origin / Sec-Fetch-Site: a page on another site, or on another local port, says so.
    """
    hosts = request.headers.getlist("host")
    host = _authority(hosts[0]) if len(hosts) == 1 else None
    if not host or host[0] not in _LOCAL_HOSTS:
        return False
    scheme = request.url.scheme
    default_port = _DEFAULT_PORTS.get(scheme)
    for origin in request.headers.getlist("origin"):
        origin_scheme, separator, rest = origin.strip().lower().partition("://")
        asker = _authority(rest) if separator else None  # "null" (a sandboxed frame) has no authority
        if not asker or origin_scheme != scheme:
            return False
        if (asker[0], asker[1] or default_port) != (host[0], host[1] or default_port):
            return False
    return all(site.strip().lower() in ("same-origin", "none")
               for site in request.headers.getlist("sec-fetch-site"))


# The answer may carry the key: never stored, and unreadable to other sites even where
# the browser sends no Sec-Fetch-Site.
_LOCAL_AUTH_HEADERS = {"Cache-Control": "no-store", "Cross-Origin-Resource-Policy": "same-origin"}


@router.get("/local-auth")
async def get_local_auth(request: Request):
    """Signs in a browser on this same machine without the key (LOCAL_AUTO_LOGIN, on by default).

    Public, and the answer is the access key itself, so all of these must hold: the
    setting is on, the connection comes from loopback, no reverse proxy relayed it, and
    OmniKeep's own page asked under a local name. A refusal never says which one failed.
    """
    client_host = request.client.host if request.client else ""
    allowed = (
        settings.LOCAL_AUTO_LOGIN
        and _is_trusted_client(client_host)
        and not _came_through_proxy(request)
        and _asked_by_own_local_page(request)
    )
    body = {"authenticated": True, "api_key": settings.API_KEY} if allowed else {"authenticated": False, "api_key": ""}
    return JSONResponse(body, headers=_LOCAL_AUTH_HEADERS)


# ── Phone sign-in with a one-time code (app/pairing.py) ──────────────
class PairRequest(BaseModel):
    code: str = Field(..., max_length=32)


@router.post("/pairing")
async def create_pairing():
    """A new one-time code for a phone, shown on this signed-in screen (replaces any earlier one)."""
    if not configured_key():
        raise HTTPException(status_code=503, detail="先設定足夠長的 API_KEY（32 個字元以上）")
    created = pairing.create()
    try:
        urls = await asyncio.to_thread(pairing.phone_urls)
    except Exception:  # no tailscale CLI, or it timed out: the page can still use its own address
        urls = []
    return {**created, "ttl": pairing.TTL, "phone_urls": urls}


@router.get("/pairing")
async def get_pairing():
    return pairing.status()


@router.delete("/pairing")
async def cancel_pairing():
    pairing.cancel()
    return {"ok": True}


@router.post("/pair")
async def redeem_pairing(req: PairRequest):
    """Public: the code is the credential. Answers with the key once, never cached."""
    key = configured_key()
    if not key or not pairing.redeem(req.code):
        return JSONResponse(status_code=400, content={"error": "配對碼不正確、已用過或已過期，請在電腦上重新產生"},
                            headers={"Cache-Control": "no-store"})
    logger.info("A phone signed in with a pairing code")
    return JSONResponse({"api_key": key}, headers={"Cache-Control": "no-store"})
