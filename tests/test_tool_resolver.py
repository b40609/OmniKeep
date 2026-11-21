import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.research.tool_resolver import (
    search_github_repositories,
    judge_best_matching_repo,
    extract_tool_query_from_content,
    resolve_mentioned_tools
)
from app.bot.telegram_bot import TelegramBot


@pytest.mark.asyncio
async def test_search_github_repositories_success():
    fake_items = [
        {
            "full_name": "owner/repo1",
            "name": "repo1",
            "html_url": "https://github.com/owner/repo1",
            "description": "Awesome tool for developers",
            "stargazers_count": 1250,
            "language": "Python",
            "topics": ["ai", "tools"]
        }
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": fake_items}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.research.tool_resolver.public_http_client", return_value=mock_client):
        candidates = await search_github_repositories("repo1", limit=3)
        assert len(candidates) == 1
        assert candidates[0]["full_name"] == "owner/repo1"
        assert candidates[0]["stars"] == 1250
        assert candidates[0]["html_url"] == "https://github.com/owner/repo1"


@pytest.mark.asyncio
async def test_search_github_repositories_rate_limit_and_error():
    mock_resp = MagicMock()
    mock_resp.status_code = 403

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.research.tool_resolver.public_http_client", return_value=mock_client):
        candidates = await search_github_repositories("test_query")
        assert candidates == []

    # Network exception fallback
    mock_client.get.side_effect = Exception("Connection timeout")
    with patch("app.research.tool_resolver.public_http_client", return_value=mock_client):
        candidates = await search_github_repositories("test_query")
        assert candidates == []


@pytest.mark.asyncio
async def test_judge_best_matching_repo_exact_fast_path():
    candidates = [
        {
            "full_name": "pkause/impeccable",
            "name": "impeccable",
            "html_url": "https://github.com/pkause/impeccable",
            "description": "Design language for AI harness",
            "stars": 85000,
            "language": "TypeScript",
            "topics": ["ai", "design"]
        }
    ]
    judge = await judge_best_matching_repo("impeccable", "讓 AI 更懂設計的 harness 語言", candidates)
    assert judge["matched"] is not None
    assert judge["confidence"] >= 0.7
    assert judge["matched"]["html_url"] == "https://github.com/pkause/impeccable"


@pytest.mark.asyncio
async def test_judge_best_matching_repo_llm_multiple_choice():
    candidates = [
        {
            "full_name": "user/other-tool",
            "name": "other-tool",
            "html_url": "https://github.com/user/other-tool",
            "description": "A different utility",
            "stars": 10,
            "topics": []
        },
        {
            "full_name": "buer/cartographer",
            "name": "cartographer",
            "html_url": "https://github.com/buer/cartographer",
            "description": "Turn your codebase into a visual map in one command",
            "stars": 1500,
            "topics": ["visualization"]
        }
    ]

    mock_provider = AsyncMock()
    mock_provider.generate_json.return_value = {
        "matched_index": 2,
        "confidence": 0.92,
        "reason": "功能描述'將專案變地圖'與第二個候選專案高度吻合"
    }

    judge = await judge_best_matching_repo("專案地圖工具", "一行指令把專案變地圖", candidates, provider=mock_provider)
    assert judge["matched"] is not None
    assert judge["matched"]["full_name"] == "buer/cartographer"
    assert judge["confidence"] == 0.92


@pytest.mark.asyncio
async def test_resolve_mentioned_tools_enrichment():
    ai_result = {
        "sub_entities": [
            {
                "name": "cartographer",
                "canonical_url": "",
                "reason": "可視化專案地圖"
            }
        ]
    }

    fake_candidates = [
        {
            "full_name": "buer/cartographer",
            "name": "cartographer",
            "html_url": "https://github.com/buer/cartographer",
            "description": "Turn your repo into a map",
            "stars": 2000,
            "topics": ["map"]
        }
    ]

    with patch("app.research.tool_resolver.search_github_repositories", return_value=fake_candidates):
        resolved = await resolve_mentioned_tools("貼文介紹 cartographer 工具", "標題", ai_result)
        assert len(resolved) == 1
        assert resolved[0]["canonical_url"] == "https://github.com/buer/cartographer"
        assert resolved[0]["status"] == "verified"
        assert resolved[0]["stars"] == 2000


@pytest.mark.asyncio
async def test_telegram_card_with_sub_entities():
    bot = TelegramBot(token="123456:dummy_token")
    item = {
        "id": "item_123",
        "title_l1": "AI 設計利器 impeccable",
        "category_name": "AI",
        "source_type": "THREADS",
        "author": "TechReviewer",
        "summary_l1": "一套為 AI harness 打造的設計語言規範。",
        "tech_tags": ["Design", "AI", "Frontend"],
        "url": "https://threads.net/p/xyz"
    }

    fake_sub_entities = [
        {
            "target_canonical_url": "https://github.com/pkause/impeccable",
            "target_name": "impeccable",
            "mention_context": "設計語言規範 (★85k)"
        },
        {
            "target_canonical_url": "https://github.com/candidate/repo",
            "target_name": "similar-tool",
            "mention_context": "[疑似候選] 相似設計工具"
        }
    ]

    with patch("app.bot.telegram_bot.get_sub_entities_for_parent", return_value=fake_sub_entities):
        card = bot.build_item_card_html(item)
        assert "提及開源專案" in card
        assert "impeccable" in card
        assert "https://github.com/pkause/impeccable" in card
        assert "疑似提及專案（未確認）" in card
        assert "similar-tool" in card

        kb = bot.build_item_keyboard(item)
        inline_kb = kb["inline_keyboard"]
        # Button row containing direct link to repository
        flattened_texts = [btn["text"] for row in inline_kb for btn in row]
        assert any("📦 impeccable" in t for t in flattened_texts)


@pytest.mark.asyncio
async def test_search_github_repositories_cache_hit():
    from app.research.tool_resolver import _GITHUB_SEARCH_CACHE
    _GITHUB_SEARCH_CACHE.clear()

    fake_items = [{"full_name": "cached/repo", "name": "repo", "html_url": "https://github.com/cached/repo", "stars": 100, "topics": []}]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"items": fake_items}

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    with patch("app.research.tool_resolver.public_http_client", return_value=mock_client):
        # 第一次查詢，走 HTTP
        first = await search_github_repositories("cache_test", limit=3)
        assert len(first) == 1
        assert mock_client.get.call_count == 1

        # 第二次查詢，命中快取，不應再次呼叫 HTTP client
        second = await search_github_repositories("cache_test", limit=3)
        assert len(second) == 1
        assert second[0]["full_name"] == "cached/repo"
        assert mock_client.get.call_count == 1


@pytest.mark.asyncio
async def test_same_name_different_domain_lean_not_linked_to_quantconnect():
    """Same repo name ('Lean') in an unrelated domain (trading vs theorem proving) must not fast-path."""
    quantconnect_lean = {
        "full_name": "QuantConnect/Lean",
        "name": "Lean",
        "html_url": "https://github.com/QuantConnect/Lean",
        "description": "Lean Algorithmic Trading Engine by QuantConnect (Python, C#)",
        "stars": 22633,
        "language": "C#",
        "topics": ["algorithmic-trading", "finance", "quantconnect", "trading"]
    }
    lean4 = {
        "full_name": "leanprover/lean4",
        "name": "lean4",
        "html_url": "https://github.com/leanprover/lean4",
        "description": "Lean 4 programming language and theorem prover",
        "stars": 10095,
        "language": "Lean",
        "topics": ["lean", "theorem-prover", "formal-verification"]
    }

    # 1. Without LLM judge, QuantConnect/Lean must NOT match theorem-proving context
    judge_no_llm = await judge_best_matching_repo(
        "Lean",
        "證明自己寫的捲動清單元件不會閃、不會抖",
        [quantconnect_lean]
    )
    assert judge_no_llm["matched"] is None
    assert judge_no_llm["confidence"] < 0.4

    # 2. With LLM judge, fast-path must not hijack QuantConnect/Lean; judge picks leanprover/lean4
    mock_provider = AsyncMock()
    mock_provider.generate_json.return_value = {
        "matched_index": 2,
        "confidence": 0.94,
        "reason": "演講提及用於證明元件正確性，對應定理證明器 leanprover/lean4，而非 QuantConnect/Lean 交易引擎"
    }
    judge_with_llm = await judge_best_matching_repo(
        "Lean",
        "證明自己寫的捲動清單元件不會閃、不會抖",
        [quantconnect_lean, lean4],
        provider=mock_provider
    )
    assert mock_provider.generate_json.called
    assert judge_with_llm["matched"]["full_name"] == "leanprover/lean4"


@pytest.mark.asyncio
async def test_resolve_mentioned_tools_marks_mismatched_domain_unverified_without_url():
    """When only an unrelated-domain repo exists, resolve_mentioned_tools gives no link and marks 待確認."""
    ai_result = {
        "sub_entities": [
            {
                "name": "Lean",
                "canonical_url": "",
                "reason": "用 Lean 證明捲動清單元件不閃不抖"
            }
        ]
    }
    quantconnect_only = [
        {
            "full_name": "QuantConnect/Lean",
            "name": "Lean",
            "html_url": "https://github.com/QuantConnect/Lean",
            "description": "Lean Algorithmic Trading Engine by QuantConnect (Python, C#)",
            "stars": 22633,
            "language": "C#",
            "topics": ["algorithmic-trading", "finance", "trading"]
        }
    ]
    mock_provider = AsyncMock()
    mock_provider.generate_json.return_value = {
        "matched_index": None,
        "confidence": 0.1,
        "reason": "QuantConnect/Lean 屬於量化交易領域，與演講提及的定理證明不符"
    }

    with patch("app.research.tool_resolver.search_github_repositories", return_value=quantconnect_only):
        resolved = await resolve_mentioned_tools(
            "演講提到用 Lean 證明捲動清單元件不閃不抖",
            "AI 照抄你的程式碼，糾正要寫成自動檢查",
            ai_result,
            provider=mock_provider
        )
        assert len(resolved) == 1
        assert resolved[0]["canonical_url"] == ""
        assert resolved[0]["status"] == "unverified"
        assert "[待確認]" in resolved[0]["reason"]


@pytest.mark.asyncio
async def test_telegram_detail_count_matches_listed_open_source_projects():
    """Detail view must not count [庫內重複] or [待確認] items inside 提及開源專案清單 (N)."""
    from app.database import save_item, save_citation

    bot = TelegramBot(token="123456:dummy-token")
    bot.is_authorized = MagicMock(return_value=True)
    bot.answer_callback_query = AsyncMock()
    bot.send_api = AsyncMock(return_value={"ok": True})

    item_id = save_item({
        "url": "https://youtu.be/test_lean_count",
        "source_type": "youtube",
        "category_name": "AI",
        "title_l1": "AI 照抄你的程式碼，糾正要寫成自動檢查",
        "summary_l1": "把糾正寫成自動檢查",
        "deep_analysis": "## 最重要的 3 件事\n- 用自動檢查擋錯",
    })
    save_citation({
        "source_parent_id": item_id,
        "target_canonical_url": "https://github.com/tlaplus/tlaplus",
        "target_name": "📦 tlaplus/tlaplus",
        "mention_context": "驗證跨裝置通知同步順序",
    })
    save_citation({
        "source_parent_id": item_id,
        "target_canonical_url": "https://github.com/leanprover/lean4",
        "target_name": "📦 leanprover/lean4",
        "mention_context": "證明捲動清單元件不閃不抖",
    })
    # Two unlinked [待確認] mentions must not overwrite each other in DB
    save_citation({
        "source_parent_id": item_id,
        "target_canonical_url": "",
        "target_name": "pstack",
        "mention_context": "[待確認] Cursor 外掛",
    })
    save_citation({
        "source_parent_id": item_id,
        "target_canonical_url": "",
        "target_name": "bombadil",
        "mention_context": "[待確認] UI 測試工具",
    })
    # Duplicate item in library must go to 庫內競品與關聯提醒, not inflate 開源專案清單 count
    save_citation({
        "source_parent_id": item_id,
        "target_canonical_url": "https://www.youtube.com/watch?v=dup123",
        "target_name": "AI 寫的垃圾來自環境",
        "mention_context": "[庫內重複] 同一演講另一支整理影片",
    })

    await bot.handle_callback({
        "id": "q_detail",
        "from": {"id": 9999},
        "data": f"detail:{item_id}",
        "message": {"chat": {"id": 111}, "message_id": 222},
    })

    sent_text = bot.send_api.call_args[0][1]["text"]
    assert "📦 <b>提及開源專案清單 (2)</b>" in sent_text
    assert "🔍 <b>疑似提及專案（未確認 (2)）</b>" in sent_text
    assert "<b>pstack</b>" in sent_text
    assert "<b>bombadil</b>" in sent_text
    assert "⚖️ <b>庫內競品與關聯提醒</b>" in sent_text
    assert "重複收錄" in sent_text


