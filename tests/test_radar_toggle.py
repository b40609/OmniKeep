"""The radar settings toggle alone decides background scans, and takes effect without a restart."""
import asyncio
from contextlib import closing
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
import httpx
import pytest

from app.config import settings
from app.database import get_db_connection, get_radar_settings, init_db, update_radar_settings
from app.main import app
from app.radar import scheduler as scheduler_module
from app.radar.scheduler import radar_scheduler

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}

# radar_settings as releases before this change created it.
OLD_SCHEMA = """
    CREATE TABLE radar_settings (
        id INTEGER PRIMARY KEY CHECK (id = 1), enabled INTEGER DEFAULT 1,
        interval_minutes INTEGER DEFAULT 180, max_analyze_per_cycle INTEGER DEFAULT 3,
        notification_mode TEXT DEFAULT 'silent', daily_digest_hour INTEGER DEFAULT 8,
        vip_threshold REAL DEFAULT 4.0, auto_digest_push INTEGER DEFAULT 0,
        auto_star_push INTEGER DEFAULT 0, updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)
"""


def _old_database(toggle_on):
    with closing(get_db_connection()) as conn, conn:
        conn.execute("DROP TABLE radar_settings")
        conn.execute(OLD_SCHEMA)
        conn.execute("INSERT INTO radar_settings (id, enabled) VALUES (1, ?)", (int(toggle_on),))


@pytest.mark.parametrize("toggle_on, env_on, expected", [
    (True, False, False),  # the bug: the toggle said on while nothing ran; it now says off
    (True, True, True),    # scans really ran; they keep running
    (False, True, False),
    (False, False, False),
])
def test_upgrade_keeps_the_state_that_actually_took_effect(monkeypatch, toggle_on, env_on, expected):
    _old_database(toggle_on)
    monkeypatch.setattr(settings, "RADAR_ENABLED", env_on)
    init_db()
    assert get_radar_settings()["enabled"] is expected


def test_after_the_upgrade_only_the_toggle_counts(monkeypatch):
    _old_database(True)
    monkeypatch.setattr(settings, "RADAR_ENABLED", True)
    init_db()
    update_radar_settings(enabled=False)  # switched off in the UI; .env still says true
    init_db()                              # restart
    assert get_radar_settings()["enabled"] is False
    update_radar_settings(enabled=True)
    monkeypatch.setattr(settings, "RADAR_ENABLED", False)
    init_db()
    assert get_radar_settings()["enabled"] is True


def test_settings_report_whether_the_scheduler_runs():
    # Background services are off in tests, so nothing would honour the toggle: say so.
    with TestClient(app) as client:
        assert client.get("/api/radar/settings", headers=HEADERS).json()["settings"]["scheduler_running"] is False


async def _until(condition, timeout=3.0):
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


@pytest.mark.asyncio
async def test_toggle_starts_and_stops_scans_on_a_running_scheduler(monkeypatch):
    cycles = AsyncMock(return_value={"new_items_count": 0, "sources_scanned": 0})
    monkeypatch.setattr(scheduler_module, "run_radar_cycle", cycles)
    radar_scheduler.start(initial_delay=0)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test",
                                     headers=HEADERS) as client:
            await asyncio.sleep(0.3)
            assert cycles.await_count == 0  # running, but switched off: no scans

            res = await client.put("/api/radar/settings", json={"enabled": True, "interval_minutes": 180})
            assert res.json()["settings"]["enabled"] is True
            assert res.json()["settings"]["scheduler_running"] is True
            await _until(lambda: cycles.await_count == 1)  # saving wakes it: scans right away

            await client.put("/api/radar/settings", json={"enabled": False})
            await asyncio.sleep(0.3)
            assert cycles.await_count == 1  # woken again, but off: no further scan
    finally:
        await radar_scheduler.stop()
