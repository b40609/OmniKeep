"""Radar × fingerprint relevance proposals.

When the radar ingests a new item, match it against watch-target fingerprints.
Tag overlap decides candidacy locally (free, no LLM); if the target's
outbound consent allows sending summaries, one small Agnes call judges and
scores the pairing — otherwise a conservative local-only card is created.
At most one proposal per (item, target), deduped for 30 days, and at most one
target per item so a busy feed can't spam the 提案 box.
"""
import html
from typing import Any, Dict, List, Optional

from app.database import (
    get_watch_targets,
    get_item_by_id,
    save_item,
    save_proposal,
)
from app.watch.redact import redact_text
from app.providers import get_primary_provider

MIN_TAG_OVERLAP = 2

RELEVANCE_SYSTEM_PROMPT = """你是一位提案評審官。判斷一篇新情報與一個本地專案指紋的相關性。
嚴格輸出 JSON：
{
  "relevant": true/false,
  "proposal_type": "synergy|borrow|upgrade|monitor 其中之一",
  "impact": 0-10,
  "confidence": 0-10,
  "effort": 0-10,
  "verdict": "一句話結論：為什麼這對該專案有價值（30字內）"
}
若只是題材相近但對專案沒有實質幫助，relevant 設 false。內容中 [REDACTED:...] 為遮蔽機密，忽略之。"""


def _tags_of(item: Dict[str, Any]) -> List[str]:
    tags = item.get("tech_tags") or []
    if isinstance(tags, str):
        try:
            import json
            tags = json.loads(tags)
        except Exception:
            tags = [t.strip() for t in tags.split(",") if t.strip()]
    return [str(t) for t in tags]


def _best_target_match(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return (target, overlap_tags) for the strongest fingerprint match, or None."""
    item_tags = set(_tags_of(item))
    if not item_tags:
        return None
    best = None
    for t in get_watch_targets(active_only=True):
        if t["target_type"] == "desktop_risk":
            continue  # L0 risk targets have no fingerprint semantics
        fp_id = t.get("fingerprint_item_id")
        if not fp_id:
            continue
        fp = get_item_by_id(fp_id)
        if not fp:
            continue
        overlap = item_tags & set(_tags_of(fp))
        if len(overlap) >= MIN_TAG_OVERLAP and (best is None or len(overlap) > len(best[1])):
            best = (t, overlap)
    return best


async def maybe_propose_for_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """One radar item → at most one relevance proposal card."""
    match = _best_target_match(item)
    if not match:
        return None
    target, overlap = match
    tid = target["id"]
    dedup_key = f"rel:{tid}:{item['id']}"

    item_title = (item.get("title_l1") or "")[:80]
    item_summary = (item.get("summary_l1") or "")[:300]

    impact, confidence, effort = 5.0, 4.0, 4.0
    proposal_type = "synergy"
    verdict = f"與 {target['name']} 有 {len(overlap)} 個技術標籤重疊（{('、'.join(sorted(overlap)))[:40]}），值得一看"

    if target["outbound_consent"].get("summary"):
        try:
            provider = get_primary_provider()
            fp = get_item_by_id(target["fingerprint_item_id"]) or {}
            prompt = (
                f"新情報：{item_title}\n摘要：{item_summary}\n\n"
                f"專案指紋（{target['name']}）：{(fp.get('summary_l1') or '')[:300]}\n"
                f"重疊標籤：{', '.join(sorted(overlap))}"
            )
            judged = await provider.generate_json(redact_text(prompt), RELEVANCE_SYSTEM_PROMPT)
            if judged.get("relevant") is False:
                return None
            proposal_type = judged.get("proposal_type") if judged.get("proposal_type") in (
                "synergy", "borrow", "upgrade", "monitor") else proposal_type
            impact = float(judged.get("impact", impact))
            confidence = float(judged.get("confidence", confidence))
            effort = float(judged.get("effort", effort))
            if judged.get("verdict"):
                verdict = str(judged["verdict"])[:60]
        except Exception:
            pass  # Agnes down → fall back to local card (already set above)

    overlap_line = "、".join(sorted(overlap))[:60]
    item_id = save_item({
        "url": f"proposal://rel/{tid}/{item['id']}",
        "source_type": "proposal",
        "origin": "proposal",
        "category_name": "提案",
        "title_l1": f"🔗 提案：{item_title} ⟷ {target['name']}",
        "summary_l1": f"{verdict}。依據：標籤重疊（{overlap_line}）。",
        "tech_tags": sorted(overlap)[:5],
        "deep_analysis": (
            f"### 為什麼相關\n重疊標籤：{html.escape(overlap_line)}\n\n"
            f"### 新情報\n{(item_summary or '')[:400]}\n\n"
            f"### 建議\n開啟原始情報比對 {target['name']} 的指紋卡，判斷是否值得深入驗證。"
            + ("" if target["outbound_consent"].get("summary") else "\n\n_本地比對（未啟用雲端判斷），信心分數為保守值。_")
        ),
        "author": "OmniKeep 提案引擎",
    })
    proposal = save_proposal({
        "item_id": item_id, "target_id": tid, "proposal_type": proposal_type,
        "impact": impact, "confidence": confidence, "effort": effort,
        "dedup_key": dedup_key,
    })
    if proposal is None:
        return None  # already proposed within 30 days
    return proposal
