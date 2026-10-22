"""
OmniKeep Model Context Protocol (MCP) Server
Allows external AI Agents (Claude Code, Cursor, Codex, Antigravity) to query,
retrieve, and store engineering intelligence into OmniKeep's Second Brain.
"""

import json
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP

from app.database import (
    get_items,
    get_item_by_id,
    update_item_field,
    get_status_counts,
    get_all_categories
)
from app.pipeline import run_pipeline
from app.providers import get_primary_provider

# Initialize FastMCP Server
mcp = FastMCP(
    "OmniKeep",
    dependencies=["pydantic", "sqlite3"]
)

# ── 1. Search Tool ──────────────────────────────────────────────

@mcp.tool()
async def search_brain(
    query: str,
    category: Optional[str] = None,
    limit: int = 10,
    is_starred: Optional[bool] = None
) -> str:
    """
    Search your Second Brain using SQLite FTS5 unicode61 full-text search.
    Searches across titles, plain takeaways, tech tags, deep analysis, and raw content.
    Returns structured summary cards for relevant technical intelligence items.
    """
    items = get_items(
        query=query,
        category=category,
        is_starred=is_starred,
        limit=min(limit, 50)
    )
    if not items:
        return f"在 OmniKeep 大腦中未找到與「{query}」相關的情報項目。"

    results = []
    for item in items:
        status = "已讀" if item.get("is_read") else "待讀"
        star = " [⭐已星標]" if item.get("is_starred") else ""
        tags = ", ".join(item.get("tech_tags", []))
        
        results.append(
            f"### [{item.get('id')}] {item.get('title_l1')}{star}\n"
            f"- **分類/狀態**: {item.get('category_name')} ({status})\n"
            f"- **來源**: {item.get('source_type')} | {item.get('url')}\n"
            f"- **技術標籤**: #{tags}\n"
            f"- **白話核心**: {item.get('summary_l1')}\n"
        )
    return f"找到 {len(results)} 筆相關情報：\n\n" + "\n---\n".join(results)


# ── 2. Get Detail Tool ──────────────────────────────────────────

@mcp.tool()
async def get_item_detail(item_id: str) -> str:
    """
    Retrieve full details for an item in OmniKeep, including L1 plain takeaway,
    L2 deep architectural breakdown, technical tags, and raw content snapshot.
    """
    item = get_item_by_id(item_id)
    if not item:
        return f"錯誤：找不到 ID 為「{item_id}」的情報項目。"

    tags = ", ".join(item.get("tech_tags", []))
    status = "已封存" if item.get("is_read") else "待讀 (Inbox)"
    star = "⭐ 已星標" if item.get("is_starred") else "未星標"

    output = [
        f"# {item.get('title_l1')}",
        f"- **ID**: {item.get('id')}",
        f"- **原始連結/引文**: {item.get('url')}",
        f"- **來源類型**: {item.get('source_type')} | **分類**: {item.get('category_name')}",
        f"- **狀態**: {status} | {star}",
        f"- **技術標籤**: #{tags}\n",
        "## ⚡ L1 白話核心痛點與價值",
        item.get("summary_l1", ""),
        "\n## 📊 L2 深度技術架構解構",
        item.get("deep_analysis", "無深入分析內容。"),
    ]

    raw = item.get("content_raw", "")
    if raw:
        preview_raw = raw[:2500] + ("\n...(原文過長已截斷)..." if len(raw) > 2500 else "")
        output.extend(["\n## 📖 原文節錄快照 (Snapshot)", preview_raw])

    return "\n".join(output)


# ── 3. Save to Brain Tool ───────────────────────────────────────

@mcp.tool()
async def save_to_brain(
    content_or_url: str,
    category: Optional[str] = None
) -> str:
    """
    Ingest a new item into OmniKeep Second Brain.
    Accepts:
    1. A web/YouTube URL (e.g. 'https://github.com/...')
    2. A technical text snippet, note, markdown summary, or code discussion.
    The item will be automatically parsed, tagged, and structured into L1/L2 format.
    """
    clean_input = content_or_url.strip()
    if not clean_input:
        return "錯誤：內容不能為空。"

    try:
        item = await run_pipeline(clean_input, manual_category=category)
        tags = ", ".join(item.get("tech_tags", []))
        return (
            f"✅ 成功存入 OmniKeep 第二大腦！\n"
            f"- **ID**: {item.get('id')}\n"
            f"- **標題**: {item.get('title_l1')}\n"
            f"- **自動分類**: {item.get('category_name')}\n"
            f"- **技術標籤**: #{tags}\n"
            f"- **白話重點**: {item.get('summary_l1')}\n"
            f"- **詳情可透過 get_item_detail('{item.get('id')}') 查看**"
        )
    except Exception as e:
        return f"❌ 存入失敗：{str(e)}"


# ── 4. List Recent Items Tool ───────────────────────────────────

@mcp.tool()
async def list_recent_items(
    triage_status: str = "inbox",
    category: Optional[str] = None,
    limit: int = 10
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
        limit=min(limit, 50)
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
            f"   重點: {item.get('summary_l1')[:90]}..."
        )
    return "\n".join(lines)


# ── 5. Update Status Tool ───────────────────────────────────────

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


# ── 6. Ask Brain Synthesis Tool (Massive Context) ────────────────

@mcp.tool()
async def ask_brain_synthesis(topic: str, top_k: int = 5) -> str:
    """
    Cross-reference multiple items in your brain related to a topic and generate
    a synthesized architectural comparison using Agnes AI's massive context window.
    """
    items = get_items(query=topic, limit=min(top_k, 15))
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


# ── 7. Resources ────────────────────────────────────────────────

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
    mcp.run()

if __name__ == "__main__":
    main()
