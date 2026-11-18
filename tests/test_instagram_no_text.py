"""An Instagram post that gives no public text says so and what to do (2026-11-18 trial: it was
titled 「無法解析：Instagram 貼文無公開文字」 by the AI, and a reel took the login page's greeting as its title)."""
from unittest.mock import AsyncMock, patch

import pytest

from app import pipeline
from app.parsers import web
from app.parsers.blocked import detect_blocked_page, is_error_title

POST = "https://www.instagram.com/p/C-0vO-9vB8Z/"
LOGIN_PAGE = ('<html><head><meta property="og:title" content="歡迎回到 Instagram。登入以查看親朋好友的更新動態。">'
              '<meta property="og:description" content="登入以查看親朋好友的更新動態，看看你感興趣的主題。"></head></html>')


def test_the_login_page_is_not_taken_for_the_post():
    class Resp:
        status_code = 200
        text = LOGIN_PAGE
        url = POST

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, _url):
            return Resp()

    import asyncio
    with patch.object(web, "site_cookies", return_value=None), \
         patch.object(web, "public_http_client", return_value=Client()):
        page = asyncio.run(web.parse_instagram_page(POST))
    assert "登入" not in page["title"] and page["content_raw"] == "（Instagram 貼文未提供公開文字說明）"
    assert is_error_title("歡迎回到 Instagram。登入以查看親朋好友的更新動態")


def test_no_public_text_is_a_failed_fetch():
    assert detect_blocked_page("（Instagram 貼文未提供公開文字說明）") == "no_public_text"


@pytest.mark.asyncio
async def test_the_post_is_kept_with_what_to_do_and_no_ai_guess():
    page = {"url": POST, "title": "Instagram 貼文", "content_raw": "（Instagram 貼文未提供公開文字說明）",
            "cover_image": "", "author": "Instagram", "published_date": ""}
    provider = AsyncMock()
    with patch.object(pipeline, "parse_web_page", new=AsyncMock(return_value=page)), \
         patch.object(pipeline, "get_primary_provider", return_value=provider), \
         patch("app.snapshot.save_html_snapshot"):
        item = await pipeline.run_pipeline(POST)
    provider.generate_json.assert_not_called()
    assert item["title_l1"] == "Instagram 貼文（讀不到內容）"
    assert "書籤小工具" in item["summary_l1"] and "貼成筆記" in item["summary_l1"]
    assert "無法解析" not in item["title_l1"]
