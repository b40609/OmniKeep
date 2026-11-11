"""Dream Pass (Taste Self-Reflection Engine)

Analyzes recent user behavior signals (stars, boosts, dampens, reads)
and suggests evolutions to the user's natural-language interest profile.
Employs an approve/dismiss gating workflow respecting user sovereignty.
"""
from typing import Dict, Any, Optional
import json
import logging
import re
from datetime import datetime, timezone
from collections import Counter
from app.database import (
    get_interest_profile,
    get_recent_taste_signals,
    create_dreampass_proposal,
    get_latest_dreampass_proposal,
    apply_dreampass_proposal,
    dismiss_dreampass_proposal,
    get_dreampass_proposal,
)
from app.providers import get_provider

logger = logging.getLogger("omnikeep.dreampass")


def radar_provider():
    """The radar slot (設定 › AI 服務商): falls back to the analysis chain."""
    return get_provider("radar")


def _ai_is_set_up() -> bool:
    """False when no AI is set up at all: no connection for the radar or analysis slot and
    none of the older flat settings. get_provider() would still hand back the default
    endpoint without a key, and calling that only records a failure."""
    from app import ai_connections
    return bool(ai_connections.resolve("radar")) or not ai_connections.needs_setup()


def _lines(value: Any, bullet: str = "") -> str:
    """A reply field as text: models answer with a string or with a list of lines."""
    if isinstance(value, (list, tuple)):
        return "\n".join(f"{bullet}{str(x).strip()}" for x in value if x is not None and str(x).strip())
    return str(value).strip() if value is not None else ""

_DREAMPASS_SYSTEM_PROMPT = """你是一位敏銳的「個人知識與情報品味管家」。
你的任務是回顧使用者最近的真實情報互動訊號（包含星標收藏、手動調升、封存、調降抑制的技術標籤與文章），
與使用者當前的「情報興趣畫像 (Interest Profile)」進行對照自省，
提出畫像調整建議，協助使用者的第二大腦保持對最新關注點的敏銳度，同時排除已不再感興趣的噪音。

【輸出原則】
1. 一律使用繁體中文（台灣習慣用語）。
2. 絕對嚴禁使用任何 LaTeX 語法。
3. 嚴謹基於提供的真實互動數據，不得憑空捏造。
4. 輸出必須為標準 JSON 格式，包含以下欄位：
   - "observations": 具體觀察到的品味演進與焦點轉移（條列 2-3 點）。
   - "suggested_profile": 結合原畫像修訂後的完整自然語言畫像（維持 150-350 字，流暢、具體、明確，可直接作為推薦與評審 prompt 的依據）。
   - "diff_summary": 條列指出「＋ 建議加強關注」與「－ 建議抑制淡化」的領域。
"""


def _heuristic_dreampass_analysis(signals: Dict[str, Any], current_profile: str) -> Dict[str, str]:
    """Fallback deterministic reflection if LLM is unavailable or fails."""
    pos_tags = []
    for item in signals.get("positive_items", []):
        pos_tags.extend(item.get("tech_tags", []))
    neg_tags = []
    for item in signals.get("negative_items", []):
        neg_tags.extend(item.get("tech_tags", []))

    pos_counts = Counter(pos_tags).most_common(5)
    neg_counts = Counter(neg_tags).most_common(3)

    top_pos_names = [tag for tag, _ in pos_counts]
    top_neg_names = [tag for tag, _ in neg_counts]

    observations = []
    if top_pos_names:
        observations.append(f"近期在「{', '.join(top_pos_names)}」領域有較高頻率的收藏與主動調升訊號。")
    if top_neg_names:
        observations.append(f"針對「{', '.join(top_neg_names)}」有多次抑制或調降動作，顯示偏好逐漸收斂。")
    if not observations:
        observations.append("近期沒有足夠的收藏、調升或調降訊號，看不出偏好有變化。")

    diff_lines = []
    if top_pos_names:
        diff_lines.append(f"＋ 強化關注：{', '.join(top_pos_names)}")
    if top_neg_names:
        diff_lines.append(f"－ 淡化排除：{', '.join(top_neg_names)}")
    diff_summary = "\n".join(diff_lines) if diff_lines else "（這次沒有調整建議）"

    # Construct suggested profile. Without a profile of the owner's own the suggestion is
    # built from the observed tags alone: no field of interest is assumed for them, and with
    # no signal either it stays empty (applying it changes nothing).
    base = current_profile.strip() if current_profile else ""
    additions = f"近期重點關注：{', '.join(top_pos_names)}。" if top_pos_names else ""
    exclusions = f"排除噪音：{', '.join(top_neg_names)}。" if top_neg_names else ""

    parts = [base] if base else []
    if additions and additions not in base:
        parts.append(additions)
    if exclusions and exclusions not in base:
        parts.append(exclusions)

    suggested_profile = " ".join(parts).strip()[:1000]

    return {
        "observations": "\n".join(f"• {o}" for o in observations),
        "suggested_profile": suggested_profile,
        "diff_summary": diff_summary,
    }


async def run_dreampass_reflection(days: int = 7) -> Dict[str, Any]:
    """Executes a taste self-reflection cycle and records a proposal."""
    signals = get_recent_taste_signals(days=days)
    current_profile = get_interest_profile()

    pos_items = signals.get("positive_items", [])
    neg_items = signals.get("negative_items", [])
    event_counts = signals.get("event_counts", {})
    total_actions = sum(event_counts.values())

    # Build prompt input data
    pos_desc = "\n".join(
        f"- [{it.get('category_name', '通用')}] {it.get('title_l1')} (Tags: {', '.join(it.get('tech_tags', [])[:4])})"
        for it in pos_items[:10]
    ) or "(無特別正向互動)"

    neg_desc = "\n".join(
        f"- {it.get('title_l1')} (Action: {it.get('event_type')}, Tags: {', '.join(it.get('tech_tags', [])[:4])})"
        for it in neg_items[:8]
    ) or "(無特定調降紀錄)"

    topics_desc = ", ".join(f"{t['tag']}(權重:{t['weight']})" for t in signals.get("top_topics", [])[:6])

    user_prompt = f"""【當前用戶興趣畫像 (Profile)】
{current_profile or "(尚未填寫，目前使用預設空畫像)"}

【近 {days} 天互動統計】
互動總次數: {total_actions} 次 ({json.dumps(event_counts, ensure_ascii=False)})
高權重話題: {topics_desc or "無"}

【近期待消化/高星標/提升之內容 (正面訊號)】
{pos_desc}

【近期被調降/抑制之內容 (負面訊號)】
{neg_desc}

請根據以上訊號進行品味自省，產出 JSON 格式的調整建議。
"""

    parsed = None
    if _ai_is_set_up():
        try:
            # Through the radar slot like every other radar call: the connections saved in the
            # app (local servers included), their fallback chain, pacing and usage counts.
            parsed = await radar_provider().generate_json(user_prompt, _DREAMPASS_SYSTEM_PROMPT)
            if not isinstance(parsed, dict) or not _lines(parsed.get("suggested_profile")):
                logger.warning("[DreamPass] LLM reflection came back without a suggested_profile, using heuristic")
                parsed = None
        except Exception as e:
            # Fall back to heuristic, but never silently: a dead key, a network
            # error or malformed JSON must show up in the logs.
            logger.warning(
                "[DreamPass] LLM reflection failed (%s: %s), using heuristic",
                type(e).__name__, e, exc_info=True,
            )
    else:
        logger.info("[DreamPass] No AI connection is set up, using heuristic")

    if not parsed:
        parsed = _heuristic_dreampass_analysis(signals, current_profile)

    obs = _lines(parsed.get("observations"), bullet="• ") or "近期關注點持續演進。"
    sug_prof = _lines(parsed.get("suggested_profile"))
    diff = _lines(parsed.get("diff_summary")) or "＋ 微調關注領域"

    prop_id = create_dreampass_proposal(
        observations=obs,
        suggested_profile=sug_prof,
        diff_summary=diff,
        current_profile=current_profile,
    )

    return {
        "id": prop_id,
        "status": "pending",
        "observations": obs,
        "suggested_profile": sug_prof,
        "diff_summary": diff,
        "current_profile": current_profile,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
