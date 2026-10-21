import json
from typing import Dict, Any, Optional
from app.database import get_all_categories, save_item
from app.parsers import is_youtube_url, fetch_youtube_metadata, parse_web_page
from app.providers import get_primary_provider, get_gemini_provider
from app.config import settings

ANALYSIS_SYSTEM_PROMPT = """你是一位頂尖的資深系統架構師與技術情報分析官。
你的任務是將使用者提供的內容精準消化，輸出結構化的兩段式情報（L1 速覽 + L2 深度剖析）。

嚴格規則：
1. 一律使用繁體中文（台灣習慣用語）。
2. 極簡、高密度乾貨，絕對禁止廢話與無意義客套套話（如「值得注意的是」、「總結來說」）。
3. 嚴格輸出合法的 JSON 物件，格式如下：
{
  "category": "從分類清單中精選1個，若皆不符合請填 Inbox",
  "title_l1": "簡潔有力、直擊本質的中文標題（25字以內）",
  "summary_l1": "白話核心重點（1-2句話說清楚這個專案/文章在做什麼，解決什麼核心痛點）",
  "tech_tags": ["新技術項1", "新技術項2", "專有名詞/核心依賴"],
  "deep_analysis": "L2 深入技術剖析（Markdown 格式，條列架構設計、核心規格參數、落地步驟與潛在限制）"
}"""

async def run_pipeline(url: str, manual_category: Optional[str] = None) -> Dict[str, Any]:
    # 1. Fetch available categories
    cat_rows = get_all_categories()
    category_names = [c["name"] for c in cat_rows]
    cat_list_str = ", ".join(category_names)

    # 2. Check if YouTube
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
                # Fallback to Primary LLM with title/meta
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

    else:
        # Standard Web Page / GitHub / Article
        source_type = "web"
        page_data = await parse_web_page(url)
        content_raw = page_data.get("content_raw", "")
        cover_image = page_data.get("cover_image", "")
        author = page_data.get("author", "")

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

    # Extract fields with safe defaults
    category_name = manual_category or ai_result.get("category", "Inbox")
    if category_name not in category_names and category_name != "Inbox":
        category_name = "Inbox"

    title_l1 = ai_result.get("title_l1") or meta.get("title", "未命名項目") if is_youtube_url(url) else page_data.get("title", "未命名項目")
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
    return item_record
