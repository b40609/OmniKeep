import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.bot.telegram_bot import (
    TelegramBot,
    build_failure_keyboard,
    notify_task_failed,
    notify_task_completed,
)
from app.database import (
    init_db,
    create_ingest_task,
    get_ingest_task,
    save_item,
    get_item_by_id,
    get_db_connection,
)


def setup_module(module):
    init_db()


@pytest.mark.asyncio
async def test_multi_url_and_note_extraction(monkeypatch):
    bot = TelegramBot(token="123456:dummy-token-for-test")
    bot.is_authorized = MagicMock(return_value=True)
    bot.send_message = AsyncMock(return_value={"ok": True, "result": {"message_id": 999}})
    bot.set_message_reaction = AsyncMock(return_value=True)

    text = "這兩個專案架構值得參考 https://github.com/astral-sh/uv https://github.com/fastfetch-cli/fastfetch"
    update = {
        "update_id": 880,
        "message": {
            "chat": {"id": 12345},
            "from": {"id": 12345},
            "message_id": 77,
            "text": text,
        }
    }

    await bot.handle_update(update)

    # Verify emoji reaction on incoming message
    bot.set_message_reaction.assert_awaited_with(12345, 77, "⚡")

    # Verify 2 separate tasks were created with user_note preserved in fragment
    conn = get_db_connection()
    tasks = conn.execute("SELECT url, chat_id, message_id FROM ingest_tasks WHERE chat_id = 12345").fetchall()
    conn.close()

    assert len(tasks) == 2
    urls = [t["url"] for t in tasks]
    assert any("https://github.com/astral-sh/uv#note=" in u for u in urls)
    assert any("https://github.com/fastfetch-cli/fastfetch#note=" in u for u in urls)
    assert all(t["message_id"] == 999 for t in tasks)


def test_card_html_renders_user_note():
    bot = TelegramBot(token="123456:dummy-token-for-test")
    item = {
        "title_l1": "測試情報",
        "category_name": "工具",
        "source_type": "GITHUB",
        "author": "astral-sh",
        "summary_l1": "超快速的 Python 套件管理器。",
        "content_raw": "## 使用者隨手筆記/備忘\n這工具用 Rust 寫的極快\n\n# uv\nreadme...",
        "tech_tags": ["Python", "Rust"],
    }
    html_card = bot.build_item_card_html(item)
    assert "💡 <b>個人備忘</b>：<i>這工具用 Rust 寫的極快</i>" in html_card
    assert "<b>測試情報</b>" in html_card


def test_accordion_keyboard_toggle():
    bot = TelegramBot(token="123456:dummy-token-for-test")
    item = {
        "id": "item-accordion-test",
        "url": "https://example.com/test",
        "is_starred": 0,
        "is_read": 0,
    }
    summary_kb = bot.build_item_keyboard(item, mode="summary")
    assert summary_kb["inline_keyboard"][0][0]["text"] == "深入剖析 ▾"
    assert summary_kb["inline_keyboard"][0][0]["callback_data"] == "detail:item-accordion-test"

    detail_kb = bot.build_item_keyboard(item, mode="detail")
    assert detail_kb["inline_keyboard"][0][0]["text"] == "▴ 收合摘要"
    assert detail_kb["inline_keyboard"][0][0]["callback_data"] == "collapse:item-accordion-test"


@pytest.mark.asyncio
async def test_accordion_detail_and_collapse_callbacks():
    bot = TelegramBot(token="123456:dummy-token-for-test")
    bot.is_authorized = MagicMock(return_value=True)
    bot.answer_callback_query = AsyncMock()
    bot.edit_message_text = AsyncMock(return_value={"ok": True})
    bot.send_api = AsyncMock(return_value={"ok": True})

    item_id = save_item({
        "url": "https://example.com/accordion",
        "source_type": "web",
        "category_name": "Inbox",
        "title_l1": "架構測試",
        "summary_l1": "簡介",
        "deep_analysis": "### 模組規格\n- 核心演算法: Raft",
    })

    # 1. Expand to detail
    query_detail = {
        "id": "q1",
        "from": {"id": 9999},
        "data": f"detail:{item_id}",
        "message": {"chat": {"id": 111}, "message_id": 222},
    }
    await bot.handle_callback(query_detail)
    assert bot.send_api.called
    call_args = bot.send_api.call_args[0]
    assert call_args[0] == "editMessageText"
    assert "架構測試" in call_args[1]["text"]
    assert "架構深析" in call_args[1]["text"]
    assert "▴ 收合摘要" in call_args[1]["reply_markup"]["inline_keyboard"][0][0]["text"]

    # 2. Collapse back to summary
    query_collapse = {
        "id": "q2",
        "from": {"id": 9999},
        "data": f"collapse:{item_id}",
        "message": {"chat": {"id": 111}, "message_id": 222},
    }
    await bot.handle_callback(query_collapse)
    assert bot.edit_message_text.called
    collapse_args = bot.edit_message_text.call_args[0]
    assert "<blockquote>簡介</blockquote>" in collapse_args[2]
    assert "深入剖析 ▾" in bot.edit_message_text.call_args.kwargs["reply_markup"]["inline_keyboard"][0][0]["text"]


@pytest.mark.asyncio
async def test_failure_keyboard_and_retry_callback():
    bot = TelegramBot(token="123456:dummy-token-for-test")
    bot.is_authorized = MagicMock(return_value=True)
    bot.answer_callback_query = AsyncMock()
    bot.edit_message_text = AsyncMock(return_value={"ok": True})
    bot.set_message_reaction = AsyncMock(return_value=True)

    task = create_ingest_task(url="https://example.com/fail-retry", source="telegram", chat_id=123, message_id=456)
    task_id = task["id"]
    from app.database import update_task_status
    update_task_status(task_id, status="failed", error_message="連接超時")

    query_retry = {
        "id": "q_retry",
        "from": {"id": 123},
        "data": f"retry_task:{task_id}",
        "message": {"chat": {"id": 123}, "message_id": 456},
    }
    await bot.handle_callback(query_retry)

    t_after = get_ingest_task(task_id)
    assert t_after["status"] == "queued"
    assert t_after["retry_count"] == 0
    assert t_after["error_message"] is None
    bot.answer_callback_query.assert_awaited_with("q_retry", "已排入重試佇列")


@pytest.mark.asyncio
async def test_delete_message_callback():
    bot = TelegramBot(token="123456:dummy-token-for-test")
    bot.is_authorized = MagicMock(return_value=True)
    bot.answer_callback_query = AsyncMock()
    bot.delete_message = AsyncMock(return_value=True)

    query_del = {
        "id": "q_del",
        "from": {"id": 123},
        "data": "delete_msg:789",
        "message": {"chat": {"id": 123}, "message_id": 789},
    }
    await bot.handle_callback(query_del)
    bot.delete_message.assert_awaited_with(123, 789)
    bot.answer_callback_query.assert_awaited_with("q_del", "已清除訊息")


def test_card_html_renders_all_eight_open_source_projects():
    bot = TelegramBot(token="123456:dummy-token-for-test")
    item = {
        "id": "multi-tool-item",
        "title_l1": "8 個開源 Skill 矩陣",
        "category_name": "工具",
        "source_type": "WEB",
        "summary_l1": "整合多個開源工具的全鏈路工作流。",
        "tech_tags": ["AI", "Skills"],
    }
    eight_tools = [
        {"target_canonical_url": f"https://github.com/org/repo{i}", "target_name": f"tool-{i}", "mention_context": f"說明文字 {i}"}
        for i in range(1, 9)
    ]
    with patch("app.bot.telegram_bot.get_sub_entities_for_parent", return_value=eight_tools):
        card = bot.build_item_card_html(item)
        assert "📦 <b>提及開源專案 (8)</b>" in card
        for i in range(1, 9):
            assert f"tool-{i}" in card

        # Test keyboard generates 2x2 buttons
        kb = bot.build_item_keyboard(item)
        inline_kb = kb["inline_keyboard"]
        tool_btn_rows = [row for row in inline_kb if any("📦" in btn["text"] for btn in row)]
        assert len(tool_btn_rows) == 2
        assert len(tool_btn_rows[0]) == 2
        assert len(tool_btn_rows[1]) == 2


def test_card_html_renders_overflow_indicator_when_over_eight():
    bot = TelegramBot(token="123456:dummy-token-for-test")
    item = {
        "id": "overflow-item",
        "title_l1": "超量開源專案測試",
        "category_name": "工具",
        "source_type": "WEB",
        "summary_l1": "超量工具彙整測試。",
        "tech_tags": ["AI"],
    }
    ten_tools = [
        {"target_canonical_url": f"https://github.com/org/repo{i}", "target_name": f"tool-{i}", "mention_context": f"說明 {i}"}
        for i in range(1, 11)
    ]
    with patch("app.bot.telegram_bot.get_sub_entities_for_parent", return_value=ten_tools):
        card = bot.build_item_card_html(item)
        assert "📦 <b>提及開源專案 (10)</b>" in card
        assert "...以及另外 2 個專案（可點擊「深入剖析」查看全貌）" in card

