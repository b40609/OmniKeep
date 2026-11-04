import pytest
from app.research.competitor_detector import detect_competitors_and_alternatives
from app.research.tool_resolver import resolve_taiwan_counterpart
from app.bot.telegram_bot import TelegramBot
from app.database import save_item, save_citation, get_sub_entities_for_parent

@pytest.mark.asyncio
async def test_resolve_taiwan_counterpart():
    # Should resolve for regional keyword like 润学
    res = await resolve_taiwan_counterpart("润学指南", "把Github上的润学指南拿到墙内卖")
    assert res is not None
    assert "f2etw" in res["name"] or "developer-roadmap" in res["name"]
    assert "http" in res["canonical_url"]
    assert "[台灣對等資源]" in res["reason"]

    # Should not resolve for non-regional generic tools
    res_none = await resolve_taiwan_counterpart("fastapi", "A high performance web framework")
    assert res_none is None


@pytest.mark.asyncio
async def test_telegram_bot_card_sections():
    # Mock item
    mock_item = {
        "id": "test_card_item_123",
        "url": "https://example.com/tool",
        "category_name": "Inbox",
        "title_l1": "測試工具 A",
        "summary_l1": "這是一個測試工具",
        "tech_tags": ["AI", "Web"],
        "deep_analysis": "剖析內容"
    }
    save_item(mock_item)

    # Citations with competitor, taiwan counterpart, and verified tool
    save_citation({
        "source_parent_id": "test_card_item_123",
        "target_canonical_url": "https://github.com/test/comp",
        "target_name": "測試競品 B",
        "mention_context": "[庫內競品] 兩者為同賽道競品，測試工具 A 適合本地部署"
    })
    save_citation({
        "source_parent_id": "test_card_item_123",
        "target_canonical_url": "https://github.com/f2etw/jobs",
        "target_name": "f2etw/jobs",
        "mention_context": "[台灣對等資源] 台灣工程師海外求職看板"
    })
    save_citation({
        "source_parent_id": "test_card_item_123",
        "target_canonical_url": "https://github.com/upstream/repo",
        "target_name": "原專案",
        "mention_context": "文中提及之官方專案 (★10,000)"
    })

    bot = TelegramBot(token="mock")
    card_html = bot.build_item_card_html(mock_item)

    assert "庫內競品與關聯提醒" in card_html
    assert "測試競品 B" in card_html
    assert "台灣/在地對等資源" in card_html
    assert "f2etw/jobs" in card_html
    assert "提及開源專案" in card_html
    assert "原專案" in card_html
