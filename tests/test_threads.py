import json
from unittest.mock import AsyncMock, patch
import pytest

from app.parsers.threads import (
    is_threads_url,
    normalize_threads_canonical_url,
    extract_threads_title,
    parse_threads_page,
)
from app.parsers.web import parse_web_page
from app.pipeline import run_pipeline


def test_is_threads_url():
    assert is_threads_url("https://www.threads.net/@demo.author/post/DemoPost001")
    assert is_threads_url("https://threads.net/@user/post/12345")
    assert is_threads_url("https://www.threads.com/share/ShareDemo1")
    assert is_threads_url("https://threads.com/t/ShareDemo2")
    assert is_threads_url("http://l.threads.net/something")
    assert not is_threads_url("https://www.facebook.com/reel/12345")
    assert not is_threads_url("https://www.instagram.com/reel/12345")
    assert not is_threads_url("https://github.com/fastapi/fastapi")
    assert not is_threads_url("invalid_url")
    assert not is_threads_url("")


def test_normalize_threads_canonical_url():
    assert normalize_threads_canonical_url(
        "https://www.threads.com/@sample.brand/post/DemoPost002?xmt=FAKEtoken0"
    ) == "https://www.threads.net/@sample.brand/post/DemoPost002"

    assert normalize_threads_canonical_url(
        "https://threads.net/@Demo.Author/post/DemoPost001#fragment"
    ) == "https://www.threads.net/@demo.author/post/DemoPost001"

    assert normalize_threads_canonical_url(
        "https://www.threads.net/t/ShareDemo2?s=09"
    ) == "https://www.threads.net/t/ShareDemo2"


def test_extract_threads_title():
    caption = "原本以為要自己盯盤，結果有人寫了 11 個 Claude skill\n自動掃圖..."
    raw_title = "Threads 上的王小明（@demo.author）"
    author = "王小明 (@demo.author)"

    title = extract_threads_title(raw_title, caption, author)
    assert "11 個 Claude skill" in title

    # Empty caption fallback
    title_fallback = extract_threads_title(raw_title, "", author)
    assert title_fallback == "王小明（@demo.author）"


@pytest.mark.asyncio
async def test_parse_threads_page_with_relay():
    fake_relay_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:site_name" content="Threads" />
        <meta property="og:title" content="Threads 上的王小明（@demo.author）" />
        <meta property="og:description" content="原本以為要自己盯盤，結果有人寫了 11 個 Claude skill" />
        <meta property="og:image" content="https://scontent.fake/cover.jpg" />
        <meta property="og:url" content="https://www.threads.net/@demo.author/post/DemoPost001" />
    </head>
    <body>
        <script>
        {"require": [[
            "ScheduledServerJS", "handle", null, [{
                "__bbox": {
                    "require": [[
                        "RelayPrefetchedStreamCache", "next", [], [
                            "query_id", {
                                "__bbox": {
                                    "result": {
                                        "data": {
                                            "media": {
                                                "user": {"username": "demo.author", "full_name": "王小明"},
                                                "caption": {"text": "原本以為要自己盯盤，結果有人寫了 11 個 Claude skill 自動掃盤！"},
                                                "taken_at": 1740000000,
                                                "like_count": 888,
                                                "image_versions2": {"candidates": [{"url": "https://scontent.fake/highres.jpg"}]},
                                                "video_versions": []
                                            }
                                        }
                                    }
                                }
                            }
                        ]
                    ]]
                }
            }]
        ]]}
        </script>
        <script>
        {"require": [[
            "ScheduledServerJS", "handle", null, [{
                "__bbox": {
                    "require": [[
                        "RelayPrefetchedStreamCache", "next", [], [
                            "query_reply", {
                                "__bbox": {
                                    "result": {
                                        "data": {
                                            "thread_items": [
                                                {
                                                    "post": {
                                                        "user": {"username": "demo.author"},
                                                        "caption": {"text": "開源地址已發在 GitHub: github.com/test/quant"}
                                                    }
                                                },
                                                {
                                                    "post": {
                                                        "user": {"username": "trader_bob"},
                                                        "caption": {"text": "太強了！已收藏測試"}
                                                    }
                                                }
                                            ]
                                        }
                                    }
                                }
                            }
                        ]
                    ]]
                }
            }]
        ]]}
        </script>
    </body>
    </html>
    """

    fake_resp = AsyncMock()
    fake_resp.status_code = 200
    fake_resp.text = fake_relay_html
    fake_resp.url = "https://www.threads.com/@demo.author/post/DemoPost001"

    mock_client_instance = AsyncMock()
    mock_client_instance.get.return_value = fake_resp
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.__aexit__.return_value = None

    with patch("app.parsers.threads.public_http_client", return_value=mock_client_instance):
        result = await parse_threads_page("https://www.threads.com/share/ShareDemo1")

    assert result["url"] == "https://www.threads.net/@demo.author/post/DemoPost001"
    assert "11 個 Claude skill" in result["title"]
    assert "王小明" in result["author"]
    assert "@demo.author" in result["author"]
    assert "原本以為要自己盯盤" in result["content_raw"]
    assert "github.com/test/quant" in result["content_raw"]
    assert "@trader_bob" in result["content_raw"]
    assert result["cover_image"] == "https://scontent.fake/cover.jpg"
    assert result["source_type"] == "threads"


@pytest.mark.asyncio
async def test_parse_threads_page_og_fallback():
    fake_og_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta property="og:site_name" content="Threads" />
        <meta property="og:title" content="Threads 上的 範例品牌官方帳號（@sample.brand）" />
        <meta property="og:description" content="範例品牌上線新功能：支援 10 萬根 K 棒策略回測" />
        <meta property="og:image" content="https://scontent.fake/brand.jpg" />
        <meta property="og:url" content="https://www.threads.net/@sample.brand/post/DemoPost002" />
    </head>
    <body>
        <div>僅有簡短 SSR 結構</div>
    </body>
    </html>
    """

    fake_resp = AsyncMock()
    fake_resp.status_code = 200
    fake_resp.text = fake_og_html
    fake_resp.url = "https://www.threads.com/share/ShareDemo2"

    mock_client_instance = AsyncMock()
    mock_client_instance.get.return_value = fake_resp
    mock_client_instance.__aenter__.return_value = mock_client_instance
    mock_client_instance.__aexit__.return_value = None

    with patch("app.parsers.threads.public_http_client", return_value=mock_client_instance):
        # Also test dispatch through parse_web_page
        result = await parse_web_page("https://www.threads.com/share/ShareDemo2")

    assert result["url"] == "https://www.threads.net/@sample.brand/post/DemoPost002"
    assert "範例品牌上線新功能" in result["title"]
    assert "範例品牌" in result["author"]
    assert "10 萬根 K 棒策略回測" in result["content_raw"]
    assert result["cover_image"] == "https://scontent.fake/brand.jpg"


@pytest.mark.asyncio
async def test_threads_pipeline_routing():
    fake_parsed = {
        "url": "https://www.threads.net/@sample.dev/post/DemoPost003",
        "title": "先別急著疊因子，挑一個簡單策略",
        "content_raw": "台股資料跟蒙地卡羅檢定都內建在 Demo Agent，github.com/example/demo-agent",
        "cover_image": "https://scontent.fake/demo.jpg",
        "author": "陳大文 (@sample.dev)",
        "published_date": "2025-02-19T10:00:00+00:00",
        "source_type": "threads",
        "raw_html": "",
        "meta": {}
    }

    fake_ai_output = {
        "category": "AI",
        "title_l1": "Demo Agent：台股量化與蒙地卡羅檢定開源框架",
        "summary_l1": "內建台股完整歷史數據與蒙地卡羅驗證，簡化量化因子疊加測試。",
        "tech_tags": ["台股量化", "蒙地卡羅檢定", "Demo Agent"],
        "deep_analysis": "技術架構剖析...",
        "is_composite": False,
        "sub_entities": []
    }

    mock_provider = AsyncMock()
    mock_provider.generate_json.return_value = fake_ai_output

    with patch("app.pipeline.parse_threads_page", AsyncMock(return_value=fake_parsed)), \
         patch("app.pipeline.get_primary_provider", return_value=mock_provider), \
         patch("app.database.save_item", return_value="item-123"), \
         patch("app.pipeline.get_all_categories", return_value=[{"name": "AI"}, {"name": "Finance"}]):

        item = await run_pipeline("https://www.threads.com/share/ShareDemo3")
        assert item["source_type"] == "threads"
        assert item["title_l1"] == "Demo Agent：台股量化與蒙地卡羅檢定開源框架"
        assert "Demo Agent" in item["tech_tags"]
