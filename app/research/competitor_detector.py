"""
OmniKeep Competitor & Superior Alternative Detector
Discovers in-database duplicates, direct competitors, and superior alternatives using hybrid vector search and LLM adjudication.
"""

import json
import logging
import re
from typing import Dict, Any, List, Optional
from app.vector import search_hybrid
from app.database import save_citation, get_item_by_id
from app.providers import get_primary_provider

logger = logging.getLogger("omnikeep.competitor_detector")

COMPETITOR_EVAL_PROMPT = """你是一位嚴格客觀的系統架構選型評審官。
請審查以下【新收錄項目】與【庫內既有候選項目】，判斷兩者之間是否存在競爭、上位替代或重複關係：

【新收錄項目】
標題：{title}
摘要：{summary}
關鍵技術：{tags}

【庫內既有候選項目】
{candidates_block}

判定規則：
1. 若候選中存在完全相同之專案、文章或報導，relation_type 填 "duplicate"。
2. 若候選專案為同賽道同類型競品（功能相近且目標相同，如 Firecrawl vs Crawl4AI，或 uv vs poetry），relation_type 填 "competitor"。
3. 若庫內候選專案明顯為更成熟、星數更高、功能更完備的上位標準解，relation_type 填 "superior_alternative"。
4. 若僅為一般概念微弱沾邊、或毫無直接競爭/替代關係，has_relation 必須填 false。

輸出合法 JSON：
{
  "has_relation": true,
  "relation_type": "competitor" | "superior_alternative" | "duplicate",
  "matched_candidate_index": 1,
  "comparison_summary": "1句話精闢點出兩者核心技術架構差異與實務選型建議"
}"""


async def detect_competitors_and_alternatives(
    item_id: str,
    title: str,
    summary: str,
    tech_tags: List[str],
    category_name: str = "",
    provider=None
) -> Optional[Dict[str, Any]]:
    """Detect in-database duplicates, competitors or superior alternatives."""
    # Life & entertainment videos do not require tech competitor evaluation
    EXCLUDED_CATEGORIES = {"生活娛樂", "迷因語錄", "美食", "旅遊", "隔離區"}
    if category_name in EXCLUDED_CATEGORIES:
        return None

    clean_title = (title or "").strip()
    if not clean_title or clean_title in ("未命名項目", "未命名專案"):
        return None

    tags_str = " ".join(tech_tags[:3]) if isinstance(tech_tags, list) else ""
    raw_query = f"{clean_title} {tags_str}"
    clean_query = re.sub(r'[^\w\s\u4e00-\u9fff]', ' ', raw_query)
    query_words = [w for w in clean_query.split() if len(w) >= 2][:8]
    query = " ".join(query_words).strip() or clean_title

    try:
        candidates = search_hybrid(query, limit=6)
    except Exception as e:
        logger.debug(f"[CompetitorDetector] search_hybrid failed: {e}")
        return None

    # Filter out current item and empty entries
    valid_candidates = []
    for c in candidates:
        c_id = c.get("id")
        if not c_id or c_id == item_id:
            continue
        c_title = (c.get("title_l1") or "").strip()
        if not c_title or c_title in ("未命名項目", "未命名專案"):
            continue
        valid_candidates.append(c)

    if not valid_candidates:
        return None

    # Format candidates for LLM multiple choice
    candidate_lines = []
    for idx, c in enumerate(valid_candidates[:4], 1):
        c_sum = (c.get("summary_l1") or "")[:120].strip()
        candidate_lines.append(f"[{idx}] ID: {c['id']} | 標題: {c.get('title_l1')} | 摘要: {c_sum}")
    candidates_block = "\n".join(candidate_lines)

    prompt = (
        COMPETITOR_EVAL_PROMPT
        .replace("{title}", clean_title)
        .replace("{summary}", (summary or "")[:300].strip())
        .replace("{tags}", tags_str)
        .replace("{candidates_block}", candidates_block)
    )

    try:
        active_provider = provider or get_primary_provider()
        res = await active_provider.generate_json(prompt, "你是一位嚴格客觀的系統架構選型評審官。")
        if isinstance(res, dict) and res.get("has_relation"):
            rel_type = res.get("relation_type", "competitor")
            matched_idx = res.get("matched_candidate_index", 1)
            summary_diff = str(res.get("comparison_summary", "")).strip()

            if isinstance(matched_idx, int) and 1 <= matched_idx <= len(valid_candidates):
                target_item = valid_candidates[matched_idx - 1]
                target_id = target_item.get("id")
                target_title = target_item.get("title_l1") or "庫內專案"
                target_url = target_item.get("url") or ""

                prefix_map = {
                    "duplicate": "[庫內重複]",
                    "competitor": "[庫內競品]",
                    "superior_alternative": "[上位替代]"
                }
                prefix = prefix_map.get(rel_type, "[庫內競品]")

                # Record citation in database
                try:
                    save_citation({
                        "source_parent_id": item_id,
                        "target_item_id": target_id,
                        "target_canonical_url": target_url,
                        "target_name": target_title,
                        "mention_context": f"{prefix} {summary_diff}".strip()
                    })
                except Exception as e:
                    logger.debug(f"[CompetitorDetector] Citation save failed (e.g. mock id): {e}")

                return {
                    "relation_type": rel_type,
                    "target_item_id": target_id,
                    "target_title": target_title,
                    "target_url": target_url,
                    "comparison_summary": summary_diff
                }
    except Exception as e:
        logger.warning(f"[CompetitorDetector] Evaluation error: {e}")

    return None
