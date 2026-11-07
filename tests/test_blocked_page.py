"""A site's error / anti-bot page is not analysed as if it were the article (2026-11-07)."""
from unittest.mock import AsyncMock, patch

import pytest

from app import database as db
from app.parsers.blocked import EMPTY_PLACEHOLDER, detect_blocked_page, is_error_title, reason_text
from app.pipeline import FETCH_FAILED_TAG, METADATA_ONLY_TAG, run_pipeline

X_PAGE = ("We’ve detected that JavaScript is disabled in this browser. Please enable JavaScript or switch to a "
          "supported browser to continue using x.com. You can see a list of supported browsers in our Help "
          "Center.\nHelp Center\nTerms of Service Privacy Policy Cookie Policy Imprint Ads info © 2026 X Corp.")
CF_ZH = ("transitfeeds.com\n正在執行安全驗證\n此網站使用安全服務抵禦惡意機器人。當網站驗證並確認您不是機器人時，"
         "便會顯示此頁面。\n驗證成功。正在等待 transitfeeds.com 回應\nEnable JavaScript and cookies to continue")
CF_EN = ("Just a moment...\nexample.com\nVerifying you are human. This may take a few seconds.\n"
         "example.com needs to review the security of your connection before proceeding.\n"
         "Ray ID: 8f1a2b3c4d5e6f70\nPerformance & security by Cloudflare")
SOUNDCLOUD = ("JavaScript is disabled\nYou need to enable JavaScript to use SoundCloud\nYour current browser isn't "
              "compatible with SoundCloud. Please download one of our supported browsers. Need help?\nSorry! "
              "Something went wrong\nIs your network connection unstable or browser outdated?\n"
              "Popular searches Privacy Policy Cookie Policy")
AKAMAI = ("Access Denied\nYou don't have permission to access \"http://www.example.com/\" on this server.\n"
          "Reference #18.2f3e4d5c.1730960000.1a2b3c4d")
NOT_FOUND = ("One banana, two banana, three banana, four , whatever you requested came back 404.\nWe couldn't find "
             "the file you requested. If you're lost, you might try:\nFind out more about the new WCA certification")
VERCEL = "It may have been moved, removed, or never existed.\n404 DEPLOYMENT_NOT_FOUND\nhkg1::j9zsn-1792901230453-79b93921aff6"
# A single-page app's <noscript> line followed by the page's real text.
SPA = ("You need to enable JavaScript to run this app.\n"
       + "在 Ethereum、Unichain、Base 等 23 個以上的網路上買賣加密貨幣，零 App 手續費。\n" * 8
       + "Uniswap Labs 在一個平台上提供鏈上經濟的全部要素：零費用交易、經過驗證的安全性和深厚的流動性。")


@pytest.mark.parametrize("text, reason", [
    (X_PAGE, "js_required"), (SOUNDCLOUD, "js_required"), (CF_ZH, "bot_check"), (CF_EN, "bot_check"),
    (AKAMAI, "access_denied"), (NOT_FOUND, "not_found"), (VERCEL, "not_found"),
    (EMPTY_PLACEHOLDER, "empty"), ("", "empty"),
])
def test_error_pages_are_recognised(text, reason):
    assert detect_blocked_page(text) == reason


@pytest.mark.parametrize("text", [
    SPA,
    # Short posts that mention the same words but say something.
    "Pro tip: enable JavaScript source maps in Chrome DevTools to debug minified bundles. "
    "It saves hours when tracking production errors in React apps.",
    "Our API returned Access Denied for an hour. The fix was rotating the IAM role and adding s3:GetObject "
    "to the bucket policy, then redeploying every Lambda function behind the gateway.",
    "12. Cloudflare Workers AI 每天有免費額度可以領；13. GitHub Copilot Free 每月 2,000 次補全。",
    "Reddit is announcing a huge shift: it's going to start requiring users to log in.",
    # Long enough that an error phrase inside it is a quote, not the whole page.
    X_PAGE + "\n" + "這篇長文接著解釋 X 為什麼這樣擋爬蟲，以及開發者可以怎麼處理。" * 80,
])
def test_real_content_is_left_alone(text):
    assert detect_blocked_page(text) is None


def test_an_http_error_with_no_body_names_the_status():
    assert detect_blocked_page(EMPTY_PLACEHOLDER, http_status=404) == "http_error"
    assert "HTTP 404" in reason_text("http_error", 404)


@pytest.mark.parametrize("title, useless", [
    ("Just a moment...", True), ("X", True), ("未知標題", True), ("404 Not Found", True),
    ("Midjourney", False), ("小草莓 on X: 天涯大佬又甩出猛料了", False),
])
def test_error_titles(title, useless):
    assert is_error_title(title) is useless


# --- the pipeline ----------------------------------------------------------------------------

X_URL = "https://x.com/someone/status/2117019351056596996"
AI = {"category": "Inbox", "title_l1": "推文重點", "summary_l1": "推文在講免費 API 額度。", "tech_tags": ["API"],
      "deep_analysis": "## 重點\n- 免費額度", "is_composite": True,
      "sub_entities": [{"name": "made-up", "canonical_url": "https://github.com/made/up", "reason": "猜的"}]}


def _page(content, title="X", status=200):
    return {"url": X_URL, "title": title, "content_raw": content, "cover_image": "", "author": "",
            "published_date": "", "raw_html": "<html>error page</html>", "http_status": status}


def _provider():
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=dict(AI))
    return provider


@pytest.fixture
def follow_ups():
    with patch("app.research.tool_resolver.resolve_mentioned_tools", new=AsyncMock(return_value=[])) as tools, \
         patch("app.research.competitor_detector.detect_competitors_and_alternatives", new=AsyncMock()) as rivals, \
         patch("app.snapshot.save_html_snapshot") as snapshot:
        yield tools, rivals, snapshot


@pytest.mark.asyncio
async def test_an_error_page_with_nothing_else_gets_no_ai_analysis(follow_ups):
    provider = _provider()
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(X_PAGE))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        item = await run_pipeline(X_URL)
    provider.generate_json.assert_not_awaited()
    stored = db.get_item_by_id(item["id"])
    assert stored["summary_l1"].startswith(FETCH_FAILED_TAG) and "JavaScript" in stored["summary_l1"]
    assert stored["deep_analysis"].startswith("> ⚠️ 擷取失敗")
    assert stored["title_l1"] == "x.com/someone/status/2117019351056596996"
    assert stored["tech_tags"] == []
    assert stored["content_raw"] == X_PAGE  # the evidence is kept
    tools, rivals, snapshot = follow_ups
    tools.assert_not_awaited(), rivals.assert_not_awaited(), snapshot.assert_not_called()


@pytest.mark.asyncio
async def test_an_error_page_with_the_browser_view_is_analysed_from_that_only(follow_ups):
    provider = _provider()
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(X_PAGE))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        item = await run_pipeline(X_URL, page_title="someone on X: 免費 API 整理",
                                  page_description="續集來了，還有一些可以免費用的 API 平台")
    provider.generate_json.assert_awaited_once()
    prompt = provider.generate_json.await_args.args[0]
    assert "免費 API 整理" in prompt and "續集來了" in prompt
    assert "detected that JavaScript" not in prompt  # the error page itself is never shown to the AI
    assert item["summary_l1"].startswith(METADATA_ONLY_TAG)
    assert item["deep_analysis"].startswith("> ⚠️ 證據不足") and "JavaScript" in item["deep_analysis"]
    assert "## 重點" in item["deep_analysis"]
    tools, rivals, _ = follow_ups
    tools.assert_not_awaited(), rivals.assert_not_awaited()  # no made-up sub-projects collected


@pytest.mark.asyncio
async def test_a_404_with_no_body_is_marked_with_the_status(follow_ups):
    provider = _provider()
    with patch("app.pipeline.parse_web_page",
               new=AsyncMock(return_value=_page(EMPTY_PLACEHOLDER, title="未知標題", status=404))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        item = await run_pipeline("https://github.com/made/up")
    provider.generate_json.assert_not_awaited()
    assert item["summary_l1"].startswith(FETCH_FAILED_TAG) and "HTTP 404" in item["summary_l1"]


@pytest.mark.asyncio
async def test_a_real_page_is_analysed_as_before(follow_ups):
    provider = _provider()
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(SPA, title="Uniswap"))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        item = await run_pipeline("https://uniswap.org")
    provider.generate_json.assert_awaited_once()
    assert "Unichain" in provider.generate_json.await_args.args[0]
    assert item["summary_l1"] == AI["summary_l1"] and item["deep_analysis"] == AI["deep_analysis"]
