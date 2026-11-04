import os
import shutil
import time
import tempfile
import subprocess
import http.cookiejar
import ipaddress
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Any, Iterator, Optional, List
from urllib.parse import urlsplit
import httpx
import psutil
import yt_dlp.cookies
from app.config import settings

_cached_jar: Optional[http.cookiejar.CookieJar] = None
_cached_jar_time: float = 0
_CACHE_TTL_SECONDS = 900  # 15 minutes cache
_cdp_launch_lock = threading.RLock()

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


def _managed_cdp_browser() -> Optional[psutil.Process]:
    """Find only the Chrome root process using OmniKeep's dedicated profile/port."""
    profile = str(Path(settings.BROWSER_CDP_PROFILE_DIR).expanduser())
    profile_arg = f"--user-data-dir={profile}"
    port_arg = f"--remote-debugging-port={settings.BROWSER_CDP_PORT}"
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            args = process.info["cmdline"] or []
            if (
                (process.info["name"] or "").lower() in {"chrome", "chrome.exe"}
                and port_arg in args
                and any(a.casefold() == profile_arg.casefold() for a in args)
                and not any(a.startswith("--type=") for a in args)
            ):
                return process
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
    return None


def _close_managed_browser(process: psutil.Process) -> bool:
    """Ask Chrome to flush its profile and exit before switching modes."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{settings.BROWSER_CDP_PORT}"
            )
            browser.new_browser_cdp_session().send("Browser.close")
    except Exception as exc:
        # Closing the browser can disconnect CDP before it returns a response.
        print(f"[Cookie Bridge] Chrome shutdown notice: {type(exc).__name__}")
    try:
        process.wait(timeout=8)
        return True
    except (psutil.NoSuchProcess,):
        return True
    except psutil.TimeoutExpired:
        print("[Cookie Bridge] Chrome did not exit; mode switch skipped.")
        return False


def ensure_cdp_browser(*, visible: bool = False) -> bool:
    """Keep a headless CDP Chrome by default; show it only for manual login."""
    with _cdp_launch_lock:
        return _ensure_cdp_browser_locked(visible=visible)


def restore_headless_cdp_browser() -> bool:
    """Finish manual login and return the dedicated profile to background mode."""
    if not settings.BROWSER_CDP_HEADLESS:
        return True
    with _cdp_launch_lock:
        if _cdp_reachable(settings.BROWSER_CDP_PORT):
            process = _managed_cdp_browser()
            if process is None:
                return False
            try:
                if any(a.startswith("--headless") for a in process.cmdline()):
                    return True
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                return False
            if not _close_managed_browser(process):
                return False
        return _ensure_cdp_browser_locked(visible=False)


def _ensure_cdp_browser_locked(*, visible: bool) -> bool:
    port = settings.BROWSER_CDP_PORT
    if _cdp_reachable(port):
        if not visible:
            return True
        process = _managed_cdp_browser()
        if process is None:
            print("[Cookie Bridge] CDP port is used by another browser; cannot open login window safely.")
            return False
        try:
            if not any(a.startswith("--headless") for a in process.cmdline()):
                return True
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return False
        if not _close_managed_browser(process):
            return False
    # An explicit login request is allowed even when background auto-launch is off.
    if not settings.BROWSER_CDP_AUTOLAUNCH and not visible:
        return False

    chrome = next((p for p in _CDP_LAUNCH_PATHS if Path(p).is_file()), None)
    if not chrome:
        print("[Cookie Bridge] CDP port closed and chrome.exe not found for auto-launch.")
        return False

    profile_dir = str(Path(settings.BROWSER_CDP_PROFILE_DIR).expanduser())
    Path(profile_dir).mkdir(parents=True, exist_ok=True)
    try:
        args = [
            chrome,
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if settings.BROWSER_CDP_HEADLESS and not visible:
            args.append("--headless=new")
        args.append("about:blank")
        subprocess.Popen(
            args,
            creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS) if os.name == "nt" else 0,
            close_fds=True,
        )
    except Exception as e:
        print(f"[Cookie Bridge] Chrome auto-launch failed: {e}")
        return False

    for _ in range(24):  # up to ~12s cold start
        time.sleep(0.5)
        if _cdp_reachable(port):
            print(
                f"[Cookie Bridge] Launched {'visible' if visible else 'background'} Chrome "
                f"(CDP :{port}, profile {profile_dir})."
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
                    comment=None, comment_url=None,
                    # The stdlib's spelling, so MozillaCookieJar.save() writes the #HttpOnly_ marker.
                    rest={http.cookiejar.HTTPONLY_ATTR: ""} if c.get("httpOnly") else {},
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


# Hosts that share one login with another site: short links and sibling domains.
_SITE_ALIASES = {"fb.watch": "facebook.com", "fb.com": "facebook.com", "instagr.am": "instagram.com",
                 "youtu.be": "youtube.com", "b23.tv": "bilibili.com"}
# Second-level labels under country TLDs that are not registrable on their own (co.uk, com.tw…).
_SECOND_LEVEL = {"co", "com", "net", "org", "gov", "edu", "ac", "or", "ne", "go"}
_EXPORT_PREFIX = "omnikeep-cookies-"
_EXPORT_MAX_AGE_SECONDS = 3600


def _is_http_only(cookie: http.cookiejar.Cookie) -> bool:
    # cookies.txt loads as the stdlib's "HTTPOnly"; older CDP jars used "HttpOnly".
    return cookie.has_nonstandard_attr(http.cookiejar.HTTPONLY_ATTR) or cookie.has_nonstandard_attr("HttpOnly")


def cookie_site(url: str) -> str:
    """The site whose login a URL belongs to: its registrable domain (www.instagram.com →
    instagram.com, news.bbc.co.uk → bbc.co.uk). A heuristic rather than the full Public
    Suffix List; its job is to keep every other site's cookies out."""
    host = (urlsplit(url).hostname or "").lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    for alias, site in _SITE_ALIASES.items():
        if host == alias or host.endswith("." + alias):
            return site
    labels = host.split(".")
    keep = 3 if len(labels) >= 3 and len(labels[-1]) == 2 and labels[-2] in _SECOND_LEVEL else 2
    return ".".join(labels[-keep:])


def site_cookies(url: str, jar: Optional[http.cookiejar.CookieJar] = None) -> http.cookiejar.CookieJar:
    """Only the bridged cookies that belong to url's site."""
    site = cookie_site(url)
    scoped = http.cookiejar.CookieJar()
    source = jar if jar is not None else get_cookie_jar()
    for cookie in source or []:
        domain = cookie.domain.lstrip(".").lower()
        if site and (domain == site or domain.endswith("." + site)):
            scoped.set_cookie(cookie)
    return scoped


def sweep_cookie_exports(max_age: float = _EXPORT_MAX_AGE_SECONDS) -> int:
    """Delete cookie exports a crash left behind, plus the shared export file earlier
    versions kept in TEMP/omnikeep-cookies with every site's cookies in plain text."""
    temp = Path(tempfile.gettempdir())
    removed = 0
    for folder in temp.glob(_EXPORT_PREFIX + "*"):
        try:
            if folder.is_dir() and time.time() - folder.stat().st_mtime > max_age:
                shutil.rmtree(folder)
                removed += 1
        except OSError:  # gone already, or still open
            pass
    legacy = temp / "omnikeep-cookies" / "session.cookies"
    try:
        legacy.unlink()
        removed += 1
    except OSError:
        pass
    try:
        legacy.parent.rmdir()  # only if now empty
    except OSError:
        pass
    return removed


def _restrict_to_current_user(folder: Path) -> None:
    """Windows: drop inherited access and grant the current user. TEMP's ACL can let other
    accounts in (on the dev machine it grants a sandbox group modify rights)."""
    whoami = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], capture_output=True,
                            text=True, check=True, timeout=10).stdout
    sid = whoami.strip().rsplit(",", 1)[-1].strip('"')
    subprocess.run(["icacls", str(folder), "/inheritance:r", "/grant:r", f"*{sid}:(OI)(CI)F"],
                   capture_output=True, check=True, timeout=10)


def _private_dir() -> Path:
    """A fresh folder only the current user (and administrators) can open. mkdtemp makes
    it 0700 on POSIX, and newer Pythons on Windows give it a user-only ACL too; older
    ones (the project supports 3.10+) inherit TEMP's, so inheritance is cut explicitly."""
    folder = Path(tempfile.mkdtemp(prefix=_EXPORT_PREFIX))
    if os.name == "nt":
        try:
            _restrict_to_current_user(folder)
        except (OSError, subprocess.SubprocessError):
            shutil.rmtree(folder, ignore_errors=True)
            raise
    return folder


@contextmanager
def ytdlp_cookie_opts(url: str) -> Iterator[Dict[str, Any]]:
    """yt-dlp options for one download of `url`.

    Only url's site cookies are exported, into a folder only this user can open, and
    the folder is deleted once the download is done. If that folder cannot be made
    private, the download goes without cookies. yt-dlp rewrites its cookiefile when it
    exits, so the user's own cookies.txt is never handed to it either.
    """
    sweep_cookie_exports()
    cookies = site_cookies(url)
    if len(cookies) == 0:
        browser_source = getattr(settings, "BROWSER_COOKIE_SOURCE", None)
        if browser_source and browser_source.lower() not in ("chrome", "chromium", "edge", "brave", "opera", "vivaldi"):
            yield {"cookiesfrombrowser": (browser_source,)}
        else:
            yield {}
        return
    try:
        folder = _private_dir()
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[Cookie Bridge] No private folder for cookies ({type(e).__name__}); downloading without them.")
        yield {}
        return
    try:
        export = http.cookiejar.MozillaCookieJar(str(folder / "cookies.txt"))
        for cookie in cookies:
            export.set_cookie(cookie)
        # The stdlib writer marks HttpOnly cookies on the domain field, as yt-dlp expects.
        export.save(ignore_discard=True, ignore_expires=True)
        yield {"cookiefile": export.filename}
    finally:
        shutil.rmtree(folder, ignore_errors=True)  # anything still open is left to the next sweep


def get_httpx_cookies(url: str) -> Optional[httpx.Cookies]:
    """url's site cookies formatted for httpx.AsyncClient / Client."""
    jar = site_cookies(url)
    if len(jar) > 0:
        return httpx.Cookies(jar)
    return None


async def inject_playwright_cookies(context: Any, url: str) -> int:
    """
    Inject url's site cookies into a Playwright BrowserContext, and no others:
    the rendered page may load any third party, which must not get the user's sessions.
    Returns the number of cookies successfully injected.
    """
    jar = site_cookies(url)
    if not jar:
        return 0

    cookies_list: List[Dict[str, Any]] = []
    for c in jar:
        item: Dict[str, Any] = {
            "name": c.name,
            "value": c.value,
            "domain": c.domain,
            "path": c.path or "/",
            "secure": bool(c.secure),
            "httpOnly": _is_http_only(c),
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
