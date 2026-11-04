"""Bridged browser cookies leave only for the site being fetched, and never linger on disk."""
import os
import subprocess
import tempfile
import time
from pathlib import Path

import httpx
import pytest
import yt_dlp

from app.config import settings
from app.parsers import cookie_manager, web
from app.parsers.cookie_manager import (
    _cdp_cookies_to_jar,
    cookie_site,
    inject_playwright_cookies,
    site_cookies,
    sweep_cookie_exports,
    ytdlp_cookie_opts,
)

REEL = "https://www.instagram.com/reel/C_fixture/"


def _cookie(name, domain, http_only=False):
    return {"name": name, "value": f"SYNTHETIC-{name}", "domain": domain, "path": "/", "secure": True,
            "httpOnly": http_only, "expires": 2147483647}


@pytest.fixture
def browser_jar(monkeypatch, isolated_runtime):
    """A logged-in automation Chrome: Instagram plus other sites' sessions."""
    jar = _cdp_cookies_to_jar([
        _cookie("sessionid", ".instagram.com", http_only=True),
        _cookie("csrftoken", "www.instagram.com"),
        _cookie("c_user", ".facebook.com", http_only=True),
        _cookie("SID", ".google.com", http_only=True),
        _cookie("lookalike", ".evilinstagram.com"),
    ])
    monkeypatch.setattr(cookie_manager, "get_cookie_jar", lambda force_refresh=False: jar)
    temp = isolated_runtime / "tmp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))  # never touch the real TEMP
    return temp


@pytest.mark.parametrize("url, site", [
    ("https://www.instagram.com/reel/x", "instagram.com"),
    ("https://m.facebook.com/story.php", "facebook.com"),
    ("https://fb.watch/abc", "facebook.com"),
    ("https://youtu.be/abc", "youtube.com"),
    ("https://news.bbc.co.uk/x", "bbc.co.uk"),
    ("https://shop.example.com.tw/x", "example.com.tw"),
    ("https://evilinstagram.com/x", "evilinstagram.com"),
    ("https://203.0.113.5/x", "203.0.113.5"),
])
def test_cookie_site(url, site):
    assert cookie_site(url) == site


def test_only_the_target_sites_cookies_are_selected(browser_jar):
    assert sorted(c.name for c in site_cookies(REEL)) == ["csrftoken", "sessionid"]
    assert sorted(c.name for c in site_cookies("https://fb.watch/xyz")) == ["c_user"]
    assert len(site_cookies("https://example.org/")) == 0


def _windows_principals(path):
    out = subprocess.run(["icacls", str(path)], capture_output=True, text=True, encoding="mbcs").stdout
    aces = [line.strip().removeprefix(str(path)).strip() for line in out.splitlines() if ":(" in line]
    return {ace.split(":(")[0].lower() for ace in aces}


def _allowed_principals():
    me = subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip().lower()
    # SYSTEM and Administrators can read every file on the machine anyway.
    return {me, r"nt authority\system", r"builtin\administrators", "owner rights"}


def test_ytdlp_gets_a_private_scoped_export_that_is_deleted_afterwards(browser_jar):
    with ytdlp_cookie_opts(REEL) as opts:
        export = Path(opts["cookiefile"])
        assert export.parent.parent == browser_jar and export.parent.name.startswith("omnikeep-cookies-")
        if os.name == "posix":
            assert export.parent.stat().st_mode & 0o777 == 0o700
            assert export.stat().st_mode & 0o777 == 0o600
        else:
            # Nobody else: nothing inherited from TEMP, which may grant other accounts.
            principals = _windows_principals(export)
            assert subprocess.run(["whoami"], capture_output=True, text=True).stdout.strip().lower() in principals
            assert principals <= _allowed_principals(), principals
        text = export.read_text(encoding="utf-8")  # as written, before yt-dlp rewrites it on exit
        # Netscape format marks HttpOnly on the domain field, which yt-dlp strips when reading.
        assert any(line.startswith("#HttpOnly_.instagram.com\t") and "\tsessionid\t" in line
                   for line in text.splitlines())
        assert "facebook" not in text and "google" not in text and "evilinstagram" not in text
        # What yt-dlp itself loads from the file:
        with yt_dlp.YoutubeDL({"cookiefile": str(export), "quiet": True}) as ydl:
            loaded = sorted(c.name for c in ydl.cookiejar)
        assert loaded == ["csrftoken", "sessionid"]  # not "#HttpOnly_sessionid"
    assert not export.parent.exists()

    with pytest.raises(RuntimeError):
        with ytdlp_cookie_opts(REEL) as opts:
            failed = Path(opts["cookiefile"])
            raise RuntimeError("download failed")
    assert not failed.parent.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows ACLs")
def test_access_inherited_from_temp_is_cut(isolated_runtime):
    # Older Pythons create folders that inherit TEMP's ACL; simulate a TEMP granting Users.
    parent = isolated_runtime / "permissive-temp"
    parent.mkdir()
    subprocess.run(["icacls", str(parent), "/grant", "*S-1-5-32-545:(OI)(CI)R"], capture_output=True, check=True)
    child = parent / "export"
    os.mkdir(child)  # no 0o700: inherits like on Python < 3.12.4 / 3.13
    assert r"builtin\users" in _windows_principals(child)

    cookie_manager._restrict_to_current_user(child)

    assert r"builtin\users" not in _windows_principals(child)
    (child / "cookies.txt").write_text("secret")
    assert _windows_principals(child / "cookies.txt") <= _allowed_principals()


def test_without_a_private_folder_no_cookies_are_written(browser_jar, monkeypatch):
    def refuse():
        raise subprocess.CalledProcessError(1, "icacls")

    monkeypatch.setattr(cookie_manager, "_private_dir", refuse)
    with ytdlp_cookie_opts(REEL) as opts:
        assert opts == {}
    assert list(browser_jar.iterdir()) == []


def test_ytdlp_never_rewrites_the_users_cookies_txt(monkeypatch, isolated_runtime):
    temp = isolated_runtime / "tmp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))
    users_file = isolated_runtime / "cookies.txt"  # loaded through the real get_cookie_jar
    users_file.write_text("# Netscape HTTP Cookie File\n"
                          ".instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\tUSER-FILE\n"
                          ".google.com\tTRUE\t/\tTRUE\t2147483647\tSID\tUSER-FILE\n", encoding="utf-8")
    before = users_file.read_bytes()
    monkeypatch.setattr(settings, "BROWSER_COOKIE_FILE", str(users_file))

    with ytdlp_cookie_opts(REEL) as opts:
        assert opts["cookiefile"] != str(users_file)
        with yt_dlp.YoutubeDL({"cookiefile": opts["cookiefile"], "quiet": True}) as ydl:
            assert [c.name for c in ydl.cookiejar] == ["sessionid"]
            ydl.cookiejar.set_cookie(next(iter(_cdp_cookies_to_jar([_cookie("rotated", ".instagram.com")]))))
        # yt-dlp saved its jar on exit, into the export rather than the user's file.
    assert users_file.read_bytes() == before
    assert list(temp.iterdir()) == []


def test_sweep_removes_crash_leftovers_and_the_old_shared_export(browser_jar):
    stale = browser_jar / "omnikeep-cookies-stale"
    fresh = browser_jar / "omnikeep-cookies-fresh"
    for folder in (stale, fresh):
        folder.mkdir()
        (folder / "cookies.txt").write_text("secret")
    old = time.time() - 7200
    os.utime(stale, (old, old))
    legacy = browser_jar / "omnikeep-cookies" / "session.cookies"
    legacy.parent.mkdir()
    legacy.write_text("every site's cookies")

    assert sweep_cookie_exports() == 2
    assert not stale.exists() and fresh.exists()
    assert not legacy.exists() and not legacy.parent.exists()


async def test_playwright_gets_only_the_target_sites_cookies(browser_jar):
    class Context:
        added = []

        async def add_cookies(self, cookies):
            self.added.extend(cookies)

    context = Context()
    assert await inject_playwright_cookies(context, REEL) == 2
    assert {(c["name"], c["httpOnly"]) for c in context.added} == {("sessionid", True), ("csrftoken", False)}


async def test_cookies_txt_keeps_httponly_when_injected_into_playwright(monkeypatch, isolated_runtime):
    users_file = isolated_runtime / "cookies.txt"
    users_file.write_text("# Netscape HTTP Cookie File\n"
                          "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t2147483647\tsessionid\tUSER-FILE\n",
                          encoding="utf-8")
    monkeypatch.setattr(settings, "BROWSER_COOKIE_FILE", str(users_file))

    class Context:
        added = []

        async def add_cookies(self, cookies):
            self.added.extend(cookies)

    context = Context()
    assert await inject_playwright_cookies(context, REEL) == 1
    assert context.added[0]["httpOnly"] is True


async def test_web_fetch_sends_only_the_target_sites_cookies(browser_jar, monkeypatch):
    seen = {}

    def client(**kwargs):
        seen["cookies"] = sorted(c.name for c in kwargs["cookies"])
        body = "<html><title>Fixture</title><body><p>" + "長文內容 " * 40 + "</p></body></html>"
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, text=body)))

    monkeypatch.setattr(web, "public_http_client", client)
    await web.parse_web_page("https://www.instagram.com/p/fixture/")
    assert seen["cookies"] == ["csrftoken", "sessionid"]
