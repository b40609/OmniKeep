"""Radar × fingerprint relevance proposals.

When the radar ingests a new item, match it against watch-target fingerprints.
Tag overlap decides candidacy locally (free, no LLM); if the target's
outbound consent allows sending summaries, one small Agnes call judges and
scores the pairing — otherwise a conservative local-only card is created.
At most one proposal per (item, target), deduped for 30 days, and at most one
target per item so a busy feed can't spam the 提案 box.
"""
import html
import logging
import math
import uuid
from typing import Any, Dict, List, Optional

from app.database import (
    get_watch_targets,
    get_item_by_id,
    get_watch_target,
    proposal_seen,
    save_proposal,
)
from app.watch.redact import redact_text
from app.watch.locks import target_lock
from app.providers import get_primary_provider

MIN_TAG_OVERLAP = 2
logger = logging.getLogger("omnikeep.watch.relevance")

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
    return [str(t).strip().casefold() for t in tags if str(t).strip()]


def _best_target_match(item: Dict[str, Any]) -> Optional[tuple]:
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


def _score(value, default):
    try:
        number = float(value)
        return min(10.0, max(0.0, number)) if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


async def maybe_propose_for_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    async with target_lock(("relevance", item["id"])):
        return await _propose(item)


async def _propose(item):
    match = _best_target_match(item)
    if not match:
        return None
    target, overlap = match
    tid = target["id"]
    dedup_key = f"rel:{tid}:{item['id']}"
    if proposal_seen(dedup_key):
        return None
    item_title = redact_text(str(item.get("title_l1") or ""))[:80]
    item_summary = redact_text(str(item.get("summary_l1") or ""))[:300]
    impact, confidence, effort = 5.0, 4.0, 4.0
    proposal_type = "synergy"
    overlap_line = redact_text("、".join(sorted(overlap)))[:60]
    verdict = f"與 {target['name']} 有 {len(overlap)} 個技術標籤重疊（{overlap_line}），值得一看"
    if target["outbound_consent"].get("summary"):
        try:
            # Historical summaries can contain code/docs whose consent was revoked.
            # Only structural matching facts and the new public item are sent here.
            prompt = redact_text(
                f"新情報：{item_title}\n摘要：{item_summary}\n\n"
                f"專案名稱：{target['name']}\n重疊標籤數：{len(overlap)}"
            )
            judged = await get_primary_provider().generate_json(prompt, RELEVANCE_SYSTEM_PROMPT)
            if judged.get("relevant") is False:
                return None
            if judged.get("proposal_type") in ("synergy", "borrow", "upgrade", "monitor"):
                proposal_type = judged["proposal_type"]
            impact = _score(judged.get("impact"), impact)
            confidence = _score(judged.get("confidence"), confidence)
            effort = _score(judged.get("effort"), effort)
            if judged.get("verdict"):
                verdict = redact_text(str(judged["verdict"]))[:60]
        except Exception as exc:
            logger.warning("Cloud relevance unavailable; using local match (%s)", type(exc).__name__)
    latest = get_watch_target(tid)
    if not latest or not latest["is_active"] or any(
        latest.get(k) != target.get(k) for k in ("read_scope", "outbound_consent", "fingerprint_version", "fingerprint_item_id")
    ) or not get_item_by_id(item["id"]):
        return None
    card = {
        # New review period creates a new card rather than overwriting a decision.
        "url": f"proposal://rel/{tid}/{item['id']}/{uuid.uuid4().hex}",
        "source_type": "proposal", "origin": "proposal", "category_name": "提案",
        "title_l1": redact_text(f"🔗 提案：{item_title} ⟷ {target['name']}"),
        "summary_l1": redact_text(f"{verdict}。依據：標籤重疊（{overlap_line}）。"),
        "tech_tags": sorted(overlap)[:5],
        "deep_analysis": redact_text(
            f"### 為什麼相關\n重疊標籤：{html.escape(overlap_line)}\n\n"
            f"### 新情報\n{item_summary}\n\n"
            f"### 建議\n開啟原始情報比對 {target['name']} 的指紋卡，再決定是否驗證。"
            + ("" if target["outbound_consent"].get("summary") else "\n\n_本地比對，未啟用雲端判斷。_")
        ),
        "author": "OmniKeep 提案引擎",
    }
    return save_proposal({
        "target_id": tid, "proposal_type": proposal_type,
        "impact": impact, "confidence": confidence, "effort": effort,
        "dedup_key": dedup_key,
    }, item_data=card)
