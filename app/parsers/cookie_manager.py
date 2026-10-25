import os
import time
import tempfile
import subprocess
import http.cookiejar
from pathlib import Path
from typing import Dict, Any, Optional, List
import httpx
import yt_dlp.cookies
from app.config import settings

_cached_jar: Optional[http.cookiejar.CookieJar] = None
_cached_jar_time: float = 0
_CACHE_TTL_SECONDS = 900  # 15 minutes cache

# Chrome 127+ App-Bound Encryption (yt-dlp #10927) plus the DB file lock while
# Chrome runs (yt-dlp #7271) make direct DB extraction dead on Windows. The
# only durable path is asking Chrome itself for decrypted cookies over CDP,
# against a dedicated automation profile (Chrome 136+ blocks the debug port on
# the default profile).
_CDP_LAUNCH_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


class SilentYDLLogger:
    def debug(self, msg: str):
        pass

    def info(self, msg: str):
        pass

    def warning(self, msg: str):
        pass

    def error(self, msg: str):
        pass


def _cdp_reachable(port: int, timeout: float = 1.5) -> bool:
    try:
        r = httpx.get(f"http://127.0.0.1:{port}/json/version", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def ensure_cdp_browser() -> bool:
    """Make sure a Chrome with the DevTools port is up (auto-launching a
    dedicated persistent profile when needed). Returns True when reachable."""
    port = settings.BROWSER_CDP_PORT
    if _cdp_reachable(port):
        return True
    if not settings.BROWSER_CDP_AUTOLAUNCH:
        return False

    chrome = next((p for p in _CDP_LAUNCH_PATHS if Path(p).is_file()), None)
    if not chrome:
        print("[Cookie Bridge] CDP port closed and chrome.exe not found for auto-launch.")
        return False

    profile_dir = str(Path(settings.BROWSER_CDP_PROFILE_DIR).expanduser())
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    try:
        subprocess.Popen(
            [
                chrome,
                f"--remote-debugging-port={port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "about:blank",
            ],
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )
    except Exception as e:
        print(f"[Cookie Bridge] Chrome auto-launch failed: {e}")
        return False

    for _ in range(24):  # up to ~12s cold start
        time.sleep(0.5)
        if _cdp_reachable(port):
            print(
                f"[Cookie Bridge] Launched automation Chrome (CDP :{port}, profile {profile_dir}). "
                f"在此視窗登入 Instagram / Facebook 一次，之後所有 Reel 解析都能帶會員狀態。"
            )
            return True
    print("[Cookie Bridge] Chrome launched but CDP port did not open in time.")
    return False


def _cdp_cookies_to_jar(raw: List[Dict[str, Any]]) -> http.cookiejar.CookieJar:
    jar = http.cookiejar.CookieJar()
    for c in raw:
        try:
            jar.set_cookie(
                http.cookiejar.Cookie(
                    version=0,
                    name=c.get("name", ""),
                    value=c.get("value", ""),
                    port=None, port_specified=False,
                    domain=c.get("domain", ""), domain_specified=bool(c.get("domain")), domain_initial_dot=c.get("domain", "").startswith("."),
                    path=c.get("path", "/"), path_specified=True,
                    secure=bool(c.get("secure")),
                    expires=int(c["expires"]) if c.get("expires", -1) and c.get("expires", -1) > 0 else None,
                    discard=not c.get("expires"),
                    comment=None, comment_url=None, rest={"HttpOnly": ""} if c.get("httpOnly") else {},
                    rfc2109=False,
                )
            )
        except Exception:
            continue
    return jar


def _fetch_cdp_cookies() -> Optional[http.cookiejar.CookieJar]:
    """Connect to the DevTools endpoint and pull decrypted cookies via Playwright.
    Runs in a worker thread so it is safe inside the FastAPI event loop."""
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    port = settings.BROWSER_CDP_PORT

    async def _inner() -> List[Dict[str, Any]]:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            try:
                merged: Dict[tuple, Dict[str, Any]] = {}
                for ctx in browser.contexts:
                    for c in await ctx.cookies():
                        merged[(c["name"], c["domain"], c["path"])] = c
                return list(merged.values())
            finally:
                await browser.close()  # detaches only — the user's Chrome keeps running

    with ThreadPoolExecutor(max_workers=1) as ex:
        raw = ex.submit(lambda: asyncio.run(_inner())).result(timeout=30)
    return _cdp_cookies_to_jar(raw)


def get_cookies_via_cdp(force_refresh: bool = False) -> Optional[http.cookiejar.CookieJar]:
    """Fetch live decrypted cookies over CDP; auto-launches the automation
    Chrome on first use. Returns None when unavailable."""
    if not ensure_cdp_browser():
        return None
    try:
        jar = _fetch_cdp_cookies()
        if jar and len(jar) > 0:
            return jar
    except Exception as e:
        print(f"[Cookie Bridge] CDP cookie fetch failed: {type(e).__name__}: {e}")
    return None


def get_cookie_jar(force_refresh: bool = False) -> Optional[http.cookiejar.CookieJar]:
    """
    Retrieve browser session cookies as a CookieJar, in reliability order:
    1. cookies.txt file (exported from Chrome via extension) — zero moving parts.
    2. CDP bridge to the automation Chrome profile (immune to file lock + ABE).
    3. Legacy yt-dlp live extraction (kept for Firefox / older browsers).
    Results are cached in memory to avoid repeated decryption overhead.
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

    # 2. CDP bridge to the automation Chrome (decrypted by Chrome itself)
    jar = get_cookies_via_cdp(force_refresh=force_refresh)
    if jar and len(jar) > 0:
        _cached_jar = jar
        _cached_jar_time = now
        print(f"[Cookie Bridge] Extracted {len(jar)} live cookies via CDP (port {settings.BROWSER_CDP_PORT})")
        return jar

    # 3. Legacy live extraction (works for Firefox / browsers without ABE) —
    #    skip noisy guaranteed-to-fail attempts for App-Bound-encrypted Chrome.
    browser_source = getattr(settings, "BROWSER_COOKIE_SOURCE", None)
    if browser_source and browser_source.lower() not in ("chrome", "chromium", "edge", "brave", "opera", "vivaldi"):
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
            # Short-TTL the empty jar so a login in the automation window is
            # picked up quickly instead of being blocked for the full 15 min.
            _cached_jar_time = now - _CACHE_TTL_SECONDS + 60

    return None


def _write_netscape_tmp(jar: http.cookiejar.CookieJar) -> str:
    """Export a CookieJar to a Netscape-format cookies file yt-dlp can consume."""
    tmp_dir = Path(tempfile.gettempdir()) / "omnikeep-cookies"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    out = tmp_dir / "session.cookies"
    lines = ["# Netscape HTTP Cookie File"]
    for c in jar:
        if not c.domain:
            continue
        name = ("#HttpOnly_" + c.name) if c.has_nonstandard_attr("HttpOnly") else c.name
        expires = str(int(c.expires)) if c.expires else "0"
        initial_dot = "TRUE" if c.domain.startswith(".") else "FALSE"
        lines.append("\t".join([
            c.domain, initial_dot, c.path or "/", "TRUE" if c.secure else "FALSE",
            expires, name, c.value or "",
        ]))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(out)


_netscape_tmp_file: Optional[str] = None
_netscape_tmp_time: float = 0


def get_ytdlp_cookie_opts(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Generate yt-dlp cookie options compatible with YoutubeDL:
    - Prioritizes 'cookiefile' if cookies.txt is present.
    - Otherwise exports the live bridge jar (CDP) to a Netscape temp file.
    - 'cookiesfrombrowser' stays as last resort for browsers without ABE.
    """
    global _netscape_tmp_file, _netscape_tmp_time

    cookie_file = getattr(settings, "BROWSER_COOKIE_FILE", None)
    if cookie_file and Path(cookie_file).is_file():
        return {"cookiefile": str(cookie_file)}

    if (
        _netscape_tmp_file
        and Path(_netscape_tmp_file).is_file()
        and (time.time() - _netscape_tmp_time) < _CACHE_TTL_SECONDS
        and not force_refresh
    ):
        return {"cookiefile": _netscape_tmp_file}

    jar = get_cookie_jar(force_refresh=force_refresh)
    if jar is not None and len(jar) > 0:
        try:
            _netscape_tmp_file = _write_netscape_tmp(jar)
            _netscape_tmp_time = time.time()
            return {"cookiefile": _netscape_tmp_file}
        except Exception as e:
            print(f"[Cookie Bridge] Netscape export failed: {e}")

    browser_source = getattr(settings, "BROWSER_COOKIE_SOURCE", None)
    if browser_source and browser_source.lower() not in ("chrome", "chromium", "edge", "brave", "opera", "vivaldi"):
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
