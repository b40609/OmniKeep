"""
OmniKeep Model Context Protocol (MCP) Server
Allows external AI Agents (ChatGPT App, Claude, Cursor, Antigravity) to query,
retrieve, synthesize, and write back engineering intelligence into OmniKeep's Second Brain.
"""

import sys
import json
import uuid
import argparse
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP

from app.database import (
    get_items,
    get_item_by_id,
    save_item,
    save_citation,
    update_item_field,
    get_status_counts,
    get_all_categories,
    get_db_connection
)
from app.pipeline import run_pipeline
from app.providers import get_primary_provider

# Initialize FastMCP Server
mcp = FastMCP(
    "OmniKeep",
    dependencies=["pydantic", "sqlite3"]
)

# ── 1. Search Tool (Lean & Fast) ────────────────────────────────

@mcp.tool()
async def search_brain(
    query: str,
    category: Optional[str] = None,
    limit: int = 5,
    is_starred: Optional[bool] = None
) -> str:
    """
    Search your Second Brain using SQLite FTS5 unicode61 full-text search.
    Returns lean, token-efficient summary cards (Title, Tags, Plain Core) to avoid bloating Agent context.
    For deep architectural breakdown, follow up with get_item_architecture(item_id).
    """
    items = get_items(
        query=query,
        category=category,
        is_starred=is_starred,
        limit=min(limit, 20)
    )
    if not items:
        return f"在 OmniKeep 大腦中未找到與「{query}」相關的情報項目。"

    results = []
    for item in items:
        status = "已讀" if item.get("is_read") else "待讀"
        star = " [⭐]" if item.get("is_starred") else ""
        tags = ", ".join(item.get("tech_tags", []))
        
        results.append(
            f"### [{item.get('id')}] {item.get('title_l1')}{star}\n"
            f"- **分類/狀態**: {item.get('category_name')} ({status})\n"
            f"- **技術標籤**: #{tags}\n"
            f"- **白話核心**: {item.get('summary_l1')}"
        )

    output = f"找到 {len(results)} 筆相關情報：\n\n" + "\n\n".join(results)
    output += "\n\n---\n💡 提示：使用 `get_item_architecture(item_id)` 取得 L2 架構規格；使用 `writeback_insight(...)` 可將對話結論寫回大腦。"
    return output


# ── 2. Get Architecture Breakdown Tool (Token Optimized) ───────

@mcp.tool()
async def get_item_architecture(item_id: str) -> str:
    """
    Retrieve high-density L1 takeaway and L2 deep architectural breakdown for an item.
    Excludes verbose raw page snapshots to conserve context tokens for deep technical discussion.
    """
    item = get_item_by_id(item_id)
    if not item:
        return f"錯誤：找不到 ID 為「{item_id}」的情報項目。"

    tags = ", ".join(item.get("tech_tags", []))
    status = "已封存" if item.get("is_read") else "待讀 (Inbox)"
    star = "⭐ 已星標" if item.get("is_starred") else "未星標"

    output = [
        f"# {item.get('title_l1')}",
        f"- **ID**: {item.get('id')} | **分類**: {item.get('category_name')} ({status}, {star})",
        f"- **原始連結**: {item.get('url')}",
        f"- **技術標籤**: #{tags}\n",
        "## ⚡ L1 白話核心痛點與價值",
        item.get("summary_l1", ""),
        "\n## 📊 L2 深度技術架構與規格解構",
        item.get("deep_analysis", "無深入分析內容。"),
    ]
    return "\n".join(output)


# ── 3. Get Raw Content Snapshot Tool ────────────────────────────

@mcp.tool()
async def get_item_raw(item_id: str, max_chars: int = 2500) -> str:
    """
    Retrieve the raw text or source code snapshot of an item.
    Only call this when you need exact code snippets, implementation details, or verbatim quotes.
    """
    item = get_item_by_id(item_id)
    if not item:
        return f"錯誤：找不到 ID 為「{item_id}」的情報項目。"

    raw = item.get("content_raw", "")
    if not raw:
        return f"項目 [{item_id}] 沒有原始內容快照。"

    preview = raw[:max_chars]
    if len(raw) > max_chars:
        preview += f"\n...(原文超過 {max_chars} 字已截斷)..."

    return f"# [{item_id}] 原文節錄快照 ({item.get('title_l1')})\n\n{preview}"


# ── 4. Backward-Compatible Full Detail Tool ─────────────────────

@mcp.tool()
async def get_item_detail(item_id: str, include_raw: bool = False) -> str:
    """
    Retrieve item details. By default excludes raw snapshots to prevent context explosion.
    Set include_raw=True if raw text is explicitly required.
    """
    base = await get_item_architecture(item_id)
    if not include_raw or "錯誤：" in base:
        return base

    item = get_item_by_id(item_id)
    raw = item.get("content_raw", "") if item else ""
    if raw:
        preview = raw[:2000] + ("\n...(原文已截斷)..." if len(raw) > 2000 else "")
        return base + f"\n\n## 📖 原文節錄快照\n{preview}"
    return base


# ── 5. Write Back Insight Tool (Agent Memory Loop) ──────────────

@mcp.tool()
async def writeback_insight(
    title: str,
    summary: str,
    architecture_details: str,
    category: Optional[str] = "Insight",
    tech_tags: Optional[List[str]] = None,
    related_item_id: Optional[str] = None
) -> str:
    """
    Write back architectural decisions, syntheses, or technical conclusions discussed with the Agent into OmniKeep.
    Creates a new first-class item in the Second Brain with source_type='insight'.
    If related_item_id is provided, automatically establishes a citation link to the referenced project.

    Idempotency: insights carry synthetic URLs (omnikeep://insight/<uuid>), so
    the URL cache can't dedupe them. Same title within the last 7 days updates
    the existing item instead of piling up duplicates (agents retry, humans
    re-run the same conversation — neither should spam the archive).
    """
    title = title.strip()[:60]

    existing = None
    try:
        conn = get_db_connection()
        row = conn.execute(
            """SELECT id, updated_at FROM items
               WHERE source_type = 'insight' AND title_l1 = ?
               AND julianday(updated_at) > julianday('now', '-7 days')
               ORDER BY updated_at DESC LIMIT 1""",
            (title,),
        ).fetchone()
        conn.close()
        existing = row["id"] if row else None
    except Exception:
        existing = None

    tags = list(tech_tags) if tech_tags else ["AgentInsight"]
    if "AgentInsight" not in tags:
        tags.append("AgentInsight")

    if existing:
        update_item_field(existing, {
            "summary_l1": summary.strip(),
            "deep_analysis": architecture_details.strip(),
            "content_raw": f"# {title}\n\n{summary}\n\n{architecture_details}",
            "tech_tags": json.dumps(tags, ensure_ascii=False),
        })
        saved_id = existing
        mode = "🔄 已更新既有的同名 Insight（7 天內冪等去重），未產生重複項目"
    else:
        item_id = f"ins_{uuid.uuid4().hex[:10]}"
        item_data = {
            "id": item_id,
            "url": f"omnikeep://insight/{item_id}",
            "source_type": "insight",
            "category_name": category or "Insight",
            "title_l1": title,
            "summary_l1": summary.strip(),
            "tech_tags": tags,
            "deep_analysis": architecture_details.strip(),
            "content_raw": f"# {title}\n\n{summary}\n\n{architecture_details}",
            "author": "AI Assistant (Remote MCP)",
            "is_starred": 1,  # Agent 提煉的成果預設星標
            "is_read": 0
        }
        saved_id = save_item(item_data)
        mode = "✅ 成功將技術決策回寫至 OmniKeep 第二大腦！"

    try:
        if not existing:
            saved_id = save_item(item_data)
        cit_msg = ""
        if related_item_id:
            parent_item = get_item_by_id(related_item_id)
            if parent_item:
                save_citation({
                    "source_parent_id": related_item_id,
                    "target_item_id": saved_id,
                    "target_canonical_url": f"omnikeep://insight/{saved_id}",
                    "target_name": title,
                    "mention_context": "Agent 深度探討與架構決策成果"
                })
                cit_msg = f"\n- **關聯專案**: [{related_item_id}] {parent_item.get('title_l1')}"

        return (
            f"{mode}\n"
            f"- **ID**: {saved_id}\n"
            f"- **標題**: {title}\n"
            f"- **分類**: {category}\n"
            f"- **標籤**: #{', #'.join(tags)}{cit_msg}"
        )
    except Exception as e:
        return f"❌ 回寫失敗：{str(e)}"


# ── 6. Ingest URL / Note Tool ───────────────────────────────────

@mcp.tool()
async def save_to_brain(
    content_or_url: str,
    category: Optional[str] = None
) -> str:
    """
    Ingest a new item into OmniKeep Second Brain.
    Accepts:
    1. A web/YouTube/Reel URL (e.g. 'https://github.com/...')
    2. A technical text snippet, note, markdown summary, or code discussion.
    The item will be automatically parsed, tagged, and structured into L1/L2 format.
    """
    clean_input = content_or_url.strip()
    if not clean_input:
        return "錯誤：內容不能為空。"

    try:
        item = await run_pipeline(clean_input, manual_category=category, origin="agent")
        tags = ", ".join(item.get("tech_tags", []))
        return (
            f"✅ 成功存入 OmniKeep 第二大腦！\n"
            f"- **ID**: {item.get('id')}\n"
            f"- **標題**: {item.get('title_l1')}\n"
            f"- **自動分類**: {item.get('category_name')}\n"
            f"- **技術標籤**: #{tags}\n"
            f"- **白話重點**: {item.get('summary_l1')}\n"
            f"- **詳情可透過 get_item_architecture('{item.get('id')}') 查看**"
        )
    except Exception as e:
        return f"❌ 存入失敗：{str(e)}"


# ── 7. List Recent Items Tool ───────────────────────────────────

@mcp.tool()
async def list_recent_items(
    triage_status: str = "inbox",
    category: Optional[str] = None,
    limit: int = 5
) -> str:
    """
    List recent items from OmniKeep.
    triage_status options:
    - 'inbox': unread/unprocessed items waiting for triage
    - 'starred': favorite/starred items
    - 'archived': processed/read items
    - 'all': all items regardless of status
    """
    is_read = None
    is_starred = None

    status_lower = triage_status.lower()
    if status_lower == "inbox":
        is_read = False
    elif status_lower == "archived":
        is_read = True
    elif status_lower == "starred":
        is_starred = True

    items = get_items(
        category=category,
        is_read=is_read,
        is_starred=is_starred,
        limit=min(limit, 30)
    )

    if not items:
        return f"在「{triage_status}」狀態下沒有找到任何情報項目。"

    lines = [f"### OmniKeep 最近情報清單 ({triage_status})："]
    for i, item in enumerate(items, 1):
        star = " ⭐" if item.get("is_starred") else ""
        tags = " ".join([f"#{t}" for t in item.get("tech_tags", [])[:3]])
        lines.append(
            f"{i}. [{item.get('id')}] **{item.get('title_l1')}**{star}\n"
            f"   分類: {item.get('category_name')} | {tags}\n"
            f"   重點: {item.get('summary_l1')[:80]}..."
        )
    return "\n".join(lines)


# ── 8. Update Status Tool ───────────────────────────────────────

@mcp.tool()
async def update_item_status(
    item_id: str,
    is_read: Optional[bool] = None,
    is_starred: Optional[bool] = None
) -> str:
    """
    Update triage status of an item in OmniKeep (mark read/archived, or star).
    """
    updates: Dict[str, Any] = {}
    if is_read is not None:
        updates["is_read"] = 1 if is_read else 0
    if is_starred is not None:
        updates["is_starred"] = 1 if is_starred else 0

    if not updates:
        return "未提供要更新的狀態欄位 (is_read 或 is_starred)。"

    ok = update_item_field(item_id, updates)
    if not ok:
        return f"錯誤：找不到 ID 為「{item_id}」的項目。"

    status_str = []
    if is_read is not None:
        status_str.append("已封存" if is_read else "設為待讀 Inbox")
    if is_starred is not None:
        status_str.append("已加星標" if is_starred else "已取消星標")

    return f"✅ 項目 [{item_id}] 狀態已更新為：{', '.join(status_str)}"


# ── 9. Ask Brain Synthesis Tool (Cross-Article Report) ───────────

@mcp.tool()
async def ask_brain_synthesis(topic: str, top_k: int = 5) -> str:
    """
    Cross-reference multiple items in your brain related to a topic and generate
    a synthesized architectural comparison using AGNES 3.0's massive context window.
    """
    items = get_items(query=topic, limit=min(top_k, 10))
    if not items:
        return f"大腦中無與「{topic}」相關的庫存項目，無法生成跨篇綜述。"

    context_blocks = []
    for item in items:
        context_blocks.append(
            f"=== 專案/文章: {item.get('title_l1')} (ID: {item.get('id')}) ===\n"
            f"連結: {item.get('url')}\n"
            f"標籤: {', '.join(item.get('tech_tags', []))}\n"
            f"白話重點: {item.get('summary_l1')}\n"
            f"L2 架構解構:\n{item.get('deep_analysis')}\n"
            f"=== 項目結束 ===\n"
        )

    full_context = "\n".join(context_blocks)
    primary = get_primary_provider()

    system_prompt = (
        "你是一位頂尖的資深系統架構師與技術情報分析官。"
        "請根據使用者大腦庫存中的多篇技術情報，進行跨篇橫向技術綜述與架構對比。"
        "嚴格使用繁體中文（台灣習慣用語），以高密度工程乾貨格式呈現，條列共通點、架構差異、落地建議與注意事項。"
    )

    prompt = (
        f"分析主題：{topic}\n\n"
        f"以下是使用者 OmniKeep 第二大腦庫存中與此主題相關的 {len(items)} 篇完整架構剖析：\n\n"
        f"{full_context}\n\n"
        f"請針對「{topic}」提供一份結構化的跨篇技術情報綜述與架構選型對比報告。"
    )

    try:
        report = await primary.generate_text(prompt, system_prompt=system_prompt)
        return f"## 🧠 OmniKeep 第二大腦跨篇情報綜述：{topic}\n\n{report}"
    except Exception as e:
        return f"跨篇合成失敗：{str(e)}"


# ── 10. Watch & Proposal Tools (Local Proposal Engine) ──────────

@mcp.tool()
async def list_proposals(status: str = "pending", limit: int = 10) -> str:
    """List OmniKeep proposal cards (default: pending ones).

    Each proposal is a glass-box suggestion for the user's own machine — e.g. a
    risk finding from the desktop L0 scan, or an improvement idea for a watched
    project (CatOS). Returns verdict sentence + scores (impact/confidence/effort)
    + item_id so the card body can be fetched with get_item_architecture.
    """
    from app.database import get_proposals
    rows = get_proposals(status=status, limit=limit)
    if not rows:
        return f"沒有狀態為 {status} 的提案。"
    out = []
    for p in rows:
        item = get_item_by_id(p["item_id"]) or {}
        out.append(
            f"- [{p['proposal_type']}] {item.get('title_l1', '(無標題)')}\n"
            f"  分數: 影響{p['impact']}/信心{p['confidence']}/成本{p['effort']} · "
            f"狀態:{p['status']} · id:{p['id']} · item:{p['item_id']}\n"
            f"  {item.get('summary_l1', '')}"
        )
    return "\n".join(out)

@mcp.tool()
async def decide_proposal(
    proposal_id: str,
    approve: bool,
    user_impact: Optional[float] = None,
    user_confidence: Optional[float] = None,
    user_effort: Optional[float] = None,
    reason: str = "",
) -> str:
    """Approve or dismiss a proposal; optionally correct any score dimension (0-10).

    Corrections are stored as user ground-truth labels alongside the AI prior —
    they immediately re-rank the card and later train the local preference model.
    """
    from app.database import decide_proposal as db_decide
    corrections = {k: v for k, v in {
        "impact": user_impact, "confidence": user_confidence,
        "effort": user_effort}.items() if v is not None}
    result = db_decide(proposal_id, "approved" if approve else "dismissed",
                       corrections, reason)
    if not result:
        return f"找不到提案 {proposal_id}"
    return f"提案 {proposal_id} 已標為 {result['status']}。" + (
        f"（已記錄用戶修正：{corrections}）" if corrections else "")

@mcp.tool()
async def scan_watch_target(target_id: str = "") -> str:
    """Trigger a scan of watch targets (risk check + fingerprint refresh).

    Leave target_id empty to scan ALL active targets. Fingerprints honor each
    target's two permission axes; anything sent to the cloud LLM is
    secret-redacted first.
    """
    import asyncio
    from app.database import get_watch_targets
    from app.watch.scanner import scan_target
    targets = get_watch_targets(active_only=True)
    if target_id:
        targets = [t for t in targets if t["id"] == target_id]
    if not targets:
        return "沒有可掃描的監看目標（或 id 不符）。"
    results = await asyncio.gather(*(scan_target(t) for t in targets),
                                   return_exceptions=True)
    lines = []
    for t, r in zip(targets, results):
        if isinstance(r, Exception):
            lines.append(f"- {t['name']}: ❌ {r}")
        else:
            risk = "🚨 已產生風險提案" if r.get("risk_proposal") else "無新風險"
            fp = "指紋已更新" if r.get("fingerprint_updated") else "指紋未變"
            lines.append(f"- {t['name']}: {risk} · {fp} · {r.get('file_count', '?')} 檔")
    return "\n".join(lines)


# ── 11. Resources ───────────────────────────────────────────────

@mcp.resource("omnikeep://stats")
async def get_stats_resource() -> str:
    """Returns current real-time counts across Inbox, Starred, Archived, and Total."""
    stats = get_status_counts()
    return json.dumps(stats, ensure_ascii=False, indent=2)

@mcp.resource("omnikeep://categories")
async def get_categories_resource() -> str:
    """Returns all configured categories and item counts."""
    cats = get_all_categories()
    return json.dumps(cats, ensure_ascii=False, indent=2)


# ── CLI Entrypoint ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OmniKeep MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport mode")
    args = parser.parse_args()

    if args.transport == "sse":
        import uvicorn
        from app.config import settings
        uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT)
    else:
        mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
