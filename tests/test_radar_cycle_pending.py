"""A scan cycle analyzes each page at most once and never turns a stored item back into an
empty pending stub. The backfill and the candidate list used to overlap: a stub analyzed by
the backfill was a candidate of the same cycle, so it was analyzed again or, with the budget
used up, written back as a stub."""
from contextlib import closing
from types import SimpleNamespace

import pytest

from app.database import (
    get_db_connection,
    get_item_by_id,
    get_pending_analysis_items,
    save_item,
    tune_topic_signal,
    update_radar_settings,
)
from app.radar import scheduler
from app.radar.adapters.base import RawFeedItem


def _raw(slug, title=None, url=None):
    return RawFeedItem(url=url or f"https://example.com/{slug}", title=title or f"Headline {slug}",
                       content=f"Feed text of {slug}", source_id="s1", source_type="rss")


def _row(item_id):
    with closing(get_db_connection()) as conn:
        row = conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def _status(raw):
    with closing(get_db_connection()) as conn:
        rows = conn.execute("SELECT analysis_status, summary_l1 FROM items WHERE url = ?", (raw.url,)).fetchall()
    assert len(rows) == 1, f"{raw.url}: {len(rows)} rows"
    return rows[0]["analysis_status"], rows[0]["summary_l1"]


@pytest.fixture
def radar(monkeypatch):
    """One source that lists the same items every cycle (a trending page does). run_pipeline is
    replaced by a stand-in that stores an analyzed item the way the real one does."""
    state = SimpleNamespace(raws=[], analyzed=[], failing=set())

    class Adapter:
        async def fetch_latest(self, src):
            return list(state.raws)

    async def fake_pipeline(content_input, manual_category=None, origin="manual", **kwargs):
        state.analyzed.append(content_input)
        if content_input in state.failing:
            raise RuntimeError("the page could not be analyzed")
        record = {"url": content_input, "title_l1": f"已分析 {content_input}", "summary_l1": "分析後的摘要",
                  "tech_tags": ["Rust"], "deep_analysis": "深度分析", "content_raw": "全文", "origin": origin}
        record["id"] = save_item(record)
        return record

    async def run(budget):
        update_radar_settings(max_analyze_per_cycle=budget, notification_mode="silent")
        state.analyzed.clear()
        return await scheduler.run_radar_cycle(force=True, auto_digest=False)

    monkeypatch.setattr(scheduler, "get_all_radar_sources",
                        lambda only_active=False: [{"id": "s1", "name": "feed", "source_type": "rss", "tier": 2}])
    monkeypatch.setattr(scheduler, "get_adapter", lambda source_type: Adapter())
    monkeypatch.setattr(scheduler, "run_pipeline", fake_pipeline)
    monkeypatch.setattr("app.background.follow_up_pool.submit", lambda factory: True)
    state.run = run
    return state


# ── The backlog drains: one analysis per page ────────────────

async def test_a_source_that_repeats_its_items_is_worked_off_once_each(radar):
    radar.raws = [_raw(f"r{i}") for i in range(1, 6)]
    urls = [raw.url for raw in radar.raws]

    first = await radar.run(budget=2)
    assert radar.analyzed == urls[:2]
    assert first["new_items_count"] == 2 and first["deferred_count"] == 3
    assert [it["url"] for it in get_pending_analysis_items(10)] == urls[2:]

    second = await radar.run(budget=2)
    assert radar.analyzed == urls[2:4]  # the backfill; not again as candidates
    assert second["new_items_count"] == 2 and second["deferred_count"] == 1
    for raw in radar.raws[:4]:
        assert _status(raw) == ("done", "分析後的摘要")  # not written back as a stub
    assert _status(radar.raws[4])[0] == "pending"

    third = await radar.run(budget=2)
    assert radar.analyzed == urls[4:]
    assert third["new_items_count"] == 1 and third["deferred_count"] == 0

    fourth = await radar.run(budget=2)
    assert radar.analyzed == [] and fourth["new_items_count"] == 0
    assert get_pending_analysis_items(10) == []
    for raw in radar.raws:
        assert _status(raw) == ("done", "分析後的摘要")


async def test_with_budget_left_a_backfilled_stub_is_not_analyzed_a_second_time(radar):
    waiting, fresh = _raw("waiting"), _raw("fresh")
    scheduler._save_deferred_stub(waiting)
    radar.raws = [waiting, fresh]

    result = await radar.run(budget=5)

    assert radar.analyzed == [waiting.url, fresh.url]
    assert result["new_items_count"] == 2
    assert _status(waiting) == ("done", "分析後的摘要")


async def test_the_same_page_under_a_tracking_link_counts_as_the_backfilled_stub(radar):
    waiting = _raw("story")
    scheduler._save_deferred_stub(waiting)
    radar.raws = [_raw("story", url=waiting.url + "?utm_source=feed")]

    await radar.run(budget=5)

    assert radar.analyzed == [waiting.url]
    assert _status(waiting) == ("done", "分析後的摘要")


# ── Budget used up: new candidates wait, stored rows stay as they are ──

async def test_when_the_budget_runs_out_new_candidates_wait_and_stored_rows_are_untouched(radar):
    old = [_raw(f"old{i}") for i in range(1, 4)]
    new = [_raw(f"new{i}") for i in range(1, 3)]
    stubs = [scheduler._save_deferred_stub(raw) for raw in old]
    still_waiting = _row(stubs[2])
    radar.raws = old + new

    result = await radar.run(budget=2)

    assert radar.analyzed == [old[0].url, old[1].url]  # oldest stubs first, each once
    assert _status(old[0]) == ("done", "分析後的摘要") and _status(old[1]) == ("done", "分析後的摘要")
    assert _row(stubs[2]) == still_waiting  # the stub out of budget is not rewritten
    for raw in new:
        assert _status(raw) == ("pending", "")
    assert result["deferred_count"] == 3  # old3 keeps waiting, new1 and new2 join the queue
    assert [it["url"] for it in get_pending_analysis_items(10)] == [old[2].url, new[0].url, new[1].url]


def test_a_stub_is_never_written_over_a_stored_page():
    done_id = save_item({"url": "https://example.com/kept", "title_l1": "已分析的標題", "summary_l1": "原本的摘要",
                         "tech_tags": ["Rust"], "deep_analysis": "原本的分析", "origin": "manual"})
    before = _row(done_id)

    assert scheduler._save_deferred_stub(_raw("kept", title="Feed headline")) == done_id
    assert scheduler._save_deferred_stub(_raw("kept", url="https://example.com/kept/?utm_medium=rss")) == done_id
    assert _row(done_id) == before

    stub_id = scheduler._save_deferred_stub(_raw("queued", title="First headline"))
    waiting = _row(stub_id)
    assert waiting["analysis_status"] == "pending" and waiting["title_l1"] == "First headline"
    assert scheduler._save_deferred_stub(_raw("queued", title="Edited headline")) == stub_id
    assert _row(stub_id) == waiting

    with closing(get_db_connection()) as conn:
        assert conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 2


# ── A backfill that did not end in an item still counts as this cycle's try ──

async def test_a_stub_whose_backfill_failed_waits_for_the_next_cycle(radar):
    waiting = _raw("flaky")
    scheduler._save_deferred_stub(waiting)
    radar.raws = [waiting]
    radar.failing = {waiting.url}

    result = await radar.run(budget=5)
    assert radar.analyzed == [waiting.url]  # tried once, not again as a candidate
    assert result["new_items_count"] == 0 and _status(waiting) == ("pending", "")

    radar.failing = set()
    await radar.run(budget=5)
    assert radar.analyzed == [waiting.url] and _status(waiting) == ("done", "分析後的摘要")


async def test_a_backfilled_item_dropped_for_a_muted_tag_is_not_analyzed_again(radar):
    tune_topic_signal("Rust", "mute")  # the tag the analysis gives it; the headline does not show it
    waiting = _raw("muted-after-analysis")
    stub_id = scheduler._save_deferred_stub(waiting)
    radar.raws = [waiting]

    result = await radar.run(budget=5)

    assert radar.analyzed == [waiting.url]
    assert result["new_items_count"] == 0 and get_item_by_id(stub_id) is None
