import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app
from app.config import settings
from app.mcp_server import (
    search_brain,
    get_item_architecture,
    get_item_raw,
    get_item_detail,
    writeback_insight,
    update_item_status
)
from app.database import get_item_by_id

@pytest.mark.asyncio
async def test_mcp_auth_protection():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Unauthenticated request should be rejected
        res_no_auth = await client.get("/mcp/sse")
        assert res_no_auth.status_code == 401
        assert "Unauthorized" in res_no_auth.json().get("error", "")

        # 2. Invalid token should be rejected
        res_bad_auth = await client.get("/mcp/sse?token=wrong_key")
        assert res_bad_auth.status_code == 401

        # A finite mounted path proves accepted auth without hanging on SSE.
        headers = {"Authorization": f"Bearer {settings.API_KEY}"}
        valid = await client.get("/mcp/auth-probe-not-found", headers=headers)
        assert valid.status_code == 404
        query_token = await client.get("/mcp/auth-probe-not-found", params={"token": settings.API_KEY})
        assert query_token.status_code == 401

@pytest.mark.asyncio
async def test_writeback_insight_and_retrieval():
    # 1. Write back a simulated Agent architectural insight
    # Unique suffix per run: writeback_insight dedups same-title insights for
    # 7 days, so a fixed title would pass once then fail on every re-run.
    import uuid as _uuid
    title = f"CatOS Multi-Agent Concurrency Latch {_uuid.uuid4().hex[:6]}"
    summary = "Uses atomic CAS and latch state machine to prevent race conditions during OKX order routing."
    architecture_details = "### Architecture Details\n- Supervisor holds atomic latch\n- Worker sends signed intent via IPC\n- Rollback on failure."
    
    result = await writeback_insight(
        title=title,
        summary=summary,
        architecture_details=architecture_details,
        category="CatOS",
        tech_tags=["CatOS", "Concurrency", "Latch"]
    )
    assert "成功將技術決策回寫" in result
    assert "ID" in result

    # Extract ID
    import re
    m = re.search(r'\*\*ID\*\*:\s*([a-zA-Z0-9_]+)', result)
    assert m is not None
    item_id = m.group(1)

    # 2. Test search_brain finds it
    search_res = await search_brain(query="Concurrency Latch")
    assert item_id in search_res
    assert "CatOS Multi-Agent Concurrency Latch" in search_res
    assert "💡 提示：" in search_res

    # 3. Test get_item_architecture (lean, no raw preview explosion)
    arch_res = await get_item_architecture(item_id)
    assert "## ⚡ L1 白話核心痛點與價值" in arch_res
    assert "## 📊 L2 深度技術架構與規格解構" in arch_res
    assert "Supervisor holds atomic latch" in arch_res
    assert "原文節錄快照" not in arch_res

    # 4. Test get_item_raw
    raw_res = await get_item_raw(item_id)
    assert "原文節錄快照" in raw_res
    assert title in raw_res

    # 5. Test update_item_status
    upd_res = await update_item_status(item_id, is_read=True)
    assert "已封存" in upd_res

    db_item = get_item_by_id(item_id)
    assert db_item is not None
    assert db_item["is_read"] == 1
