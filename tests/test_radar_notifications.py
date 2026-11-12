"""Radar notifications: the daily digest keeps its hour, vip_alert sends what reached the
threshold, and LINE receives the same notices as Telegram and Web Push."""
import asyncio
from contextlib import closing
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.database import get_db_connection, save_item, save_radar_digest, update_radar_settings
from app.radar import scheduler


def _local(hour, minute=0, days=0):
    base = datetime.now().astimezone() + timedelta(days=days)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _set_times(item_id, *, created=None, updated=None):
    with closing(get_db_connection()) as conn, conn:
        if created:
            conn.execute("UPDATE items SET created_at = ? WHERE id = ?",
                         (created.astimezone(timezone.utc).isoformat(), item_id))
        if updated:
            conn.execute("UPDATE items SET updated_at = ? WHERE id = ?",
                         (updated.astimezone(timezone.utc).isoformat(), item_id))


def _radar_item(slug, *, status="done", origin="radar", updated=None):
    item_id = save_item({"url": f"https://example.com/{slug}", "title_l1": slug, "summary_l1": "提要",
                         "tech_tags": ["Rust"], "origin": origin, "analysis_status": status})
    _set_times(item_id, updated=updated)
    return item_id


async def _until(condition, timeout=3.0):
    for _ in range(int(timeout / 0.05)):
        if condition():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met in time")


# ── When the daily digest is due ─────────────────────────────

def test_slot_opens_at_the_hour_and_closes_after_the_grace_period():
    assert not scheduler.daily_digest_due(_local(7, 59), 8, None)
    assert scheduler.daily_digest_due(_local(8, 0), 8, None)
    assert scheduler.daily_digest_due(_local(10, 59), 8, None)  # machine woke up late: still sends
    assert not scheduler.daily_digest_due(_local(11, 0), 8, None)


def test_slot_is_used_once_per_day():
    assert not scheduler.daily_digest_due(_local(9, 0), 8, last_sent=_local(8, 1))
    assert scheduler.daily_digest_due(_local(9, 0), 8, last_sent=_local(8, 1, days=-1))


def test_late_evening_slot_stays_open_past_midnight():
    assert scheduler.daily_digest_due(_local(0, 30), 23, None)
    assert not scheduler.daily_digest_due(_local(0, 30), 23, last_sent=_local(23, 5, days=-1))
    assert not scheduler.daily_digest_due(_local(2, 0), 23, None)


# ── What the daily digest sends ──────────────────────────────

@pytest.fixture
def daily_digest(monkeypatch):
    """Daily mode at the current hour; the LLM write-up and the outlets are stubbed."""
    now = datetime.now().astimezone()
    update_radar_settings(enabled=True, notification_mode="daily_digest", daily_digest_hour=now.hour)
    made = []

    async def fake_generate(item_ids, digest_type="evening"):
        made.append((list(item_ids), digest_type))
        digest_id = save_radar_digest({"title": "每日探索精選", "digest_type": digest_type,
                                       "markdown_content": "摘要", "item_ids": item_ids})
        return {"success": True, "digest_id": digest_id, "title": "每日探索精選"}

    announced = AsyncMock()
    monkeypatch.setattr(scheduler, "generate_radar_digest", fake_generate)
    monkeypatch.setattr(scheduler, "_announce_digest", announced)
    return now, made, announced


async def test_digest_is_sent_once_in_the_chosen_hour(daily_digest):
    now, made, announced = daily_digest
    first, second = _radar_item("a"), _radar_item("b")

    res = await scheduler.maybe_send_daily_digest(now=now)

    assert res["success"] is True
    assert sorted(made[0][0]) == sorted([first, second]) and made[0][1] == "daily"
    announced.assert_awaited_once()
    assert await scheduler.maybe_send_daily_digest(now=now + timedelta(minutes=1)) is None
    assert len(made) == 1


async def test_digest_covers_what_was_analyzed_since_the_last_daily_digest(daily_digest):
    now, made, _ = daily_digest
    covered = _radar_item("covered", updated=now - timedelta(hours=2))
    last = save_radar_digest({"title": "昨天", "digest_type": "daily", "markdown_content": "x",
                              "item_ids": [covered]})
    with closing(get_db_connection()) as conn, conn:
        conn.execute("UPDATE radar_digests SET created_at = ? WHERE id = ?",
                     ((now - timedelta(days=1)).astimezone(timezone.utc).isoformat(), last))
    _radar_item("stale", updated=now - timedelta(days=2))        # before the last digest
    fresh = _radar_item("fresh", updated=now - timedelta(hours=1))
    backfilled = _radar_item("backfilled")                       # stub saved long ago, analyzed just now
    _set_times(backfilled, created=now - timedelta(days=3), updated=now - timedelta(minutes=30))
    _radar_item("pending", status="pending")                     # not analyzed yet
    _radar_item("manual", origin="manual")                       # not a radar item

    await scheduler.maybe_send_daily_digest(now=now)

    assert sorted(made[0][0]) == sorted([fresh, backfilled])


async def test_no_digest_without_new_items_or_outside_daily_mode(daily_digest):
    now, made, announced = daily_digest
    assert await scheduler.maybe_send_daily_digest(now=now) is None  # nothing new

    _radar_item("a")
    update_radar_settings(notification_mode="silent")
    assert await scheduler.maybe_send_daily_digest(now=now) is None
    update_radar_settings(notification_mode="daily_digest", enabled=False)
    assert await scheduler.maybe_send_daily_digest(now=now) is None
    assert made == [] and announced.await_count == 0


async def test_scan_cycle_in_daily_mode_hands_off_to_the_digest_gate(monkeypatch):
    update_radar_settings(enabled=True, notification_mode="daily_digest")
    gate = AsyncMock(return_value=None)
    monkeypatch.setattr(scheduler, "maybe_send_daily_digest", gate)

    await scheduler.run_radar_cycle(force=True, auto_digest=False)
    gate.assert_not_awaited()
    await scheduler.run_radar_cycle(force=True, auto_digest=True)
    gate.assert_awaited_once()


async def test_running_scheduler_checks_the_digest_without_any_scan(monkeypatch):
    checks = AsyncMock(return_value=None)
    cycles = AsyncMock(return_value={"new_items_count": 0, "sources_scanned": 0})
    monkeypatch.setattr(scheduler, "maybe_send_daily_digest", checks)
    monkeypatch.setattr(scheduler, "run_radar_cycle", cycles)
    scheduler.radar_scheduler.start(initial_delay=0)
    try:
        await _until(lambda: checks.await_count >= 1)
        assert cycles.await_count == 0  # radar switched off: no scans, the digest check still runs
    finally:
        await scheduler.radar_scheduler.stop()


# ── vip_alert ─────────────────────────────────────────────────

async def test_vip_alert_sends_items_over_the_threshold_without_auto_star(monkeypatch):
    update_radar_settings(enabled=True, notification_mode="vip_alert", vip_threshold=1.0)
    found = [{"id": "vip", "title_l1": "高分項目", "tech_tags": ["Rust"]}]  # never auto-starred
    monkeypatch.setattr(scheduler, "_backfill_pending", AsyncMock(return_value=found))
    monkeypatch.setattr("app.background.follow_up_pool.submit", lambda factory: True)
    announced = AsyncMock()
    monkeypatch.setattr(scheduler, "_announce_vip", announced)

    await scheduler.run_radar_cycle(force=True)

    assert [it["title_l1"] for it in announced.await_args.args[0]] == ["高分項目"]


# ── Outlets: Telegram, Web Push, LINE ────────────────────────

class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


@pytest.fixture
def outlets(monkeypatch):
    pushed, line = [], []

    async def fake_send_push(title, body, url="/", tag=None, ttl=0):
        pushed.append({"title": title, "body": body, "tag": tag})
        return {"sent": 1, "removed": 0, "failed": 0}

    async def fake_line_push(user_id, messages):
        if user_id == "U_broken":
            raise RuntimeError("LINE said no")
        line.append((user_id, messages))
        return {}

    bot = FakeBot()
    monkeypatch.setattr(scheduler, "send_push", fake_send_push)
    monkeypatch.setattr("app.bot.telegram_bot.get_telegram_bot", lambda: bot)
    monkeypatch.setattr("app.bot.line_bot.push_line_messages", fake_line_push)
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", "42")
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "test-line-token")
    monkeypatch.setattr(settings, "LINE_ALLOWED_USER_IDS_RAW", "U_broken,U_owner")
    return pushed, bot, line


async def test_vip_items_reach_every_outlet(outlets):
    pushed, bot, line = outlets
    await scheduler._announce_vip([{"title_l1": "高分一"}, {"title_l1": "高分二"}])

    assert pushed == [{"title": "探索的重要內容", "body": "• 高分一\n• 高分二", "tag": "radar-vip"}]
    assert len(bot.sent) == 1 and "探索的重要內容" in bot.sent[0][1]
    assert line == [("U_owner", [{"type": "text", "text": "探索的重要內容\n\n• 高分一\n• 高分二"}])]


async def test_digest_reaches_line_and_a_failing_recipient_does_not_block_others(outlets):
    _, _, line = outlets
    ranked = [{"title_l1": "Rust 年度回顧"}, {"title_l1": "SQLite 向量檢索"}]

    await scheduler._announce_digest({"success": True, "title": "每日探索精選"}, ranked)

    assert [user for user, _ in line] == ["U_owner"]
    text = line[0][1][0]["text"]
    assert text.startswith("📰 每日探索精選") and "• Rust 年度回顧\n• SQLite 向量檢索" in text


async def test_line_stays_silent_until_it_is_set_up(outlets, monkeypatch):
    _, _, line = outlets
    monkeypatch.setattr(settings, "LINE_CHANNEL_ACCESS_TOKEN", "")

    await scheduler._announce_digest({"success": True, "title": "每日探索精選"}, [{"title_l1": "a"}])
    await scheduler._announce_autostar([{"title_l1": "收藏", "auto_starred": True}])

    assert line == []
