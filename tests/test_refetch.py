"""Items whose fetch got only an error page are fetched again later, with no AI call until it works."""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app import database as db
from app import refetch
from app.pipeline import FETCH_FAILED_TAG

X_PAGE = ("We’ve detected that JavaScript is disabled in this browser. Please enable JavaScript or switch to a "
          "supported browser to continue using x.com. You can see a list of supported browsers in our Help Center.")
REAL = "牧枫 (@mr_mofun) 在 X 發文\n\n以下5个超实用设计灵感网站，能大幅提升你的工作效率。" + "说明文字。" * 30
AI = {"category": "Inbox", "title_l1": "五個設計靈感網站", "summary_l1": "整理五個設計靈感網站。", "tech_tags": ["Design"],
      "deep_analysis": "## 重點\n- Scrolltide", "is_composite": False, "sub_entities": []}
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _save(item_id, content, created, source_type="web", updated=None):
    db.save_item({"id": item_id, "url": f"https://x.com/u/status/{item_id}", "source_type": source_type,
                  "title_l1": "x.com/u/status", "summary_l1": f"{FETCH_FAILED_TAG}網站回的是「請啟用 JavaScript」的頁面",
                  "deep_analysis": "> ⚠️ 擷取失敗", "content_raw": content, "category_name": "Inbox"})
    conn = db.get_db_connection()
    conn.execute("UPDATE items SET created_at = ?, updated_at = ? WHERE id = ?",
                 (created.isoformat(), (updated or created).isoformat(), item_id))
    conn.commit()
    conn.close()


def _page(content):
    return {"url": "", "title": "X", "content_raw": content, "cover_image": "https://pbs.twimg.com/p.jpg",
            "author": "牧枫 (@mr_mofun)", "published_date": "", "raw_html": "", "http_status": 200}


@pytest.fixture(autouse=True)
def fresh_state():
    refetch._last_try.clear()
    yield
    refetch._last_try.clear()


@pytest.fixture
def follow_ups():
    with patch("app.research.tool_resolver.resolve_mentioned_tools", new=AsyncMock(return_value=[])), \
         patch("app.research.competitor_detector.detect_competitors_and_alternatives", new=AsyncMock()), \
         patch("app.snapshot.save_html_snapshot"):
        yield


def test_only_recent_error_pages_of_scraped_pages_wait_for_a_retry():
    _save("2119000000000000001", X_PAGE, NOW - timedelta(hours=3))
    _save("2119000000000000002", REAL, NOW - timedelta(hours=3))  # has its content
    _save("2119000000000000003", X_PAGE, NOW - timedelta(days=8))  # gave up
    _save("2119000000000000004", X_PAGE, NOW - timedelta(hours=3), source_type="youtube")
    assert [i["id"] for i in refetch.candidates(NOW)] == ["2119000000000000001"]


def test_retries_start_an_hour_after_collecting_and_the_gap_doubles():
    created = NOW - timedelta(hours=10)
    item = {"id": "a", "created_at": created.isoformat(), "updated_at": created.isoformat()}
    assert not refetch.due(item, created + timedelta(minutes=59))
    tries = []
    t = created
    while t < created + timedelta(hours=40):
        t += timedelta(minutes=10)
        if refetch.due(item, t):
            tries.append(round((t - created).total_seconds() / 3600, 1))
            refetch._last_try["a"] = t
    assert tries == [1.0, 2.0, 4.0, 8.0, 16.0, 32.0]


def test_a_rewrite_by_another_job_does_not_count_as_a_try():
    # Collected on 11-02, its analysis rewritten on 11-07 by the source annotation run: the
    # rewrite is not a fetch, so the item is tried now instead of five days later (after the 7 days).
    _save("2119000000000000001", X_PAGE, NOW - timedelta(days=6), updated=NOW - timedelta(hours=1))
    item = refetch.candidates(NOW)[0]
    assert refetch.due(item, NOW)
    refetch._last_try[item["id"]] = NOW
    assert not refetch.due(item, NOW + timedelta(days=5))  # tried: the gap doubles from here


def test_a_retry_that_still_gets_the_error_page_costs_no_ai_call(follow_ups):
    _save("2119000000000000001", X_PAGE, NOW - timedelta(hours=3))
    provider = AsyncMock()
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(X_PAGE))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        stats = asyncio.run(refetch.run_once(NOW))
        again = asyncio.run(refetch.run_once(NOW + timedelta(minutes=10)))  # not due yet
    provider.generate_json.assert_not_awaited()
    assert stats == {"waiting": 1, "tried": 1, "fixed": 0}
    assert again == {"waiting": 1, "tried": 0, "fixed": 0}
    assert db.get_item_by_id("2119000000000000001")["content_raw"] == X_PAGE


def test_the_first_retry_that_gets_the_content_analyses_the_item_in_place(follow_ups):
    _save("2119000000000000001", X_PAGE, NOW - timedelta(hours=3))
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=dict(AI))
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(REAL))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        stats = asyncio.run(refetch.run_once(NOW))
    assert stats == {"waiting": 1, "tried": 1, "fixed": 1}
    item = db.get_item_by_id("2119000000000000001")
    assert item["content_raw"].startswith("牧枫 (@mr_mofun)") and item["summary_l1"] == AI["summary_l1"]
    assert item["cover_image"] == "https://pbs.twimg.com/p.jpg" and item["author"] == "牧枫 (@mr_mofun)"
    assert refetch.candidates(NOW) == []


def test_a_backlog_is_worked_through_a_few_at_a_time(follow_ups, monkeypatch):
    monkeypatch.setattr(refetch, "PER_TICK", 2)
    for n in range(5):
        _save(f"211900000000000000{n}", X_PAGE, NOW - timedelta(hours=3))
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(X_PAGE))), \
         patch("app.pipeline.get_primary_provider", return_value=AsyncMock()):
        assert asyncio.run(refetch.run_once(NOW))["tried"] == 2
        assert asyncio.run(refetch.run_once(NOW))["tried"] == 2
        assert asyncio.run(refetch.run_once(NOW))["tried"] == 1


def test_a_post_saved_without_its_replies_is_tried_again_until_they_come(follow_ups):
    from app.parsers.x_posts import REPLIES_MISSING
    saved = REAL + "\n\n" + REPLIES_MISSING
    _save("2119000000000000001", saved, NOW - timedelta(hours=3))
    assert [i["id"] for i in refetch.candidates(NOW)] == ["2119000000000000001"]
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=dict(AI))
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(saved))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        assert asyncio.run(refetch.run_once(NOW))["fixed"] == 0  # still no replies: no AI call
    provider.generate_json.assert_not_awaited()
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(REAL + "\n\n留言（收錄 1 則）：\n- a：b"))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        assert asyncio.run(refetch.run_once(NOW + timedelta(hours=4)))["fixed"] == 1  # next gap: 3 h
    assert "留言（收錄 1 則）" in db.get_item_by_id("2119000000000000001")["content_raw"]
    assert refetch.candidates(NOW + timedelta(hours=4)) == []


def test_an_error_page_is_replaced_by_the_post_even_before_its_replies_come(follow_ups):
    from app.parsers.x_posts import REPLIES_MISSING
    _save("2119000000000000001", X_PAGE, NOW - timedelta(hours=3))
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=dict(AI))
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(REAL + "\n\n" + REPLIES_MISSING))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        assert asyncio.run(refetch.run_once(NOW))["fixed"] == 1
    item = db.get_item_by_id("2119000000000000001")
    assert item["content_raw"].startswith("牧枫") and REPLIES_MISSING in item["content_raw"]
    assert [i["id"] for i in refetch.candidates(NOW)] == ["2119000000000000001"]  # replies still to come
