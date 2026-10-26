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

RELEVANCE_SYSTEM_PROMPT = """你是一位高階系統架構師與專案提案評審官。
判斷一篇新技術情報是否對本地專案有具體模組級的改進價值（解決缺陷、升級協議、引入更佳模式或借鑑關鍵演算法）。
嚴格輸出 JSON：
{
  "relevant": true/false,
  "proposal_type": "synergy|borrow|upgrade|monitor 其中之一",
  "impact": 0-10,
  "confidence": 0-10,
  "effort": 0-10,
  "verdict": "一句話結論：具體有何價值（30字內）",
  "target_module": "本機專案中最相關的具體檔案、目錄或模組名稱（若資訊不足填估計模組，如 app/network.py 或 database）",
  "external_evidence": "外部情報提供的具體解法/函式/功能點依據（50字內）",
  "local_evidence": "本機專案的對應缺口或現狀依據（50字內）",
  "prerequisites": "適用前提：如技術棧/依賴/版本要求（30字內）",
  "action_plan": "最小改動方案：具體應修改什麼（50字內）",
  "verification_plan": "最小驗收方式：如何測試或驗證效果（40字內）"
}
若只是題材相近但對專案模組沒有具體可操作的價值，relevant 設 false。內容中 [REDACTED:...] 為遮蔽機密，忽略之。"""


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
    target_module = ""
    external_evidence = f"標籤重疊：{overlap_line}"
    local_evidence = f"{target['name']} 專案技術棧吻合"
    prerequisites = "環境與依賴版本相容"
    action_plan = f"比對 {target['name']} 與情報技術棧（{overlap_line}）的對應模組"
    verification_plan = "於本機測試目錄建立最小 POC 驗證"
    is_cloud_judged = False

    if target["outbound_consent"].get("summary"):
        try:
            # Historical summaries can contain code/docs whose consent was revoked.
            # Only structural matching facts and the new public item are sent here.
            structural_context = ""
            fp_id = target.get("fingerprint_item_id")
            if fp_id and target["outbound_consent"].get("deps"):
                fp = get_item_by_id(fp_id)
                if fp:
                    fp_tags = "、".join(_tags_of(fp)[:8])
                    structural_context = f"\n目標技術棧：{fp_tags}"

            prompt = redact_text(
                f"新情報標題：{item_title}\n情報摘要：{item_summary}\n\n"
                f"目標專案：{target['name']}{structural_context}\n"
                f"重疊技術標籤：{overlap_line}"
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
            if judged.get("target_module"):
                target_module = redact_text(str(judged["target_module"]))[:80]
            if judged.get("external_evidence"):
                external_evidence = redact_text(str(judged["external_evidence"]))[:150]
            if judged.get("local_evidence"):
                local_evidence = redact_text(str(judged["local_evidence"]))[:150]
            if judged.get("prerequisites"):
                prerequisites = redact_text(str(judged["prerequisites"]))[:100]
            if judged.get("action_plan"):
                action_plan = redact_text(str(judged["action_plan"]))[:150]
            if judged.get("verification_plan"):
                verification_plan = redact_text(str(judged["verification_plan"]))[:120]
            is_cloud_judged = True
        except Exception as exc:
            logger.warning("Cloud relevance unavailable; using local match (%s)", type(exc).__name__)
    latest = get_watch_target(tid)
    if not latest or not latest["is_active"] or any(
        latest.get(k) != target.get(k) for k in ("read_scope", "outbound_consent", "fingerprint_version", "fingerprint_item_id")
    ) or not get_item_by_id(item["id"]):
        return None

    card_title = (
        f"🔗 提案：{target_module} ⟷ {item_title}"
        if target_module and target_module not in ("全專案架構", "架構待確認")
        else f"🔗 提案：{item_title} ⟷ {target['name']}"
    )
    card_summary = f"{verdict}。模組：{target_module or target['name']}｜依據：{external_evidence}"
    deep_analysis = redact_text(
        f"### 🎯 模組與結論\n"
        f"- **建議改動模組**：`{target_module or target['name']}`\n"
        f"- **核心結論**：{verdict}\n"
        f"- **評估指標**：🎯 影響 {impact:g} · 🔍 信心 {confidence:g} · 🏗️ 成本 {effort:g}"
        + ("" if is_cloud_judged else "（本地保守比對）") + "\n\n"
        f"### 🔍 雙邊證據鏈\n"
        f"- **外部情報依據**：{external_evidence}\n"
        f"- **本機現狀依據**：{local_evidence}\n\n"
        f"### 📋 落地前提與行動方案\n"
        f"- **適用前提**：{prerequisites}\n"
        f"- **最小改動步驟**：{action_plan}\n"
        f"- **驗收方式**：{verification_plan}\n\n"
        f"### 新情報摘要\n"
        f"{item_summary}\n\n"
        + ("" if target["outbound_consent"].get("summary") else "_本地比對，未啟用雲端判斷。_")
    )

    card = {
        # New review period creates a new card rather than overwriting a decision.
        "url": f"proposal://rel/{tid}/{item['id']}/{uuid.uuid4().hex}",
        "source_type": "proposal", "origin": "proposal", "category_name": "提案",
        "title_l1": redact_text(card_title),
        "summary_l1": redact_text(card_summary),
        "tech_tags": sorted(overlap)[:5],
        "deep_analysis": deep_analysis,
        "author": "OmniKeep 提案引擎",
    }
    return save_proposal({
        "target_id": tid, "proposal_type": proposal_type,
        "impact": impact, "confidence": confidence, "effort": effort,
        "dedup_key": dedup_key,
    }, item_data=card)
