import os
import tempfile
from pathlib import Path
import pytest
import http.cookiejar
from app.config import settings
from app.parsers.cookie_manager import (
    get_cookie_jar,
    get_ytdlp_cookie_opts,
    get_httpx_cookies,
    inject_playwright_cookies,
)
from app.parsers.reel import is_video_reel_url
from app.parsers.web import is_facebook_url, parse_facebook_page

def test_settings_cookie_configuration():
    assert hasattr(settings, "BROWSER_COOKIE_SOURCE")
    assert settings.BROWSER_COOKIE_SOURCE == "chrome"
    assert hasattr(settings, "BROWSER_COOKIE_FILE")
    assert Path(settings.BROWSER_COOKIE_FILE).is_absolute()

def test_ytdlp_cookie_options():
    opts = get_ytdlp_cookie_opts()
    assert isinstance(opts, dict)
    assert "cookiesfrombrowser" in opts or "cookiefile" in opts

def test_cookie_file_loading_and_conversion():
    cookie_content = """# Netscape HTTP Cookie File
.facebook.com\tTRUE\t/\tTRUE\t2147483647\tc_user\t100099887766
.facebook.com\tTRUE\t/\tTRUE\t2147483647\txs\t42%3Asecret%3A2
"""
    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt") as f:
        f.write(cookie_content)
        temp_path = f.name

    original_file = settings.BROWSER_COOKIE_FILE
    try:
        settings.BROWSER_COOKIE_FILE = temp_path
        jar = get_cookie_jar(force_refresh=True)
        assert jar is not None
        assert len(jar) == 2

        # Check httpx cookies
        httpx_cookies = get_httpx_cookies()
        assert httpx_cookies is not None
        assert "c_user" in httpx_cookies
        assert httpx_cookies.get("c_user") == "100099887766"

        # Check yt-dlp cookiefile opt
        opts = get_ytdlp_cookie_opts()
        assert opts.get("cookiefile") == temp_path

    finally:
        settings.BROWSER_COOKIE_FILE = original_file
        if os.path.exists(temp_path):
            os.remove(temp_path)

def test_url_classification():
    assert is_facebook_url("https://www.facebook.com/reel/1429983161862534")
    assert is_facebook_url("https://fb.watch/xyz123")
    assert is_video_reel_url("https://www.facebook.com/reel/1429983161862534")
    assert is_video_reel_url("https://www.instagram.com/reel/C_abc123")
    assert not is_video_reel_url("https://www.youtube.com/watch?v=123")

@pytest.mark.asyncio
async def test_parse_facebook_page_fallback():
    # Public reel URL should return clean metadata even without session
    url = "https://www.facebook.com/reel/1429983161862534"
    res = await parse_facebook_page(url)
    assert isinstance(res, dict)
    assert res.get("url") == url
    assert "title" in res
    assert "content_raw" in res
