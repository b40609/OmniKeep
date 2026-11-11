"""Radar digests: the daily one has its own title, a failed write-up is neither stored nor
announced and is tried again, and the settings API refuses values the scheduler cannot use."""
import logging
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import get_latest_radar_digests, get_radar_settings, save_item, update_radar_settings
from app.radar import digest, scheduler


class FakeLLM:
    def __init__(self, outcome):
        self.outcome, self.calls = outcome, 0

    async def generate_text(self, prompt, system_prompt=None):
        self.calls += 1
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _item(slug):
    return save_item({"url": f"https://example.com/{slug}", "title_l1": slug, "summary_l1": "提要",
                      "tech_tags": ["Rust"], "origin": "radar", "analysis_status": "done"})


@pytest.fixture
def llm(monkeypatch):
    fake = FakeLLM("# 今日重點\n- 一則")
    monkeypatch.setattr(digest, "radar_provider", lambda: fake)
    return fake


# ── Writing a digest ─────────────────────────────────────────

async def test_the_daily_digest_has_its_own_title(llm):
    made = await digest.generate_radar_digest([_item("a")], digest_type="daily")

    assert made["success"] is True and "每日摘要" in made["title"] and "焦點戰報" not in made["title"]
    stored = get_latest_radar_digests(limit=5)
    assert [d["digest_type"] for d in stored] == ["daily"] and stored[0]["title"] == made["title"]


@pytest.mark.parametrize("outcome", [RuntimeError("provider is down"), "", "   \n"])
async def test_a_failed_write_up_is_not_stored(llm, caplog, outcome):
    llm.outcome = outcome

    with caplog.at_level(logging.WARNING, logger="omnikeep.radar.digest"):
        made = await digest.generate_radar_digest([_item("a")], digest_type="daily")

    assert made["success"] is False and made["message"].startswith("摘要產生失敗")
    assert "digest_id" not in made and get_latest_radar_digests(limit=5) == []
    assert any("was not written" in r.getMessage() for r in caplog.records)


# ── The daily slot after a failure ───────────────────────────

@pytest.fixture
def daily(monkeypatch, llm):
    now = datetime.now().astimezone()
    update_radar_settings(enabled=True, notification_mode="daily_digest", daily_digest_hour=now.hour)
    monkeypatch.setattr(scheduler, "_daily_digest_retry_at", None)
    pushed = AsyncMock()
    monkeypatch.setattr(scheduler, "send_push", pushed)
    monkeypatch.setattr("app.bot.telegram_bot.get_telegram_bot", lambda: None)
    _item("a"), _item("b")
    return now, pushed


async def test_a_failed_daily_digest_is_not_pushed_and_is_tried_again(daily, llm):
    now, pushed = daily
    llm.outcome = RuntimeError("provider is down")

    failed = await scheduler.maybe_send_daily_digest(now=now)
    assert failed["success"] is False
    assert pushed.await_count == 0 and get_latest_radar_digests(limit=5) == []

    # The next minute's check waits instead of asking the model again right away ...
    assert await scheduler.maybe_send_daily_digest(now=now + timedelta(minutes=1)) is None
    assert llm.calls == 1

    # ... and once the wait is over the same slot is still open.
    llm.outcome = "# 今日重點\n- 一則"
    later = now + timedelta(minutes=scheduler.DAILY_DIGEST_RETRY_MINUTES)
    sent = await scheduler.maybe_send_daily_digest(now=later)
    assert sent["success"] is True and llm.calls == 2
    assert pushed.await_count == 1 and "每日摘要" in pushed.await_args.args[0]
    assert len(get_latest_radar_digests(limit=5)) == 1
    assert await scheduler.maybe_send_daily_digest(now=later + timedelta(minutes=1)) is None  # once a day


async def test_a_failed_digest_in_a_scan_cycle_does_not_break_the_cycle(monkeypatch, llm):
    llm.outcome = RuntimeError("provider is down")
    cfg = {"max_analyze_per_cycle": 3, "notification_mode": "legacy", "auto_digest_push": True}
    found = [{"id": _item("a"), "tech_tags": ["Rust"], "title_l1": "a"},
             {"id": _item("b"), "tech_tags": ["Rust"], "title_l1": "b"}]
    pushed = AsyncMock()
    monkeypatch.setattr(scheduler, "get_radar_settings", lambda: cfg)
    monkeypatch.setattr(scheduler, "_backfill_pending", AsyncMock(return_value=found))
    monkeypatch.setattr(scheduler, "send_push", pushed)
    monkeypatch.setattr("app.bot.telegram_bot.get_telegram_bot", lambda: None)
    monkeypatch.setattr("app.background.follow_up_pool.submit", lambda factory: True)

    result = await scheduler.run_radar_cycle(force=True)

    assert result["new_items_count"] == 2 and result["digest"]["success"] is False
    assert pushed.await_count == 0 and get_latest_radar_digests(limit=5) == []


async def test_an_out_of_range_hour_already_stored_no_longer_raises(daily):
    now, _ = daily
    update_radar_settings(daily_digest_hour=24)  # written before the API checked the range

    assert await scheduler.maybe_send_daily_digest(now=now.replace(hour=12, minute=0)) is None  # 24 reads as 0
    sent = await scheduler.maybe_send_daily_digest(now=now.replace(hour=0, minute=5))
    assert sent["success"] is True


# ── Settings API ranges ──────────────────────────────────────

@pytest.mark.parametrize("body", [
    {"daily_digest_hour": 24},
    {"daily_digest_hour": -1},
    {"interval_minutes": -5},
    {"interval_minutes": 10081},
    {"max_analyze_per_cycle": 0},
    {"max_analyze_per_cycle": 51},
    {"vip_threshold": -0.5},
    {"vip_threshold": 13},
])
async def test_settings_out_of_range_are_refused_and_nothing_is_saved(body):
    from app.main import app
    before = get_radar_settings()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        res = await client.put("/api/radar/settings", json={"enabled": True, **body})
    assert res.status_code == 400 and next(iter(body)) in res.json()["detail"]
    assert get_radar_settings() == before


async def test_settings_at_the_edges_are_accepted():
    from app.main import app
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                           headers={"Authorization": f"Bearer {settings.API_KEY}"}) as client:
        for body in ({"daily_digest_hour": 0, "interval_minutes": 0, "max_analyze_per_cycle": 1, "vip_threshold": 0},
                     {"daily_digest_hour": 23, "interval_minutes": 10080, "max_analyze_per_cycle": 50,
                      "vip_threshold": 12.5}):
            res = await client.put("/api/radar/settings", json=body)
            assert res.status_code == 200, res.text
            saved = res.json()["settings"]
            assert {k: saved[k] for k in body} == body
