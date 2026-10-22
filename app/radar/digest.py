import json
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.providers import get_primary_provider
from app.database import save_radar_digest, get_item_by_id

DIGEST_PROMPT_TEMPLATE = """你是一位高階系統架構師與首席技術情報官。
以下是 OmniKeep 情報雷達近期自適應巡檢獲取的一批高質量技術項目（涵蓋 YouTube、GitHub、技術博客）：

{items_text}

請將以上情報綜合成一份極具乾貨的【OmniKeep 焦點技術戰報】：
格式要求：
1. 一律使用繁體中文（台灣習慣用語）。
2. 極簡、高密度、直擊本質，嚴禁廢話套話（如「值得注意的是」、「總結來說」）。
3. 結構：
   - ⚡ 核心趨勢總結（2-3點關鍵架構洞見）
   - 🛠️ 重大項目與發布解構（每個項目 1-2 行核心突破與實踐建議）
   - 🎯 後續行動/技術雷達建議
"""

async def generate_radar_digest(item_ids: List[str], digest_type: str = "evening") -> Dict[str, Any]:
    if not item_ids:
        return {"success": False, "message": "No items to digest"}

    items = []
    items_text_list = []
    for idx, iid in enumerate(item_ids, 1):
        item = get_item_by_id(iid)
        if item:
            items.append(item)
            items_text_list.append(
                f"[{idx}] {item['title_l1']} ({item['source_type']})\n"
                f"標籤: {', '.join(item.get('tech_tags') or [])}\n"
                f"白話核心: {item['summary_l1']}\n"
                f"連結: {item['url']}\n"
            )

    if not items:
        return {"success": False, "message": "Valid items not found"}

    items_text = "\n".join(items_text_list)
    prompt = DIGEST_PROMPT_TEMPLATE.format(items_text=items_text)

    llm = get_primary_provider()
    system_instruction = "你是一位極簡、專注高質量技術架構的情報官。輸出乾淨的 Markdown 格式。"
    
    try:
        report_md = await llm.generate_text(prompt, system_instruction)
    except Exception as e:
        report_md = f"戰報生成失敗: {str(e)}\n\n原始項目清單:\n{items_text}"

    now_str = datetime.now().strftime("%m/%d %H:%M")
    type_names = {"evening": "晚間焦點戰報", "morning": "清晨技術晨報", "custom": "特報"}
    title = f"OmniKeep 雷達 {type_names.get(digest_type, '焦點戰報')} ({now_str})"

    digest_id = save_radar_digest({
        "title": title,
        "digest_type": digest_type,
        "markdown_content": report_md,
        "item_ids": item_ids
    })

    return {
        "success": True,
        "digest_id": digest_id,
        "title": title,
        "markdown_content": report_md,
        "item_count": len(items)
    }
