import json
import re
import uuid
import asyncio
from typing import Dict, Any, Optional
from app.database import (
    get_all_categories,
    save_item,
    normalize_canonical_url,
    find_item_by_canonical_or_url,
    save_citation
)
from app.parsers import is_youtube_url, fetch_youtube_metadata, parse_web_page
from app.providers import get_primary_provider, get_gemini_provider
from app.config import settings

ANALYSIS_SYSTEM_PROMPT = """你是一位頂尖的資深系統架構師與技術情報分析官。
你的任務是將使用者提供的內容精準消化，輸出結構化的兩段式情報（L1 速覽 + L2 深度剖析）。

嚴格規則：
1. 一律使用繁體中文（台灣習慣用語）。
2. 極簡、高密度乾貨，絕對禁止廢話與無意義客套套話（如「值得注意的是」、「總結來說」）。
3. 判斷該內容是否為「多專案/多工具/多庫盤點彙總」（例如：5大精選開源專案、10個必備工具、年度推薦庫列表、整合評測）。
4. 嚴格輸出合法的 JSON 物件，格式如下：
{
  "category": "從分類清單中精選1個，若皆不符合請填 Inbox",
  "title_l1": "簡潔有力、直擊本質的中文標題（25字以內）",
  "summary_l1": "白話核心重點（1-2句話說清楚這個專案/文章在做什麼，解決什麼核心痛點）",
  "tech_tags": ["新技術項1", "新技術項2", "專有名詞/核心依賴"],
  "deep_analysis": "L2 深入技術剖析（Markdown 格式，條列架構設計、核心規格參數、落地步驟與潛在限制）",
  "is_composite": false,
  "sub_entities": [
    {
      "name": "專案或工具名稱（如 OpenHands）",
      "canonical_url": "專案 GitHub 倉庫或官方網站網址（若文中提及或已知請填寫標準網址，未知填空字串）",
      "reason": "文中對此專案的評價、亮點或核心功能（1句話）"
    }
  ]
}

注意事項：
- 若內容只介紹單一專案、單篇新聞或單一概念，is_composite 請設為 false，且 sub_entities 設為空陣列 []。
- 若內容為盤點文、多專案推薦影片或清單彙總，is_composite 必須設為 true，並於 sub_entities 完整抽離列出每一個提及的獨立專案/工具，不可遺漏。"""

def is_pure_url(text: str) -> bool:
    clean = text.strip()
    if "\n" in clean or "\r" in clean or " " in clean:
        return False
    return clean.startswith("http://") or clean.startswith("https://")

async def _spawn_child_entity_background(source_parent_id: str, cit_id: str, target_name: str, target_url: str, mention_context: str):
    """Background worker to ingest an unpacked sub-project into its own standalone entry and link citation"""
    try:
        clean_url = normalize_canonical_url(target_url)
        # Check again if already exists
        existing = find_item_by_canonical_or_url(clean_url)
        if existing:
            save_citation({
                "id": cit_id,
                "source_parent_id": source_parent_id,
                "target_item_id": existing["id"],
                "target_canonical_url": clean_url,
                "target_name": target_name or existing.get("title_l1", ""),
                "mention_context": mention_context
            })
            return

        child_item = await run_pipeline(clean_url, manual_category="Github" if "github.com" in clean_url else None, is_sub_task=True)
        if child_item and "id" in child_item:
            save_citation({
                "id": cit_id,
                "source_parent_id": source_parent_id,
                "target_item_id": child_item["id"],
                "target_canonical_url": clean_url,
                "target_name": target_name or child_item.get("title_l1", ""),
                "mention_context": mention_context
            })
    except Exception as e:
        print(f"[Entity Fan-out] Background spawn failed for {target_url}: {e}")

async def run_pipeline(content_input: str, manual_category: Optional[str] = None, is_sub_task: bool = False) -> Dict[str, Any]:
    # 1. Fetch available categories
    cat_rows = get_all_categories()
    category_names = [c["name"] for c in cat_rows]
    cat_list_str = ", ".join(category_names)
    clean_input = content_input.strip()

    # 2. Route by input type (Pure URL vs Text Snippet/Note)
    if is_pure_url(clean_input):
        url = clean_input
        if is_youtube_url(url):
            source_type = "youtube"
            meta = await fetch_youtube_metadata(url)
            content_raw = f"# {meta['title']}\n\n頻道: {meta['author']}\nURL: {url}"
            
            # If Gemini keys are configured, use native YouTube video analysis
            if settings.gemini_keys:
                try:
                    gemini = get_gemini_provider()
                    prompt = f"""請觀看並深度分析此 YouTube 影片：{url}
影片標題：{meta['title']}
頻道：{meta['author']}

候選分類清單：[{cat_list_str}]
請分析影片內容，直接輸出結構化 JSON。"""
                    ai_result = await gemini.analyze_youtube(url, prompt)
                except Exception as e:
                    primary = get_primary_provider()
                    prompt = f"""分析此 YouTube 影片資訊：
標題：{meta['title']}
頻道：{meta['author']}
URL：{url}

候選分類清單：[{cat_list_str}]"""
                    ai_result = await primary.generate_json(prompt, ANALYSIS_SYSTEM_PROMPT)
            else:
                primary = get_primary_provider()
                prompt = f"""分析此 YouTube 影片資訊：
標題：{meta['title']}
頻道：{meta['author']}
URL：{url}

候選分類清單：[{cat_list_str}]"""
                ai_result = await primary.generate_json(prompt, ANALYSIS_SYSTEM_PROMPT)

            cover_image = meta.get("cover_image", "")
            author = meta.get("author", "")
            default_title = meta.get("title", "未命名項目")

        else:
            # Standard Web Page / GitHub / Article
            source_type = "web"
            page_data = await parse_web_page(url)
            content_raw = page_data.get("content_raw", "")
            cover_image = page_data.get("cover_image", "")
            author = page_data.get("author", "")
            default_title = page_data.get("title", "未命名項目")

            primary = get_primary_provider()
            prompt = f"""請深度分析以下網頁/文章內容：
網址：{url}
原始標題：{page_data.get('title', '')}

候選分類清單：[{cat_list_str}]

=== 內容節錄 ===
{content_raw[:12000]}
=== 內容結束 ===

請依據規範輸出結構化 JSON。"""
            ai_result = await primary.generate_json(prompt, ANALYSIS_SYSTEM_PROMPT)

    else:
        # Free-form Text Snippet / Paragraph / Thought Note
        source_type = "snippet"
        content_raw = clean_input
        cover_image = ""
        
        # Extract embedded URLs if any
        embedded_urls = re.findall(r'https?://[^\s)\]">]+', clean_input)
        item_id_seed = uuid.uuid4().hex[:10]
        if embedded_urls:
            primary_url = embedded_urls[0]
            url = f"{primary_url}#snippet-{item_id_seed}"
            author = f"節錄引文 ({primary_url})"
        else:
            url = f"note://{item_id_seed}"
            author = "筆記摘錄"

        first_line = clean_input.splitlines()[0].strip() if clean_input.splitlines() else "隨手筆記"
        default_title = first_line[:30]

        primary = get_primary_provider()
        prompt = f"""請深度分析以下使用者記錄的技術段落、筆記或片段資訊：
候選分類清單：[{cat_list_str}]

=== 筆記/段落內容 ===
{content_raw[:12000]}
=== 內容結束 ===

請精準提煉這段內容的技術價值，依據規範輸出結構化 JSON。"""
        ai_result = await primary.generate_json(prompt, ANALYSIS_SYSTEM_PROMPT)

    # Extract fields with safe defaults
    category_name = manual_category or ai_result.get("category", "Inbox")
    if category_name not in category_names and category_name != "Inbox":
        category_name = "Inbox"

    title_l1 = ai_result.get("title_l1") or default_title
    summary_l1 = ai_result.get("summary_l1") or "已儲存內容，無詳細摘要。"
    tech_tags = ai_result.get("tech_tags", [])
    if isinstance(tech_tags, str):
        tech_tags = [t.strip() for t in tech_tags.split(",") if t.strip()]

    deep_analysis = ai_result.get("deep_analysis", "")

    item_record = {
        "url": url,
        "source_type": source_type,
        "category_name": category_name,
        "title_l1": title_l1,
        "summary_l1": summary_l1,
        "tech_tags": tech_tags,
        "deep_analysis": deep_analysis,
        "content_raw": content_raw,
        "author": author,
        "cover_image": cover_image,
    }

    item_id = save_item(item_record)
    item_record["id"] = item_id

    # 3. Entity Fan-out & Citation Linking (Deduplication & Unpacking)
    sub_entities = ai_result.get("sub_entities", [])
    if isinstance(sub_entities, list) and sub_entities and not is_sub_task:
        for sub in sub_entities:
            if not isinstance(sub, dict):
                continue
            raw_name = (sub.get("name") or "").strip()
            raw_url = (sub.get("canonical_url") or "").strip()
            reason = (sub.get("reason") or "").strip()
            if not raw_name and not raw_url:
                continue

            canon_url = normalize_canonical_url(raw_url) if raw_url else ""
            target_item_id = None

            # Deduplication check: Is this entity already indexed in OmniKeep?
            existing = find_item_by_canonical_or_url(canon_url or raw_url)
            if existing:
                # Existing entry found -> Instant citation link without duplicate item
                target_item_id = existing["id"]
                save_citation({
                    "source_parent_id": item_id,
                    "target_item_id": target_item_id,
                    "target_canonical_url": canon_url or raw_url,
                    "target_name": raw_name or existing.get("title_l1", "未命名專案"),
                    "mention_context": reason
                })
            else:
                # First time seen -> Record citation first
                cit_id = save_citation({
                    "source_parent_id": item_id,
                    "target_item_id": None,
                    "target_canonical_url": canon_url or raw_url,
                    "target_name": raw_name,
                    "mention_context": reason
                })
                # If valid HTTP/HTTPS URL, spawn background ingestion
                if canon_url and (canon_url.startswith("http://") or canon_url.startswith("https://")):
                    try:
                        asyncio.create_task(_spawn_child_entity_background(item_id, cit_id, raw_name, canon_url, reason))
                    except Exception as e:
                        print(f"[Entity Fan-out] Error scheduling child spawn: {e}")

    return item_record
