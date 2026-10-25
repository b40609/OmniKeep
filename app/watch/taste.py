"""Taste learning — bridges P1 swipe labels to the radar topic-weight engine.

The radar recommender (app/radar/recommender.py) already maintains decayed
topic weights (14-day half-life) with ε-greedy exploration. Instead of a
second, parallel scoring system this module reuses that one:

  1. apply_swipe_learning — 👍/⭐ boost the item's tags, 👎 dampens them.
     💤 snooze (and everything else) never touches weights: "跳過≠不喜歡".
  2. rank_deck — orders the swipe deck by the same weights, marking the
     exploration slice with is_exploration using the same 4:1 interleave
     cadence as the radar list. Blocked (muted) items sink to the end but
     are never dropped: the deck must eventually surface everything.
"""
from typing import Any, Dict, List

from app.database import get_item_by_id, tune_topic_signal
from app.radar.recommender import score_item

# Only true labels teach the weights. snooze is deliberately absent.
SWIPE_ACTION_MAP = {
    "swipe_up": "boost",
    "swipe_star": "boost",
    "swipe_down": "dampen",
}


def apply_swipe_learning(event_type: str, item_id: str) -> List[Dict[str, Any]]:
    """Feed one swipe label into the topic-weight engine. Returns tuned tags."""
    action = SWIPE_ACTION_MAP.get(event_type)
    if not action:
        return []
    item = get_item_by_id(item_id)
    if not item:
        return []
    return [tune_topic_signal(tag, action) for tag in (item.get("tech_tags") or [])]


def rank_deck(items: List[Dict[str, Any]], exploration_ratio: float = 0.2) -> List[Dict[str, Any]]:
    """Order un-acted deck items: taste first, with a labeled exploration slice."""
    enriched = []
    for it in items:
        score, blocked = score_item(it.get("tech_tags") or [])
        copy = dict(it)
        copy["deck_score"] = -999.0 if blocked else score
        copy["is_exploration"] = False
        enriched.append(copy)
    enriched.sort(key=lambda x: x["deck_score"], reverse=True)

    n_explore = int(len(enriched) * exploration_ratio)
    if n_explore <= 0 or len(enriched) <= 3:
        return enriched

    top, rest = enriched[:-n_explore], enriched[-n_explore:]
    result: List[Dict[str, Any]] = []
    while top or rest:
        result.extend(top[:4])
        top = top[4:]
        if rest:
            card = rest.pop(0)
            card["is_exploration"] = True
            result.append(card)
    return result
