import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.providers import get_provider


def radar_provider():
    """The radar slot (設定 › AI 服務商): falls back to the analysis chain."""
    return get_provider("radar")
from app.database import save_radar_digest, get_item_by_id
from app.error_translate import classify
from app.pipeline import interest_profile_block

logger = logging.getLogger("omnikeep.radar.digest")

# Title of each digest type; "daily" is the one maybe_send_daily_digest sends at the owner's hour.
DIGEST_TYPE_NAMES = {"evening": "晚間精選", "morning": "晨間精選", "daily": "每日精選", "custom": "精選"}

DIGEST_PROMPT_TEMPLATE = """你是一位高階系統架構師與首席技術情報官。
以下是 OmniKeep 情報雷達近期自適應巡檢獲取的一批高質量技術項目（涵蓋 YouTube、GitHub、技術博客）：

{items_text}

請將以上情報綜合成一份極具乾貨的【OmniKeep 焦點技術戰報】：
格式要求：
1. 一律使用繁體中文（台灣習慣用語）。
2. 極簡、高密度、直擊本質，嚴禁廢話套話（如「值得注意的是」、「總結來說」）。
3. 結構：
   - 核心趨勢與架構洞見（2-3點關鍵觀察）
   - 重點項目與發布解構（每個項目條列核心突破、量化指標與實踐建議）
   - 技術雷達與後續行動建議
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
                f"核心提要: {item['summary_l1']}\n"
                f"連結: {item['url']}\n"
            )

    if not items:
        return {"success": False, "message": "Valid items not found"}

    items_text = "\n".join(items_text_list)
    prompt = DIGEST_PROMPT_TEMPLATE.format(items_text=items_text) + interest_profile_block()

    llm = radar_provider()
    system_instruction = "你是一位極簡、專注高質量技術架構的情報官。輸出乾淨的 Markdown 格式。"
    
    # A failed write-up is neither saved nor announced. Stored, it would count as the digest
    # of its slot (the daily one is sent once a day) and be pushed as if it were the news.
    try:
        report_md = await llm.generate_text(prompt, system_instruction)
    except Exception as e:
        logger.warning("[Radar:Digest] %s digest was not written (%s: %s)", digest_type, type(e).__name__, e)
        return {"success": False, "message": f"摘要產生失敗：{classify(e)['hint']}"}
    if not (report_md or "").strip():
        logger.warning("[Radar:Digest] %s digest was not written (the model returned no text)", digest_type)
        return {"success": False, "message": "摘要產生失敗：AI 沒有回傳內容。"}

    now_str = datetime.now().strftime("%m/%d %H:%M")
    title = f"OmniKeep 探索{DIGEST_TYPE_NAMES.get(digest_type, '精選')}（{now_str}）"

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
