"""
OmniKeep Model Context Protocol (MCP) Server
Allows external AI Agents (ChatGPT App, Claude, Cursor, Antigravity) to query,
retrieve, synthesize, and write back engineering intelligence into OmniKeep's Second Brain.
"""

import sys
import json
import uuid
import sqlite3
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any
from mcp.server.fastmcp import FastMCP

from app.config import settings
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
from app.logging_setup import configure_logging

# The pipeline, the AI providers and the vector index are imported inside the tools
# that use them: a stdio server is started by every agent session and must come up
# in about a second (docs/agent_setup_skill_design.md §7).

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
        return f"OmniKeep 裡找不到和「{query}」有關的收藏。"

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

    output = f"找到 {len(results)} 則相關的收藏：\n\n" + "\n\n".join(results)
    output += "\n\n---\n💡 提示：使用 `get_item_architecture(item_id)` 取得完整的重點分析；使用 `writeback_insight(...)` 可將對話結論寫回大腦。"
    return output


# ── 1b. Hybrid Search Tool (FTS5 + sqlite-vec via RRF) ──────────

@mcp.tool()
async def hybrid_search_brain(
    query: str,
    category: Optional[str] = None,
    is_starred: Optional[bool] = None,
    is_read: Optional[bool] = None,
    limit: int = 5
) -> str:
    """
    Perform advanced Hybrid Search combining SQLite FTS5 keyword matching and
    vector semantic search (sqlite-vec) using Reciprocal Rank Fusion (RRF).
    Discovers conceptually related intelligence even when keywords do not match verbatim.
    """
    from app.vector import search_hybrid
    fetch_limit = min(limit * 3, 50)
    raw_results = await search_hybrid(query=query, limit=fetch_limit, usable_only=True)

    filtered = []
    for item in raw_results:
        if category and item.get("category_name", "").lower() != category.lower():
            continue
        if is_starred is not None and bool(item.get("is_starred")) != is_starred:
            continue
        if is_read is not None and bool(item.get("is_read")) != is_read:
            continue
        filtered.append(item)
        if len(filtered) >= limit:
            break

    # An agent must not read keyword-only results as "nothing related exists".
    from app.brain import retrieval_report
    notice = retrieval_report(raw_results)["notice"]
    notice_line = f"\n\n注意：{notice}" if notice else ""

    if not filtered:
        return f"OmniKeep 裡找不到和「{query}」語意相近的收藏。{notice_line}"

    results = []
    for item in filtered:
        status = "已讀" if item.get("is_read") else "待讀"
        star = " [⭐]" if item.get("is_starred") else ""
        tags_raw = item.get("tech_tags", [])
        if isinstance(tags_raw, str):
            try:
                tags = ", ".join(json.loads(tags_raw))
            except Exception:
                tags = tags_raw
        elif isinstance(tags_raw, list):
            tags = ", ".join(tags_raw)
        else:
            tags = ""

        rrf = item.get("rrf_score", 0.0)
        sim = item.get("similarity", 0.0)
        sim_str = f" · 語意分: {sim:.2f}" if sim > 0 else ""

        results.append(
            f"### [{item.get('id')}] {item.get('title_l1')}{star}\n"
            f"- **分類/狀態**: {item.get('category_name')} ({status}){sim_str} · RRF: {rrf}\n"
            f"- **技術標籤**: #{tags}\n"
            f"- **白話核心**: {item.get('summary_l1')}"
        )

    heading = "【關鍵字檢索】" if notice else "【混合檢索 (FTS5 + 向量)】"
    output = f"{heading}找到 {len(results)} 則相關的收藏：\n\n" + "\n\n".join(results) + notice_line
    output += "\n\n---\n💡 提示：使用 `get_item_architecture(item_id)` 取得完整的重點分析；使用 `read_sql_query(...)` 進行結構化唯讀查詢。"
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
        return f"錯誤：找不到 ID 為「{item_id}」的收藏。"

    tags = ", ".join(item.get("tech_tags", []))
    status = "已封存" if item.get("is_read") else "待讀 (Inbox)"
    star = "已加星" if item.get("is_starred") else "未加星"

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
        return f"錯誤：找不到 ID 為「{item_id}」的收藏。"

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
        mode = "✅ 已把這次的結論存進 OmniKeep。"

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

    from app.pipeline import run_pipeline
    try:
        item = await run_pipeline(clean_input, manual_category=category, origin="agent")
        if item.get("analysis_status") == "pending":
            # No AI is connected: the content is stored, nothing was analysed.
            return (
                f"✅ 已存入 OmniKeep（尚未分析）。\n"
                f"- **ID**: {item.get('id')}\n"
                f"- **標題**: {item.get('title_l1')}\n"
                f"- 還沒有接上 AI，所以只存了標題、網址與原文。到「設定 › AI」接上 AI 連線後會自動補分析。"
            )
        tags = ", ".join(item.get("tech_tags", []))
        return (
            f"✅ 已存入 OmniKeep。\n"
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
        return f"「{triage_status}」裡沒有收藏。"

    lines = [f"### OmniKeep 最近的收藏（{triage_status}）："]
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
        status_str.append("已加星" if is_starred else "已取消加星")

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
        return f"OmniKeep 裡沒有和「{topic}」有關的收藏，沒辦法寫跨篇綜述。"

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
    from app.providers import get_provider
    primary = get_provider("brain")

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
        return f"## OmniKeep 跨篇綜述：{topic}\n\n{report}"
    except Exception as e:
        return f"跨篇合成失敗：{str(e)}"


# ── 10. Watch & Proposal Tools (Local Proposal Engine) ──────────

@mcp.tool()
async def list_proposals(status: str = "pending", limit: int = 10) -> str:
    """List OmniKeep proposal cards (default: pending ones).

    Each proposal is a glass-box suggestion for the user's own machine — e.g. a
    risk finding from the desktop L0 scan, or an improvement idea for a watched
    project. Returns verdict sentence + scores (impact/confidence/effort)
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


# ── 10b. Read-Only SQL Query Tool ──────────────────────────────

def _read_only_connection() -> sqlite3.Connection:
    """A connection that cannot write: the file is opened read-only and query_only is on."""
    db_uri = Path(settings.DATABASE_PATH).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(db_uri, uri=True, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA query_only = ON")
    return conn


@mcp.tool()
async def read_sql_query(query: str, limit: int = 50) -> str:
    """
    Execute a read-only SQL query against omnikeep.db (SELECT, PRAGMA, EXPLAIN, WITH only).
    Write operations (INSERT, UPDATE, DELETE, DROP, ALTER) are strictly rejected.
    """
    clean = query.strip()
    first_word = clean.split()[0].upper() if clean.split() else ""
    if first_word not in ("SELECT", "PRAGMA", "EXPLAIN", "WITH"):
        return "錯誤：僅允許唯讀查詢（SELECT, PRAGMA, EXPLAIN, WITH）。"

    if first_word in ("SELECT", "WITH") and "LIMIT" not in clean.upper():
        clean = f"{clean} LIMIT {min(limit, 100)}"

    # The first-word check is only a hint: `WITH x AS (...) DELETE ...` and
    # `PRAGMA user_version = 1` pass it. The connection itself refuses writes.
    try:
        conn = _read_only_connection()
    except sqlite3.Error as e:
        return f"SQL 執行錯誤: {str(e)}"
    try:
        cursor = conn.cursor()
        cursor.execute(clean)
        rows = cursor.fetchall()
        if not rows:
            return "查詢結果為空 (0 rows)。"
        results = [dict(row) for row in rows]
        return json.dumps(results, ensure_ascii=False, indent=2, default=str)
    except Exception as e:
        return f"SQL 執行錯誤: {str(e)}"
    finally:
        conn.close()


# ── 10c. Setup Tools (agent-driven first run) ───────────────────
# docs/agent_setup_skill_design.md §2–§4; the logic lives in app/setup_flow.py.
# Every tool returns JSON. None of them returns a credential: keys show only
# "configured" and the last four characters. Tools that write go through the
# running service so the change applies at once.

def _setup_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


async def _setup_call(fn, *args, **kwargs) -> str:
    from app import setup_flow
    try:
        result = fn(*args, **kwargs)
        if hasattr(result, "__await__"):
            result = await result
        return _setup_json(result)
    except setup_flow.SetupError as exc:
        return _setup_json({"ok": False, "error": str(exc)})


@mcp.tool()
async def omnikeep_scan() -> str:
    """Setup step 1. Scan this machine and OmniKeep without reading personal content:
    CPU/RAM/GPU, OmniKeep version and whether its service runs, item and radar-source
    counts, AI settings in effect (keys only as configured + last four), local Ollama,
    the last setup answers, OmniKit profile locations, and how many Chrome/Edge bookmarks
    and GitHub stars exist (counts only). Ask only about what the scan cannot tell."""
    from app import setup_flow
    return await _setup_call(setup_flow.scan)


@mcp.tool()
async def omnikeep_peek(url: str, max_chars: int = 3000) -> str:
    """Fetch and parse one link with OmniKeep's parsers (Threads, YouTube, Bilibili, web
    pages) and return its title, author and text excerpt. No AI call and nothing is saved:
    use it on the user's seed links to refine the drafted topics."""
    from app import setup_flow
    return await _setup_call(setup_flow.peek, url, max_chars)


@mcp.tool()
async def omnikeep_check_sources(sources: List[Dict[str, Any]], recent: int = 3) -> str:
    """Verify candidate radar sources before offering them. Each source is
    {"url": ..., "source_type"?: youtube|github|rss|google_news|web_change, "name"?: ...};
    a site's home page finds its RSS automatically, and a bare keyword is a Google News query.
    Returns per source: ok, resolved feed URL, latest date, posts per week and the latest
    titles. Trial fetch only: nothing is saved. Offer only sources with ok=true (max 20 per call)."""
    from app import setup_flow
    return await _setup_call(setup_flow.check_sources, sources, recent)


@mcp.tool()
async def omnikeep_list_provider_options() -> str:
    """AI service options for the user to choose from (address, suggested model, limits,
    signup link, date checked), plus what is configured now. Explain the trade-offs and
    let the user decide; no option uses Claude, Antigravity or ChatGPT subscriptions."""
    from app import setup_flow
    return await _setup_call(setup_flow.list_provider_options)


@mcp.tool()
async def omnikeep_open_settings(card: str = "", tab: str = "ai") -> str:
    """Link to OmniKeep's settings page on the given tab (ai, telegram, line, push, ...).
    Give it to the user to paste a key there themselves: never ask for a key in chat.
    Then call omnikeep_test_provider."""
    from app import setup_flow
    return await _setup_call(setup_flow.open_settings, card, tab)


@mcp.tool()
async def omnikeep_test_provider(service: str = "analysis", connection_id: str = "") -> str:
    """Test a saved credential with a small real request (a Chinese JSON reply for chat).
    connection_id: one AI connection from omnikeep_list_provider_options "current".
    Otherwise service: a task slot (analysis, brain, radar, embeddings, video: tests the
    first connection in it) or telegram, line, github. Returns ok and a message that says
    what to fix; never the key."""
    from app import setup_flow
    return await _setup_call(setup_flow.test_provider, service, connection_id)


@mcp.tool()
async def omnikeep_preview_setup(answers: Dict[str, Any]) -> str:
    """Validate the setup answers and return what would change (before/after), with a
    confirm_code. Nothing is written. answers (JSON):
    first run: {"stage": "first", "about_you", "interest_profile", "topics": [...],
      "seed_links": [...], "sources": [{"name","source_type","url","pack"}],
      "radar": {"enabled", "interval_minutes"},
      "ai_order": [connection ids for analysis, primary first, then fallbacks]};
    second run (after the first analysis and digest): {"stage": "followup",
      "analysis_depth": standard|concise|technical|actionable,
      "notifications": {"mode": silent|daily_digest|vip_alert, "daily_digest_hour": 0-23,
      "channels": [web_push|telegram|line]}}.
    Show the changes to the user as they are and ask before applying."""
    from app import setup_flow

    async def run():
        try:
            return await setup_flow.call_service("POST", "/api/setup/preview", json_body={"answers": answers})
        except setup_flow.ServiceUnavailable:
            result = setup_flow.preview(answers)
            result["note"] = "OmniKeep 服務沒在跑：這是直接讀資料庫的預覽；套用前要先啟動服務"
            return result
        except setup_flow.ServiceError as exc:
            raise setup_flow.SetupError(str(exc)) from exc
    return await _setup_call(run)


@mcp.tool()
async def omnikeep_apply_setup(answers: Dict[str, Any], confirm_code: str) -> str:
    """Apply the setup the user approved: the same answers plus the confirm_code from
    omnikeep_preview_setup. Refused if the answers or the settings changed since the preview."""
    from app import setup_flow
    return await _setup_call(setup_flow.call_service, "POST", "/api/setup/apply",
                             json_body={"answers": answers, "confirm_code": confirm_code})


@mcp.tool()
async def omnikeep_ingest(url: str) -> str:
    """Analyze one link and save it to OmniKeep (the first success: show the result and ask
    about analysis depth). Takes as long as one AI analysis."""
    from app import setup_flow
    return await _setup_call(setup_flow.ingest, url)


@mcp.tool()
async def omnikeep_run_radar() -> str:
    """Run one radar scan now and build a radar digest of what it found; returns the digest
    Markdown. Can take minutes: it fetches every active source and analyzes a few items."""
    from app import setup_flow
    return await _setup_call(setup_flow.call_service, "POST", "/api/setup/run-radar", timeout=900.0)


@mcp.tool()
async def omnikeep_import(kind: str, path: str = "", browser: str = "", profile: str = "",
                          enqueue_ai: bool = False, limit: int = 1000) -> str:
    """Import old data. kind: "bookmarks" (path to an export file, or browser="chrome"/"edge"
    for this machine's bookmarks; Pocket CSV works too), "github_stars" (needs `gh auth login`),
    or "opml" (path; feeds become radar sources). Saves only title and URL unless
    enqueue_ai=true, which queues every link for AI analysis and uses quota."""
    from app import setup_flow
    return await _setup_call(setup_flow.import_data, kind, path, browser, profile, enqueue_ai, limit)


# ── 11. Resources ───────────────────────────────────────────────

@mcp.resource("omnikeep://stats")
async def get_stats_resource() -> str:
    """Returns current real-time counts across Inbox, Starred, Archived, and Total."""
    stats = get_status_counts()
    return json.dumps(stats, ensure_ascii=False, indent=2)

@mcp.resource("omnikeep://schema")
async def get_schema_resource() -> str:
    """Returns database schema definition and semantic data dictionary for OmniKeep."""
    schema_dict = {
        "database": "omnikeep.db (SQLite WAL mode with FTS5 and sqlite-vec)",
        "tables": {
            "items": {
                "description": "核心知識庫情報項目（文章、影音、技術規格、筆記）",
                "columns": {
                    "id": "TEXT PRIMARY KEY - 唯一代碼",
                    "url": "TEXT UNIQUE - 原始收錄網址",
                    "source_type": "TEXT - 來源類型 (youtube, bilibili, web, reel, twitter, note)",
                    "category_name": "TEXT - 所屬分類 (預設 'Inbox')",
                    "title_l1": "TEXT - L1 直擊本質的精煉標題",
                    "summary_l1": "TEXT - L1 白話核心痛點與解法 (1-2 句話)",
                    "tech_tags": "TEXT (JSON Array) - 技術標籤清單",
                    "deep_analysis": "TEXT - L2 深度技術架構、規格解構與詳細 Markdown",
                    "content_raw": "TEXT - 清洗後的原始純淨文本或字幕全文",
                    "author": "TEXT - 作者或頻道名稱",
                    "published_date": "TEXT - 原文發布日期",
                    "is_starred": "INTEGER - 1: ⭐ 星標收藏, 0: 一般未加星",
                    "is_read": "INTEGER - 1: 已封存/已讀 (Archive), 0: 待讀 (Inbox)",
                    "origin": "TEXT - 'manual': 手動收錄, 'radar': 情報雷達主動捕獲",
                    "analysis_status": "TEXT - 'done': 解析完成, 'processing', 'failed'",
                    "created_at": "DATETIME - 建立時間",
                    "updated_at": "DATETIME - 更新時間"
                }
            },
            "categories": {
                "description": "知識庫分類清單",
                "columns": {
                    "id": "INTEGER PRIMARY KEY",
                    "name": "TEXT UNIQUE - 分類名稱",
                    "icon": "TEXT - UI 圖標名稱",
                    "sort_order": "INTEGER - 排序權重"
                }
            },
            "proposals": {
                "description": "自主情報雷達產生的決策與架構提案",
                "columns": {
                    "id": "TEXT PRIMARY KEY",
                    "item_id": "TEXT - 關聯的情報項目 ID",
                    "target_id": "TEXT - 關聯的監控目標 ID",
                    "proposal_type": "TEXT - 'risk': 風險警示, 'architectural': 架構升級建議",
                    "impact": "REAL (0-10) - 影響力評分",
                    "confidence": "REAL (0-10) - 信心度",
                    "effort": "REAL (0-10) - 實施成本",
                    "status": "TEXT - 'pending': 待決策, 'approved': 已採納, 'dismissed': 已忽略",
                    "created_at": "DATETIME"
                }
            },
            "watch_targets": {
                "description": "自主監看目標目錄與程式庫",
                "columns": {
                    "id": "TEXT PRIMARY KEY",
                    "name": "TEXT - 監控目標名稱",
                    "path": "TEXT - 本機路徑",
                    "preset": "TEXT - 監控預設策略 ('balanced', 'strict')",
                    "is_active": "INTEGER - 1: 啟用中, 0: 暫停",
                    "last_scan_at": "TEXT - 最後掃描時間",
                    "fingerprint_version": "TEXT - 程式庫指紋版本"
                }
            },
            "items_fts": {
                "description": "SQLite FTS5 全文索引虛擬表（trigram 分詞：任何 3 字以上的子字串都查得到，中文也可以；少於 3 字請改用 LIKE）。用 id 欄位對回 items.id",
                "indexed_columns": ["title_l1", "summary_l1", "tech_tags", "deep_analysis", "content_raw"]
            }
        }
    }
    return json.dumps(schema_dict, ensure_ascii=False, indent=2)


@mcp.resource("omnikeep://golden-queries")
async def get_golden_queries_resource() -> str:
    """Returns verified golden Text-to-SQL query templates (Few-Shot examples) for AI Agents."""
    golden_queries = [
        {
            "scenario": "查詢待讀 (Inbox) 且已加星標 (Starred) 的高價值精華情報",
            "sql": "SELECT id, title_l1, category_name, tech_tags, summary_l1, created_at FROM items WHERE is_read = 0 AND is_starred = 1 ORDER BY created_at DESC LIMIT 10;"
        },
        {
            "scenario": "統計各分類下的情報總數、待讀數與星標數",
            "sql": "SELECT category_name, COUNT(*) AS total_count, SUM(CASE WHEN is_read = 0 THEN 1 ELSE 0 END) AS unread_count, SUM(CASE WHEN is_starred = 1 THEN 1 ELSE 0 END) AS starred_count FROM items GROUP BY category_name ORDER BY total_count DESC;"
        },
        {
            "scenario": "依特定技術標籤（例如 AI、Agent 或 Quant）篩選情報",
            "sql": "SELECT id, title_l1, category_name, tech_tags, summary_l1 FROM items WHERE tech_tags LIKE '%Agent%' OR tech_tags LIKE '%AI%' ORDER BY created_at DESC LIMIT 10;"
        },
        {
            "scenario": "查詢最近 7 天由情報雷達（Radar）自主捕獲的項目",
            "sql": "SELECT id, title_l1, category_name, origin, created_at FROM items WHERE origin = 'radar' AND created_at >= datetime('now', '-7 days') ORDER BY created_at DESC LIMIT 10;"
        },
        {
            "scenario": "查詢待決策 (pending) 且影響力大於 7 分的高優先級提案",
            "sql": "SELECT p.id, p.proposal_type, p.impact, p.confidence, p.effort, i.title_l1 FROM proposals p JOIN items i ON p.item_id = i.id WHERE p.status = 'pending' AND p.impact >= 7.0 ORDER BY p.impact DESC LIMIT 10;"
        },
        {
            "scenario": "統計各情報來源（YouTube, Bilibili, Web 等）的數量與百分比佔比",
            "sql": "SELECT source_type, COUNT(*) AS count, ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM items), 1) AS percentage FROM items GROUP BY source_type ORDER BY count DESC;"
        },
        {
            "scenario": "使用 SQLite FTS5 全文索引檢索特定關鍵字",
            "sql": "SELECT i.id, i.title_l1, i.category_name, i.summary_l1 FROM items_fts fts JOIN items i ON fts.id = i.id WHERE items_fts MATCH '\"FastAPI\" OR \"向量檢索\"' ORDER BY rank LIMIT 10;"
        },
        {
            "scenario": "查詢目前活躍的監看目標及其指紋更新狀態",
            "sql": "SELECT id, name, target_type, path, preset, last_scan_at, fingerprint_version FROM watch_targets WHERE is_active = 1 ORDER BY last_scan_at DESC;"
        },
        {
            "scenario": "查看最近的備份紀錄與檔案大小 (MB)",
            "sql": "SELECT id, sink, status, file_path, ROUND(size_bytes / 1024.0 / 1024.0, 2) AS size_mb, created_at FROM backup_runs ORDER BY created_at DESC LIMIT 10;"
        },
        {
            "scenario": "查詢特定情報項目的關聯引用 (Citations)",
            "sql": "SELECT c.id, c.target_name, c.target_canonical_url, c.mention_context FROM item_citations c WHERE c.source_parent_id = 'YOUR_ITEM_ID';"
        }
    ]
    return json.dumps(golden_queries, ensure_ascii=False, indent=2)


@mcp.resource("omnikeep://categories")
async def get_categories_resource() -> str:
    """Returns all configured categories and item counts."""
    cats = get_all_categories()
    return json.dumps(cats, ensure_ascii=False, indent=2)


# ── CLI Entrypoint ──────────────────────────────────────────────

def _preload_before_stdin() -> None:
    """Load numpy before the stdio transport starts reading stdin.

    On Windows, importing numpy while another thread is blocked reading the stdin
    pipe hangs for good (measured 2026-11-05: numpy and sqlite_vec, which loads it;
    psutil, lxml, cryptography, openai and the parsers do not). The stdio reader is
    such a thread, and the pipeline and the vector index import numpy lazily, so the
    first tool that needs them would never answer. Costs about 0.1 s.
    """
    if sys.platform != "win32":
        return
    try:
        import numpy  # noqa: F401
    except ImportError:
        pass


def main():
    parser = argparse.ArgumentParser(description="OmniKeep MCP Server")
    parser.add_argument("--transport", choices=["stdio", "sse"], default="stdio", help="MCP transport mode")
    args = parser.parse_args()
    configure_logging()  # stderr; stdout belongs to the stdio transport

    if args.transport == "sse":
        import uvicorn
        from app.config import settings
        uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT)
    else:
        # A separate process from the web service: load the keys saved in the app too.
        from app.app_settings import apply_overrides
        apply_overrides()
        _preload_before_stdin()
        mcp.run(transport="stdio")

if __name__ == "__main__":
    main()
