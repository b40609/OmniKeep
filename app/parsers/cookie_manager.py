import os
import time
import http.cookiejar
from pathlib import Path
from typing import Dict, Any, Optional, List
import httpx
import yt_dlp.cookies
from app.config import settings

_cached_jar: Optional[http.cookiejar.CookieJar] = None
_cached_jar_time: float = 0
_CACHE_TTL_SECONDS = 900  # 15 minutes cache


class SilentYDLLogger:
    def debug(self, msg: str):
        pass

    def info(self, msg: str):
        pass

    def warning(self, msg: str):
        pass

    def error(self, msg: str):
        pass


def get_cookie_jar(force_refresh: bool = False) -> Optional[http.cookiejar.CookieJar]:
    """
    Retrieve browser session cookies as a CookieJar:
    1. Checks if a cookies.txt file exists (e.g. exported from Chrome via extension).
    2. If not, attempts to extract live cookies from the configured browser (e.g. 'chrome').
    3. Caches the resulting CookieJar in memory to avoid repeated disk locks / decryption overhead.
    """
    global _cached_jar, _cached_jar_time

    now = time.time()
    if not force_refresh and _cached_jar is not None and (now - _cached_jar_time) < _CACHE_TTL_SECONDS:
        return _cached_jar

    # 1. Check cookies.txt file first (most reliable, immune to Windows file lock / App-Bound encryption)
    cookie_file = getattr(settings, "BROWSER_COOKIE_FILE", None)
    if cookie_file and Path(cookie_file).is_file():
        try:
            jar = http.cookiejar.MozillaCookieJar(cookie_file)
            jar.load(ignore_discard=True, ignore_expires=True)
            _cached_jar = jar
            _cached_jar_time = now
            print(f"[Cookie Bridge] Successfully loaded {len(jar)} cookies from file: {cookie_file}")
            return jar
        except Exception as e:
            print(f"[Cookie Bridge] Warning: Failed to parse cookie file '{cookie_file}': {e}")

    # 2. Attempt live browser cookie extraction if configured
    browser_source = getattr(settings, "BROWSER_COOKIE_SOURCE", None)
    if browser_source:
        try:
            jar = yt_dlp.cookies.extract_cookies_from_browser(browser_source, logger=SilentYDLLogger())
            _cached_jar = jar
            _cached_jar_time = now
            print(f"[Cookie Bridge] Successfully extracted {len(jar)} live cookies from browser '{browser_source}'")
            return jar
        except Exception as e:
            # Graceful warning: Windows Chrome 127+ enforces App-Bound encryption & process lock while open
            print(f"[Cookie Bridge] Info: Live browser extraction from '{browser_source}' skipped ({type(e).__name__}). Using fallback strategy.")
            _cached_jar = http.cookiejar.CookieJar()
            _cached_jar_time = now

    return None


def get_ytdlp_cookie_opts() -> Dict[str, Any]:
    """
    Generate yt-dlp cookie options compatible with YoutubeDL:
    - Prioritizes 'cookiefile' if cookies.txt is present.
    - Otherwise supplies 'cookiesfrombrowser' if configured.
    """
    cookie_file = getattr(settings, "BROWSER_COOKIE_FILE", None)
    if cookie_file and Path(cookie_file).is_file():
        return {"cookiefile": str(cookie_file)}

    browser_source = getattr(settings, "BROWSER_COOKIE_SOURCE", None)
    if browser_source:
        return {"cookiesfrombrowser": (browser_source,)}

    return {}


def get_httpx_cookies() -> Optional[httpx.Cookies]:
    """
    Return cookies formatted for httpx.AsyncClient / Client.
    """
    jar = get_cookie_jar()
    if jar is not None and len(jar) > 0:
        return httpx.Cookies(jar)
    return None


async def inject_playwright_cookies(context: Any, target_domain: Optional[str] = None) -> int:
    """
    Inject extracted session cookies into a Playwright BrowserContext.
    Returns the number of cookies successfully injected.
    """
    jar = get_cookie_jar()
    if not jar:
        return 0

    cookies_list: List[Dict[str, Any]] = []
    for c in jar:
        if target_domain and target_domain not in c.domain:
            continue

        item: Dict[str, Any] = {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": bool(c.has_nonstandard_attr("HttpOnly")),
        }
        if c.expires:
            item["expires"] = int(c.expires)

        # SameSite normalization
        if c.has_nonstandard_attr("SameSite"):
            val = c.get_nonstandard_attr("SameSite")
            if val in ("Strict", "Lax", "None"):
                item["sameSite"] = val

        cookies_list.append(item)

    if cookies_list:
        try:
            await context.add_cookies(cookies_list)
            return len(cookies_list)
        except Exception as e:
            print(f"[Cookie Bridge] Playwright add_cookies error: {e}")
            return 0

    return 0
