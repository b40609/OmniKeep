import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.database import (
    tune_topic_signal,
    save_item,
    get_item_by_id,
    get_swipe_deck,
    get_pending_analysis_items,
    get_interest_profile,
    get_interest_profile_record,
    set_interest_profile,
    get_db_connection
)
from contextlib import closing
from app.radar.recommender import score_item_detailed, score_item, rank_items_with_exploration
from app.radar.scheduler import (
    build_weight_index,
    pregate_item,
    _save_deferred_stub,
    _maybe_autostar,
    _backfill_pending
)
from app.pipeline import interest_profile_block
from app.watch.taste import rank_deck
from app.bot.telegram_bot import build_deck_card_html, TelegramBot


# ── 1. score_item_detailed & Transparent Reasons ──────────────

def test_score_item_detailed_transparent_reasons():
    tune_topic_signal("FastAPI", "boost")
    tune_topic_signal("SpamCrypto", "mute")

    # 1. Normal boosted item in Tier 1
    detail = score_item_detailed(["FastAPI", "Python"], tier=1)
    assert not detail["blocked"]
    assert detail["score"] > 1.25
    assert detail["tier_mult"] == 1.25
    assert any("FastAPI" in r for r in detail["reasons"])
    assert any("Tier 1" in r for r in detail["reasons"])

    # 2. Tier 3 multiplier
    detail_t3 = score_item_detailed(["FastAPI"], tier=3)
    assert detail_t3["tier_mult"] == 0.75
    assert any("Tier 3" in r for r in detail_t3["reasons"])

    # 3. Exploration card reasons
    detail_exp = score_item_detailed(["Python"], tier=2, is_exploration=True)
    assert any("探索卡" in r for r in detail_exp["reasons"])

    # 4. Muted tag hard block
    detail_muted = score_item_detailed(["SpamCrypto", "FastAPI"], tier=1)
    assert detail_muted["blocked"]
    assert detail_muted["score"] == -999.0
    assert any("SpamCrypto" in r for r in detail_muted["reasons"])

    # 5. Backward compatibility
    score, blocked = score_item(["FastAPI", "Python"], tier=1)
    assert score == detail["score"]
    assert blocked == detail["blocked"]


# ── 2. Free Local Pre-Gate ───────────────────────────────────

def test_pregate_item_cost_gate():
    tune_topic_signal("AgentAI", "boost")
    tune_topic_signal("CasinoScam", "mute")

    weight_index = build_weight_index()
    assert any(tag == "agentai" for tag, _, _ in weight_index)
    assert any(tag == "casinoscam" and blocked for tag, _, blocked in weight_index)

    # 1. Blocked keyword hit drops immediately
    score, blocked = pregate_item("Join the best CasinoScam today", "https://scam.example", "", weight_index)
    assert blocked
    assert score == -999.0

    # 2. Boosted keyword hit gets positive pre-gate score
    score_boost, blocked_boost = pregate_item("New AgentAI multi-agent framework", "https://github.com/agentai/demo", "", weight_index)
    assert not blocked_boost
    assert score_boost > 1.0

    # 3. Neutral / unknown item defaults to 1.0
    score_neu, blocked_neu = pregate_item("Some ordinary title", "https://example.com/post", "", weight_index)
    assert not blocked_neu
    assert score_neu == 1.0


# ── 3. Deferred Stubs, Pending Queue & Backfill ──────────────

@pytest.mark.asyncio
async def test_deferred_stubs_and_pending_backfill():
    class DummyRaw:
        url = "https://example.com/deferred-1"
        source_type = "rss"
        title = "Deferred Candidate 1"
        content = "Raw content for deferred candidate"
        author = "Reporter"

    # Save as deferred stub
    item_id = _save_deferred_stub(DummyRaw())
    item = get_item_by_id(item_id)
    assert item is not None
    assert item["analysis_status"] == "pending"
    assert item["title_l1"] == "Deferred Candidate 1"

    # Pending items do NOT enter swipe deck
    deck = get_swipe_deck(limit=10)
    assert not any(it["id"] == item_id for it in deck)

    # Pending queue lists it
    pending = get_pending_analysis_items(limit=10)
    assert any(it["id"] == item_id for it in pending)

    # Backfill processes pending stub using mocked pipeline
    mock_analyzed = {
        "id": item_id,
        "url": DummyRaw.url,
        "tech_tags": ["FastAPI"],
        "title_l1": "Analyzed Title",
        "analysis_status": "done"
    }
    with patch("app.radar.scheduler._analyze_candidate", new_callable=AsyncMock) as mock_analyze:
        mock_analyze.return_value = mock_analyzed
        results = await _backfill_pending(budget=5)
        assert len(results) == 1
        assert results[0]["id"] == item_id
        mock_analyze.assert_called_once_with(DummyRaw.url, tier=2)


# ── 4. Auto-Star Tiering ──────────────────────────────────────

def test_autostar_tiering():
    # Save a test item
    item_id = save_item({
        "url": "https://example.com/high-score-item",
        "title_l1": "Critical Breakthrough in Local AI",
        "category_name": "AI",
        "tech_tags": ["FastAPI", "LocalAI"],
        "origin": "radar",
        "analysis_status": "done"
    })
    item = get_item_by_id(item_id)
    assert item["is_starred"] == 0

    # Item with score >= 2.5 triggers autostar
    detail_high = {
        "score": 2.8,
        "reasons": ["🏷️ 你對「LocalAI」的權重 2.5", "📡 Tier 1 官方來源 ×1.25"]
    }
    _maybe_autostar(item, detail_high)
    assert item.get("auto_starred") is True

    reloaded = get_item_by_id(item_id)
    assert reloaded["is_starred"] == 1

    # Check behavior event logged
    with closing(get_db_connection()) as conn:
        auto_star_event = conn.execute(
            "SELECT * FROM behavior_events WHERE item_id = ? AND event_type = 'auto_star'",
            (item_id,)
        ).fetchone()
    assert auto_star_event is not None
    assert auto_star_event["source"] == "radar"

    # Item below threshold does not trigger
    item_low_id = save_item({
        "url": "https://example.com/low-score-item",
        "title_l1": "Average tech blog post",
        "category_name": "General",
        "tech_tags": ["Tech"],
        "origin": "radar"
    })
    item_low = get_item_by_id(item_low_id)
    _maybe_autostar(item_low, {"score": 1.5, "reasons": []})
    assert item_low.get("auto_starred") is None
    assert get_item_by_id(item_low_id)["is_starred"] == 0


# ── 5. Interest Profile DAO, Prompt Block & REST API ─────────

@pytest.mark.asyncio
async def test_interest_profile_lifecycle_and_api():
    from app.main import app

    # Initial state
    assert get_interest_profile() == ""

    # Set profile
    profile_text = "專注於自託管第二大腦、Rust 嵌入式系統、量化架構"
    assert set_interest_profile(profile_text) is True

    rec = get_interest_profile_record()
    assert rec["profile"] == profile_text
    assert rec["updated_at"] is not None

    # Prompt block injection
    block = interest_profile_block()
    assert "使用者興趣設定檔" in block
    assert "自託管第二大腦" in block

    # REST API integration
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        # GET
        res_get = await client.get("/api/radar/profile")
        assert res_get.status_code == 200
        assert res_get.json()["profile"] == profile_text

        # PUT
        new_text = "專注於 Python 高性能非同步後端與 SQLite WAL"
        res_put = await client.put("/api/radar/profile", json={"profile": new_text})
        assert res_put.status_code == 200
        assert res_put.json()["profile"] == new_text

        # Re-query
        assert get_interest_profile() == new_text


# ── 6. Explainable Recommendations in Deck & Telegram ─────────

@pytest.mark.asyncio
async def test_explainable_deck_and_telegram(monkeypatch):
    tune_topic_signal("FastAPI", "boost")
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:fake-token-for-test")

    items = [
        {
            "id": "deck_1",
            "url": "https://example.com/deck1",
            "title_l1": "FastAPI 0.115 Deep Dive",
            "summary_l1": "Exploring new lifespan handlers",
            "tech_tags": ["FastAPI"],
            "origin": "radar"
        },
        {
            "id": "deck_2",
            "url": "https://example.com/deck2",
            "title_l1": "General Computing",
            "summary_l1": "Basic computing primer",
            "tech_tags": ["General"],
            "origin": "radar"
        }
    ]

    ranked = rank_deck(items, exploration_ratio=0.5)
    assert len(ranked) == 2
    for card in ranked:
        assert "reasons" in card
        assert len(card["reasons"]) > 0

    # Telegram card HTML rendering
    card_html = build_deck_card_html(ranked[0], remaining=1)
    assert "為什麼給你看：" in card_html
    assert "FastAPI" in card_html

    # Telegram bot /profile command
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", "12345")
    bot = TelegramBot()
    with patch.object(bot, "send_message", new_callable=AsyncMock) as mock_send:
        # View profile
        await bot.handle_update({
            "message": {
                "message_id": 1,
                "chat": {"id": 12345},
                "from": {"id": 12345},
                "text": "/profile"
            }
        })
        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][1]
        assert "當前興趣設定檔" in sent_text

        mock_send.reset_mock()
        # Update profile via Telegram
        await bot.handle_update({
            "message": {
                "message_id": 2,
                "chat": {"id": 12345},
                "from": {"id": 12345},
                "text": "/profile 深入量化交易系統與機電振動監測"
            }
        })
        mock_send.assert_called_once()
        sent_update = mock_send.call_args[0][1]
        assert "興趣設定檔已更新" in sent_update
        assert get_interest_profile() == "深入量化交易系統與機電振動監測"
