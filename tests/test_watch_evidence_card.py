import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

from app.config import settings
from app.database import (
    save_item,
    get_item_by_id,
    add_watch_target,
    update_watch_target,
    get_proposal,
    decide_proposal,
)
from app.watch import relevance
from app.bot.telegram_bot import build_proposal_card_html


_TMP = Path(__file__).parent / ".tmp"


def _mk_item(tags=None, title=None, summary=None, origin="radar") -> str:
    seed = uuid.uuid4().hex[:8]
    return save_item({
        "url": f"https://evidence-fixture.invalid/{seed}",
        "source_type": "web",
        "category_name": "AI",
        "title_l1": title or f"情報 {seed}",
        "summary_l1": summary or "測試情報摘要",
        "tech_tags": tags or ["FastAPI", "AsyncIO"],
        "origin": origin,
    })


@pytest.mark.asyncio
async def test_relevance_cloud_module_evidence_card():
    # 1. Setup watched target and fingerprint
    fp_id = _mk_item(
        tags=["FastAPI", "Network", "Security"],
        title="OmniKeep 核心服務",
        summary="自託管情報雷達與本機提案引擎",
        origin="watch"
    )
    target = add_watch_target(
        "OmniKeep",
        str(_TMP.resolve()),
        "folder",
        "custom",
        read_scope={"filenames": True, "deps": True},
        outbound_consent={"summary": True, "deps": True}
    )
    update_watch_target(target["id"], {"fingerprint_item_id": fp_id})

    # 2. Setup incoming radar item
    radar_item_id = _mk_item(
        tags=["FastAPI", "Network", "SSRF"],
        title="Advanced HTTPX Transport Hardening against DNS Rebinding",
        summary="Detailed architecture on pinning resolved IP while preserving TLS SNI"
    )
    radar_item = get_item_by_id(radar_item_id)

    # 3. Mock cloud LLM response conforming to module-level evidence contract
    mock_llm_judgment = {
        "relevant": True,
        "proposal_type": "upgrade",
        "impact": 8.5,
        "confidence": 9.0,
        "effort": 2.5,
        "verdict": "升級網路層防 DNS rebinding 與固定 IP 直連",
        "target_module": "app/network.py",
        "external_evidence": "使用 httpcore 自訂 backend 連線已驗證數字 IP",
        "local_evidence": "既有 HTTPX 請求未鎖定解析後 IP，存在 rebinding 窗口",
        "prerequisites": "HTTPX 0.28+ 與 httpcore 相容",
        "action_plan": "在 app/network.py 注入 CheckedTransport 並保留 TLS hostname",
        "verification_plan": "執行 pytest test_audit_regressions.py 驗證 DNS rebinding 防護"
    }

    with patch("app.watch.relevance.get_primary_provider") as mock_prov:
        mock_provider_instance = AsyncMock()
        mock_provider_instance.generate_json.return_value = mock_llm_judgment
        mock_prov.return_value = mock_provider_instance

        proposal = await relevance.maybe_propose_for_item(radar_item)

    assert proposal is not None
    assert proposal["proposal_type"] == "upgrade"
    assert proposal["impact"] == 8.5
    assert proposal["confidence"] == 9.0
    assert proposal["effort"] == 2.5

    # 4. Verify card structure in items table
    card = get_item_by_id(proposal["item_id"])
    assert card is not None
    assert "app/network.py" in card["title_l1"]
    assert "升級網路層" in card["summary_l1"]
    assert "app/network.py" in card["summary_l1"]

    deep = card["deep_analysis"]
    assert "### 🎯 模組與結論" in deep
    assert "建議改動模組**：`app/network.py`" in deep
    assert "### 🔍 雙邊證據鏈" in deep
    assert "使用 httpcore 自訂 backend" in deep
    assert "既有 HTTPX 請求未鎖定解析後 IP" in deep
    assert "### 📋 落地前提與行動方案" in deep
    assert "在 app/network.py 注入 CheckedTransport" in deep
    assert "執行 pytest test_audit_regressions.py" in deep


@pytest.mark.asyncio
async def test_relevance_local_only_evidence_fallback():
    # Target without outbound consent
    fp_id = _mk_item(tags=["SQLite", "WAL"], origin="watch")
    target = add_watch_target(
        "LocalVault",
        str(_TMP.resolve()),
        "folder",
        "custom",
        read_scope={"filenames": True},
        outbound_consent={"summary": False}
    )
    update_watch_target(target["id"], {"fingerprint_item_id": fp_id})

    item_id = _mk_item(tags=["SQLite", "WAL", "Performance"])
    item = get_item_by_id(item_id)

    proposal = await relevance.maybe_propose_for_item(item)
    assert proposal is not None

    card = get_item_by_id(proposal["item_id"])
    assert "LocalVault" in card["title_l1"]
    assert "本地保守比對" in card["deep_analysis"]
    assert "未啟用雲端判斷" in card["deep_analysis"]


def test_telegram_proposal_card_evidence_rendering():
    prop = {
        "id": "p_ev_test_1",
        "impact": 8.0,
        "confidence": 8.5,
        "effort": 3.0,
        "title_l1": "🔗 提案：app/database.py ⟷ SQLite WAL Optimization",
        "summary_l1": "升級 WAL 檢查點與時間運算。模組：app/database.py｜依據：SQLite 官方建議",
        "deep_analysis": (
            "### 🎯 模組與結論\n"
            "- **建議改動模組**：`app/database.py`\n"
            "- **核心結論**：優化 WAL 檢查點頻率\n\n"
            "### 🔍 雙邊證據鏈\n"
            "- **外部情報依據**：SQLite 官方 WAL 診斷報告\n"
            "- **本機現狀依據**：現有定時每 5 分鐘主動 wal_checkpoint\n\n"
            "### 📋 落地前提與行動方案\n"
            "- **最小改動步驟**：改為 PASSIVE checkpoint 消除寫入鎖等待\n"
        )
    }

    card_html = build_proposal_card_html(prop)
    assert "🔭 <b>模組提案卡</b>" in card_html
    assert "<b>📋 模組與證據鏈：</b>" in card_html
    assert "建議改動模組：app/database.py" in card_html
    assert "外部情報依據：SQLite 官方 WAL 診斷報告" in card_html
    assert "本機現狀依據：現有定時每 5 分鐘主動 wal_checkpoint" in card_html
    assert "最小改動步驟：改為 PASSIVE checkpoint" in card_html
    assert "🎯 影響 8.0 · 🔍 信心 8.5 · 🏗️ 成本 3.0" in card_html


@pytest.mark.asyncio
async def test_watch_proposals_api_and_decision():
    from app.main import app

    # Create target + proposal
    fp_id = _mk_item(tags=["Python", "FastAPI"], origin="watch")
    target = add_watch_target("OmniTest", str(_TMP.resolve()), "folder", "balanced")
    update_watch_target(target["id"], {"fingerprint_item_id": fp_id})

    item_id = _mk_item(tags=["Python", "FastAPI"])
    item = get_item_by_id(item_id)
    proposal = await relevance.maybe_propose_for_item(item)
    assert proposal is not None

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        # 1. GET /api/watch/proposals should return deep_analysis
        res_list = await client.get("/api/watch/proposals")
        assert res_list.status_code == 200
        data = res_list.json()
        target_prop = next((p for p in data if p["id"] == proposal["id"]), None)
        assert target_prop is not None
        assert "deep_analysis" in target_prop
        assert "### 🎯 模組與結論" in target_prop["deep_analysis"]

        # 2. Decide proposal with score corrections and structured reason
        res_decide = await client.post(f"/api/watch/proposals/{proposal['id']}/decide", json={
            "status": "approved",
            "user_impact": 9.0,
            "user_confidence": 9.5,
            "user_effort": 2.0,
            "reason": "已驗證可行，排入下一輪敏捷迭代"
        })
        assert res_decide.status_code == 200
        decided = res_decide.json()
        assert decided["status"] == "approved"
        assert decided["user_impact"] == 9.0
        assert decided["correction_reason"] == "已驗證可行，排入下一輪敏捷迭代"
