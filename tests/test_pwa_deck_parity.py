"""The PWA deck must mean the same thing as the Telegram /deck buttons."""
from contextlib import closing
import uuid

from fastapi.testclient import TestClient
import pytest

from app.bot.telegram_bot import build_deck_keyboard
from app.config import settings
from app.database import get_db_connection, get_item_by_id, get_swipe_deck, record_swipe, save_item
from app.main import app


def _radar_item() -> str:
    seed = uuid.uuid4().hex[:8]
    return save_item({
        "url": f"https://deck-parity.invalid/{seed}",
        "source_type": "web",
        "category_name": "AI",
        "title_l1": f"滑卡一致性 {seed}",
        "summary_l1": "測試摘要",
        "tech_tags": [f"tag-{seed}"],
        "origin": "radar",
    })


def _telegram_actions() -> list[str]:
    buttons = build_deck_keyboard("x")["inline_keyboard"][0]
    return [b["callback_data"].split(":", 1)[0] for b in buttons]


def _outcome(item_id: str) -> dict:
    item = get_item_by_id(item_id)
    with closing(get_db_connection()) as conn:
        events = [r["event_type"] for r in conn.execute(
            "SELECT event_type FROM behavior_events WHERE item_id = ?", (item_id,))]
    return {
        "is_read": item["is_read"],
        "is_starred": item["is_starred"],
        "in_deck": any(card["id"] == item_id for card in get_swipe_deck(limit=50)),
        "events": events,
    }


def test_telegram_deck_offers_the_four_pwa_actions():
    assert sorted(_telegram_actions()) == ["snooze", "swipe_down", "swipe_star", "swipe_up"]


@pytest.mark.parametrize("action", _telegram_actions())
def test_pwa_swipe_has_the_same_effect_as_telegram(action):
    via_telegram, via_pwa = _radar_item(), _radar_item()
    record_swipe(action, via_telegram, source="telegram")
    with TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        res = client.post("/api/behavior/event", json={"event_type": action, "item_id": via_pwa, "source": "pwa"})
    assert res.status_code == 200 and res.json()["success"] is True
    assert _outcome(via_pwa) == _outcome(via_telegram)
    with closing(get_db_connection()) as conn:
        source = conn.execute("SELECT source FROM behavior_events WHERE item_id = ?", (via_pwa,)).fetchone()["source"]
    assert source == "pwa"
