"""Tests for Dream Pass (Taste Self-Reflection Engine) and New Radar Adapters

Covers:
- Taste signals aggregation & reflection heuristics
- Dream Pass proposal lifecycle (run -> latest -> apply -> dismiss)
- Dream Pass REST endpoints (/api/radar/profile/dreampass/*)
- Telegram /dreampass command and inline button callbacks
- GoogleNewsAdapter query normalization & feed parsing
- WebChangeAdapter content hashing & change detection
"""
import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from app.main import app
from app.database import (
    init_db,
    save_item,
    log_behavior_event,
    set_interest_profile,
    get_interest_profile,
    get_latest_dreampass_proposal,
    apply_dreampass_proposal,
    dismiss_dreampass_proposal,
)
from app.radar.dreampass import run_dreampass_reflection
from app.radar.adapters.google_news import GoogleNewsAdapter
from app.radar.adapters.web_change import WebChangeAdapter
from app.radar.adapters import get_adapter
from app.bot.telegram_bot import TelegramBot
from app.config import settings


@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()


def test_dreampass_proposal_flow():
    set_interest_profile("原始關注：分佈式系統與後端工程。")

    # Ingest test items and behavior events
    item_id_1 = save_item({
        "url": "https://example.com/sqlite-vec-guide",
        "title_l1": "sqlite-vec 向量檢索深度實戰",
        "summary_l1": "介紹如何在 SQLite 嵌入 256 維向量並進行餘弦近似搜尋",
        "source_type": "web",
        "category_name": "Dev",
        "tech_tags": ["sqlite-vec", "vector", "ai"],
    })
    item_id_2 = save_item({
        "url": "https://example.com/css-magic",
        "title_l1": "CSS 排版炫彩效果大全",
        "summary_l1": "前端 CSS 炫彩特效",
        "source_type": "web",
        "category_name": "Design",
        "tech_tags": ["css", "frontend"],
    })

    # Positive signal on item 1 (star + boost), negative on item 2 (dampen)
    log_behavior_event("swipe_star", item_id=str(item_id_1))
    log_behavior_event("boost", item_id=str(item_id_1))
    log_behavior_event("dampen", item_id=str(item_id_2))

    # Run Dream Pass reflection
    import asyncio
    prop = asyncio.run(run_dreampass_reflection(days=7))

    assert prop["id"] > 0
    assert prop["status"] == "pending"
    assert "sqlite-vec" in prop["observations"] or "sqlite-vec" in prop["diff_summary"] or "sqlite-vec" in prop["suggested_profile"]
    assert len(prop["suggested_profile"]) > 0

    # Retrieve latest
    latest = get_latest_dreampass_proposal(status="pending")
    assert latest is not None
    assert latest["id"] == prop["id"]

    # Apply proposal
    applied = apply_dreampass_proposal(prop["id"])
    assert applied is True

    # Verify interest profile updated
    updated_prof = get_interest_profile()
    assert updated_prof == prop["suggested_profile"]

    # Re-apply should return False (already applied)
    assert apply_dreampass_proposal(prop["id"]) is False


def test_dreampass_rest_api():
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.API_KEY}"}

    # 1. Trigger run
    run_resp = client.post("/api/radar/profile/dreampass/run?days=7", headers=headers)
    assert run_resp.status_code == 200
    data = run_resp.json()
    assert data["success"] is True
    prop_id = data["proposal"]["id"]

    # 2. Get latest
    get_resp = client.get("/api/radar/profile/dreampass/latest", headers=headers)
    assert get_resp.status_code == 200
    assert get_resp.json()["proposal"]["id"] == prop_id

    # 3. Dismiss proposal
    dismiss_resp = client.post(f"/api/radar/profile/dreampass/{prop_id}/dismiss", headers=headers)
    assert dismiss_resp.status_code == 200
    assert dismiss_resp.json()["success"] is True

    # 4. Try to apply dismissed proposal -> fails with 400
    apply_resp = client.post(f"/api/radar/profile/dreampass/{prop_id}/apply", headers=headers)
    assert apply_resp.status_code == 400


def test_telegram_dreampass_command_and_callback(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "fake-token-dreampass")
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", "999")

    bot = TelegramBot()
    bot.send_message = AsyncMock(return_value={"message_id": 100})
    bot.send_api = AsyncMock(return_value={"ok": True})
    bot.answer_callback_query = AsyncMock(return_value=True)

    # 1. /dreampass command
    update_cmd = {
        "message": {
            "message_id": 10,
            "chat": {"id": 999},
            "from": {"id": 999},
            "text": "/dreampass",
        }
    }
    import asyncio
    asyncio.run(bot.handle_update(update_cmd))
    assert bot.send_message.called
    sent_text = bot.send_message.call_args[0][1]
    assert "Dream Pass" in sent_text

    # 2. Callback query to apply
    latest_prop = get_latest_dreampass_proposal(status="pending")
    assert latest_prop is not None
    p_id = latest_prop["id"]

    update_callback = {
        "callback_query": {
            "id": "query-dp-1",
            "from": {"id": 999},
            "message": {"message_id": 100, "chat": {"id": 999}},
            "data": f"dreampass:{p_id}:apply",
        }
    }
    asyncio.run(bot.handle_update(update_callback))
    assert bot.answer_callback_query.called
    assert "成功採用" in bot.answer_callback_query.call_args[0][1]


def test_google_news_adapter():
    adapter = GoogleNewsAdapter()
    assert get_adapter("google_news") is not None

    # Test query normalization
    norm_query = adapter._normalize_feed_url("FastAPI AI")
    assert "news.google.com/rss/search" in norm_query
    assert "FastAPI%20AI" in norm_query

    direct_url = "https://news.google.com/rss/topics/xyz"
    assert adapter._normalize_feed_url(direct_url) == direct_url

    # Mock fetch latest
    sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Google 新聞 - FastAPI</title>
        <item>
          <title>FastAPI 0.115 發布全面支援 Pydantic v2 - iThome 電腦報</title>
          <link>https://news.google.com/articles/CAIiE12345</link>
          <description>深入探討最新版 FastAPI 效能表現與新特性...</description>
          <pubDate>Mon, 26 Oct 2026 12:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>
    """
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_rss
    mock_resp.headers = {"etag": "etag-gn-1", "last-modified": "Mon, 26 Oct 2026 12:00:00 GMT"}

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.radar.adapters.google_news.public_http_client", return_value=mock_client):
        import asyncio
        items = asyncio.run(adapter.fetch_latest({
            "id": 888,
            "url": "FastAPI",
            "name": "FastAPI Google News",
            "tier": 1
        }))
        assert len(items) == 1
        item = items[0]
        assert item.source_type == "google_news"
        # Verify title suffix stripped
        assert item.title == "FastAPI 0.115 發布全面支援 Pydantic v2"
        assert item.author == "iThome 電腦報"
        assert item.url == "https://news.google.com/articles/CAIiE12345"


def test_web_change_adapter():
    adapter = WebChangeAdapter()
    assert get_adapter("web_change") is not None

    page_html_v1 = """<!DOCTYPE html>
    <html>
      <head><title>Anthropic Engineering Blog</title></head>
      <body>
        <h1>Engineering Updates</h1>
        <p>October 2026: Announcing Model Context Protocol updates.</p>
      </body>
    </html>"""

    mock_resp1 = MagicMock()
    mock_resp1.status_code = 200
    mock_resp1.text = page_html_v1

    mock_client1 = AsyncMock()
    mock_client1.get = AsyncMock(return_value=mock_resp1)
    mock_client1.__aenter__ = AsyncMock(return_value=mock_client1)
    mock_client1.__aexit__ = AsyncMock(return_value=None)

    from app.database import save_radar_source, get_radar_source
    src_id = save_radar_source({
        "name": "Anthropic Blog",
        "source_type": "web_change",
        "url": "https://example.com/engineering",
        "tier": 1,
    })
    source = get_radar_source(src_id)

    import asyncio
    with patch("app.radar.adapters.web_change.public_http_client", return_value=mock_client1):
        items1 = asyncio.run(adapter.fetch_latest(source))
        assert len(items1) == 1
        assert "Model Context Protocol updates" in items1[0].content
        assert items1[0].source_type == "web_change"

    # Second check with same content -> should return [] (no changes)
    updated_source = get_radar_source(src_id)
    # Etag now holds the sha256 hash
    with patch("app.radar.adapters.web_change.public_http_client", return_value=mock_client1):
        items2 = asyncio.run(adapter.fetch_latest(updated_source))
        assert len(items2) == 0

    # Content changes
    page_html_v2 = """<!DOCTYPE html>
    <html>
      <head><title>Anthropic Engineering Blog</title></head>
      <body>
        <h1>Engineering Updates</h1>
        <p>November 2026: Announcing breakthrough in autonomous reasoning.</p>
      </body>
    </html>"""
    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.text = page_html_v2

    mock_client2 = AsyncMock()
    mock_client2.get = AsyncMock(return_value=mock_resp2)
    mock_client2.__aenter__ = AsyncMock(return_value=mock_client2)
    mock_client2.__aexit__ = AsyncMock(return_value=None)

    with patch("app.radar.adapters.web_change.public_http_client", return_value=mock_client2):
        items3 = asyncio.run(adapter.fetch_latest(updated_source))
        assert len(items3) == 1
        assert "autonomous reasoning" in items3[0].content
