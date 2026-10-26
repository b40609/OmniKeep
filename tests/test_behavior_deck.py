import shutil
import tempfile
import uuid
from pathlib import Path

import pytest

from app.database import (
    init_db,
    save_item,
    get_items,
    log_behavior_event,
    get_behavior_stats,
    get_swipe_deck,
    delete_item,
)
from app.bot.telegram_bot import (
    build_deck_keyboard,
    build_proposal_keyboard,
    build_deck_card_html,
)

_TMP_ROOT = Path(__file__).parent / ".tmp"


def _tmpdir() -> Path:
    _TMP_ROOT.mkdir(exist_ok=True)
    return Path(tempfile.mkdtemp(dir=str(_TMP_ROOT), prefix=f"p1-{uuid.uuid4().hex[:6]}-"))


def setup_module(module):
    init_db()


def _mk_item(origin: str, read: int = 0) -> str:
    seed = uuid.uuid4().hex[:8]
    return save_item({
        "url": f"https://behavior-fixture.invalid/{seed}",
        "source_type": "web",
        "category_name": "AI",
        "title_l1": f"P1 測試項目 {seed}",
        "summary_l1": "測試摘要",
        "tech_tags": ["測試"],
        "origin": origin,
        "is_read": read,
    })


def test_origin_field_roundtrip_and_filter():
    radar_id = _mk_item("radar")
    _mk_item("manual")
    radar_only = get_items(origin="radar", limit=50)
    assert all(i["origin"] == "radar" for i in radar_only)
    assert any(i["id"] == radar_id for i in radar_only)
    assert all(i["origin"] == "manual" for i in get_items(origin="manual", limit=50))


def test_swipe_deck_flow_labels_and_snooze():
    a, b, c = _mk_item("radar"), _mk_item("radar"), _mk_item("radar")
    manual = _mk_item("manual")
    read_radar = _mk_item("radar", read=1)

    deck = get_swipe_deck(limit=50)
    deck_ids = {i["id"] for i in deck}
    assert {a, b, c} <= deck_ids
    assert manual not in deck_ids          # origin split: radar only
    assert read_radar not in deck_ids      # already-archived radar excluded

    # 👎 on one card → labeled, leaves the deck forever
    log_behavior_event("swipe_down", item_id=a, source="telegram")
    # 💤 snooze on another → hidden for a day, but NOT a label
    log_behavior_event("snooze", item_id=b, source="telegram")

    deck_ids = {i["id"] for i in get_swipe_deck(limit=50)}
    assert a not in deck_ids and b not in deck_ids and c in deck_ids

    # stats reflect both events
    stats = get_behavior_stats(days=1)
    assert stats["by_type"].get("swipe_down", 0) >= 1
    assert stats["by_type"].get("snooze", 0) >= 1


def test_snooze_is_never_a_training_label():
    from app.database import SWIPE_LABEL_EVENTS
    assert "snooze" not in SWIPE_LABEL_EVENTS
    assert set(SWIPE_LABEL_EVENTS) == {"swipe_up", "swipe_down", "swipe_star"}


def test_telegram_deck_keyboard_and_cards():
    kb = build_deck_keyboard("abc123")
    row = kb["inline_keyboard"][0]
    assert [b["callback_data"] for b in row] == [
        "swipe_up:abc123", "swipe_star:abc123", "snooze:abc123", "swipe_down:abc123"]
    assert [b["text"] for b in row][2].startswith("💤")

    pk = build_proposal_keyboard("p1")
    assert pk["inline_keyboard"][0][0]["callback_data"] == "prop:p1:approve"

    card = build_deck_card_html({"title_l1": "<b>標題</b>", "summary_l1": "摘要",
                                 "tech_tags": ["AI", "量化"]}, 7)
    assert "剩 7 張" in card
    assert "&lt;b&gt;標題&lt;/b&gt;" in card          # HTML escaped
    assert "#AI #量化" in card


@pytest.mark.asyncio
async def test_behavior_router_endpoints():
    from fastapi.testclient import TestClient
    from app.main import app

    item_id = _mk_item("radar")
    from app.config import settings
    with TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        r = client.post("/api/behavior/event", json={
            "event_type": "swipe_up", "item_id": item_id, "source": "pwa"})
        assert r.status_code == 200 and r.json()["success"] is True

        bad = client.post("/api/behavior/event", json={"event_type": "hack_the_planet"})
        assert bad.json()["success"] is False

        deck = client.get("/api/behavior/deck").json()
        assert deck["count"] >= 0
        assert all(i["id"] != item_id for i in deck["items"])  # just swiped away

        stats = client.get("/api/behavior/stats?days=7").json()
        assert "by_type" in stats
