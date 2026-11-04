"""/api/behavior/deck serves two decks: by default the radar swipe deck (the PWA
DeckDialog and Telegram /deck), with mode=daily the daily review deck."""
import uuid

from fastapi.testclient import TestClient

from app.config import settings
from app.database import init_db, save_item


def _mk(origin: str) -> str:
    seed = uuid.uuid4().hex[:8]
    return save_item({
        "url": f"https://deck-mode.invalid/{seed}",
        "source_type": "web",
        "category_name": "AI",
        "title_l1": f"牌組測試 {seed}",
        "summary_l1": "摘要",
        "tech_tags": ["測試"],
        "origin": origin,
        "is_read": 0,
    })


def test_default_deck_is_radar_and_daily_is_opt_in():
    init_db()
    radar_id = _mk("radar")
    manual_id = _mk("manual")
    from app.main import app

    with TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        radar = {i["id"] for i in client.get("/api/behavior/deck?limit=50").json()["items"]}
        explicit = {i["id"] for i in client.get("/api/behavior/deck?mode=radar&limit=50").json()["items"]}
        daily = {i["id"] for i in client.get("/api/behavior/deck?mode=daily&limit=50").json()["items"]}

    assert radar_id in radar and manual_id not in radar
    assert explicit == radar
    assert manual_id in daily
