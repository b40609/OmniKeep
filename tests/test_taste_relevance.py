import uuid
from pathlib import Path

import pytest

from app.database import (
    init_db,
    save_item,
    get_item_by_id,
    log_behavior_event,
    get_topic_weight,
    tune_topic_signal,
)
from app.watch.taste import apply_swipe_learning, rank_deck
from app.watch import relevance

_TMP = Path(__file__).parent / ".tmp"


def setup_module(module):
    init_db()


def _mk_item(origin="radar", tags=None, title=None) -> str:
    seed = uuid.uuid4().hex[:8]
    return save_item({
        "url": f"https://p2-test.example/{seed}",
        "source_type": "web",
        "category_name": "AI",
        "title_l1": title or f"P2 測試 {seed}",
        "summary_l1": "測試摘要",
        "tech_tags": tags or [],
        "origin": origin,
    })


def test_snooze_never_touches_weights():
    item_id = _mk_item(tags=["snooze-test-tag"])
    before = get_topic_weight("snooze-test-tag")
    log_behavior_event("snooze", item_id=item_id, source="telegram")
    assert apply_swipe_learning("snooze", item_id) == []
    assert get_topic_weight("snooze-test-tag") == before


def test_swipe_labels_move_topic_weights_both_directions():
    up_item = _mk_item(tags=["taste-up-tag"])
    down_item = _mk_item(tags=["taste-down-tag"])
    tune_topic_signal("taste-up-tag", "reset")
    tune_topic_signal("taste-down-tag", "reset")

    apply_swipe_learning("swipe_up", up_item)
    assert get_topic_weight("taste-up-tag") > 1.0

    apply_swipe_learning("swipe_down", down_item)
    assert get_topic_weight("taste-down-tag") < 1.0

    apply_swipe_learning("swipe_star", up_item)   # star also boosts
    assert get_topic_weight("taste-up-tag") > get_topic_weight("taste-down-tag")


def test_rank_deck_orders_and_marks_exploration():
    items = []
    for i in range(6):
        tag = f"rank-tag-{uuid.uuid4().hex[:4]}"
        if i < 4:
            tune_topic_signal(tag, "boost")
        items.append({"id": str(i), "tech_tags": [tag], "title_l1": f"item{i}"})
    ranked = rank_deck(items, exploration_ratio=0.2)
    assert len(ranked) == 6
    explore_flags = [bool(r.get("is_exploration")) for r in ranked]
    assert sum(explore_flags) == 1                       # 20% of 6 = 1 explore card
    assert explore_flags.index(True) >= 4                # explore card sits in the tail


def test_relevance_tag_matching(monkeypatch):
    fp_item = _mk_item(origin="watch", tags=["OKX", "回測", "量化", "Python"])
    hit_item = get_item_by_id(_mk_item(tags=["OKX", "回測", "無關主題"]))
    miss_item = get_item_by_id(_mk_item(tags=["食譜", "鑄鐵鍋"]))
    target = {"id": "t1", "name": "CatOS", "target_type": "folder",
              "fingerprint_item_id": fp_item, "outbound_consent": {"summary": False}}
    monkeypatch.setattr(relevance, "get_watch_targets", lambda active_only=True: [target])

    matched = relevance._best_target_match(hit_item)
    assert matched is not None and matched[0]["id"] == "t1"
    assert len(matched[1]) == 2                          # OKX + 回測
    assert relevance._best_target_match(miss_item) is None
    # L0 risk targets never match
    risk_target = dict(target, id="t2", target_type="desktop_risk",
                       fingerprint_item_id=fp_item)
    monkeypatch.setattr(relevance, "get_watch_targets",
                        lambda active_only=True: [risk_target])
    assert relevance._best_target_match(hit_item) is None


@pytest.mark.asyncio
async def test_relevance_local_only_card_created_and_deduped(monkeypatch):
    fp_item = _mk_item(origin="watch", tags=["OKX", "量化"])
    target = {"id": f"t-{uuid.uuid4().hex[:4]}", "name": "CatOS", "target_type": "folder",
              "fingerprint_item_id": fp_item,
              "outbound_consent": {"summary": False, "docs": False, "deps": False,
                                   "code": False, "git": False}}
    monkeypatch.setattr(relevance, "get_watch_targets", lambda active_only=True: [target])

    item = get_item_by_id(_mk_item(tags=["OKX", "量化", "新聞"]))
    prop = await relevance.maybe_propose_for_item(item)
    assert prop is not None
    assert prop["proposal_type"] in ("synergy", "borrow", "upgrade", "monitor")

    card = get_item_by_id(prop["item_id"])
    assert "CatOS" in card["title_l1"]
    assert "本地比對" in card["deep_analysis"]           # no-consent path marked

    dup = await relevance.maybe_propose_for_item(item)
    assert dup is None                                   # 30-day dedup
