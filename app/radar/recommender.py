import math
from datetime import datetime, timezone
from typing import List, Dict, Any, Tuple
from app.database import (
    get_all_topic_weights,
    get_topic_weight,
    tune_topic_signal,
    get_item_by_id
)

# Half-life for topic interest decay (in days). Inactivity pulls weights back towards 1.0.
HALF_LIFE_DAYS = 14.0

def calculate_time_decay(weight: float, last_interacted_iso: str) -> float:
    """
    Applies exponential decay towards the neutral baseline (1.0).
    weight_decayed = 1.0 + (weight - 1.0) * (0.5 ** (delta_days / HALF_LIFE_DAYS))
    """
    if not last_interacted_iso:
        return weight
    try:
        last_dt = datetime.fromisoformat(last_interacted_iso.replace("Z", "+00:00"))
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        now_dt = datetime.now(timezone.utc)
        delta_days = (now_dt - last_dt).total_seconds() / 86400.0
        if delta_days <= 0:
            return weight
        decay_factor = math.pow(0.5, delta_days / HALF_LIFE_DAYS)
        decayed = 1.0 + (weight - 1.0) * decay_factor
        return round(decayed, 3)
    except Exception:
        return weight

def score_item_detailed(tags: List[str], tier: int = 2, is_exploration: bool = False) -> Dict[str, Any]:
    """
    Transparent scoring — 'numbers for the model, words for the human'.
    Returns raw dimension values (score, base, tier multiplier, per-tag weights)
    plus human-readable reason lines so every recommendation can answer 為什麼給我看.
    """
    tag_weights: Dict[str, float] = {}
    reasons: List[str] = []
    blocked_tag = None
    scores = []
    for t in tags:
        w = get_topic_weight(t)
        tag_weights[t] = w
        if w <= -100.0:
            if blocked_tag is None:
                blocked_tag = t
        else:
            scores.append(w)

    if blocked_tag:
        reasons.append(f"🔇 命中靜音標籤「{blocked_tag}」")
        base_score = -999.0
    else:
        # Max + average hybrid to emphasize high-interest tags without over-inflating long lists
        base_score = 0.6 * max(scores) + 0.4 * (sum(scores) / len(scores)) if scores else 1.0
        hot = sorted(((t, w) for t, w in tag_weights.items() if w > 1.0), key=lambda x: -x[1])[:2]
        for t, w in hot:
            reasons.append(f"🏷️ 你對「{t}」的權重 {w:g}")

    tier_multipliers = {1: 1.25, 2: 1.0, 3: 0.75}
    tier_mult = tier_multipliers.get(tier, 1.0)
    if blocked_tag:
        final_score = -999.0
    else:
        final_score = round(base_score * tier_mult, 3)

    if tier == 1:
        reasons.append("📡 Tier 1 官方來源 ×1.25")
    elif tier == 3:
        reasons.append("📊 Tier 3 聚合來源 ×0.75")
    if is_exploration:
        reasons.append("🧭 探索卡（避免同溫層）")
    if not reasons:
        reasons.append("🆕 尚無互動訊號，預設權重")

    return {
        "score": final_score,
        "blocked": blocked_tag is not None,
        "base_score": base_score,
        "tier_mult": tier_mult,
        "tag_weights": tag_weights,
        "reasons": reasons,
    }

def score_item(tags: List[str], tier: int = 2) -> Tuple[float, bool]:
    """
    Scores an incoming or existing item based on user topic weights and source tier.
    Returns: (final_score, is_blocked)
    """
    detail = score_item_detailed(tags, tier)
    return detail["score"], detail["blocked"]

def rank_items_with_exploration(items: List[Dict[str, Any]], exploration_ratio: float = 0.2) -> List[Dict[str, Any]]:
    """
    Applies 80/20 Epsilon-Greedy exploration to avoid filter bubbles.
    - (1 - exploration_ratio): Top scored items (Exploitation)
    - exploration_ratio: Novel / emerging items with good base quality (Exploration)
    """
    if not items:
        return []

    scored_items = []
    for it in items:
        tags = it.get("tech_tags") or []
        tier = it.get("tier", 2)
        detail = score_item_detailed(tags, tier)
        if not detail["blocked"] and detail["score"] >= 0.5:
            it_copy = dict(it)
            it_copy["radar_score"] = detail["score"]
            it_copy["reasons"] = detail["reasons"]
            scored_items.append(it_copy)

    # Sort descending by radar score
    scored_items.sort(key=lambda x: x["radar_score"], reverse=True)

    n_total = len(scored_items)
    n_explore = int(n_total * exploration_ratio)
    n_exploit = n_total - n_explore

    top_exploit = scored_items[:n_exploit]
    rest_pool = scored_items[n_exploit:]

    # Pick exploratory items that introduce novel tags
    # Interleave 4 exploit items with 1 explore item
    result = []
    exploit_idx = 0
    explore_idx = 0

    while exploit_idx < len(top_exploit) or explore_idx < len(rest_pool):
        # Take up to 4 exploit
        for _ in range(4):
            if exploit_idx < len(top_exploit):
                result.append(top_exploit[exploit_idx])
                exploit_idx += 1
        # Take 1 explore
        if explore_idx < len(rest_pool):
            item = rest_pool[explore_idx]
            item["is_exploration"] = True
            item["reasons"] = (item.get("reasons") or []) + ["🧭 探索卡（避免同溫層）"]
            result.append(item)
            explore_idx += 1

    return result

def tune_item_signal(item_id: str, action: str) -> Dict[str, Any]:
    """
    Batch tune all tags in a specific item:
    action: 'boost', 'dampen', 'mute', or 'reset'
    """
    item = get_item_by_id(item_id)
    if not item:
        raise ValueError(f"Item not found: {item_id}")

    tags = item.get("tech_tags") or []
    results = []
    for tag in tags:
        res = tune_topic_signal(tag, action)
        results.append(res)

    return {
        "item_id": item_id,
        "action": action,
        "affected_tags": results
    }
