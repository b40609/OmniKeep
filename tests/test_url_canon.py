"""Canonical links (app/url_canon.py): the same page behind different links is found once,
and different pages never collapse into one (different YouTube videos used to)."""
from unittest.mock import AsyncMock, patch

import pytest

from app import database as db
from app.radar.adapters.base import RawFeedItem
from app.url_canon import canonical_url, search_key

VIDEO = "dQw4w9WgXcQ"
OTHER = "9bZkp7q19f0"


@pytest.mark.parametrize("link, canon", [
    (f"https://www.youtube.com/watch?v={VIDEO}&si=abc&t=30", f"https://www.youtube.com/watch?v={VIDEO}"),
    (f"https://youtu.be/{VIDEO}?si=x", f"https://www.youtube.com/watch?v={VIDEO}"),
    (f"https://m.youtube.com/shorts/{VIDEO}?feature=share", f"https://www.youtube.com/watch?v={VIDEO}"),
    ("https://www.youtube.com/@chan/videos?si=1", "https://www.youtube.com/@chan/videos"),
    ("https://twitter.com/Foo/status/1888?s=20&t=abc", "https://x.com/foo/status/1888"),
    ("https://GitHub.com/Owner/Repo.git?tab=readme", "https://github.com/owner/repo"),
    ("https://www.threads.com/@User/post/Abc?xmt=1", "https://www.threads.net/@user/post/Abc"),
    ("https://www.instagram.com/reel/DfWwhZ1hUwP/?dlrf=MWsz", "https://www.instagram.com/reel/DfWwhZ1hUwP"),
    ("https://www.bilibili.com/video/BV1x?p=2&vd_source=abc&spm_id_from=333", "https://www.bilibili.com/video/BV1x?p=2"),
    ("https://news.ycombinator.com/item?id=123&utm_source=x", "https://news.ycombinator.com/item?id=123"),
    ("https://Example.COM:443/a/?b=2&a=1&fbclid=z#frag", "https://example.com/a?a=1&b=2"),
    ("see https://cursor.com?ref=ph (tool)", "https://cursor.com"),
    ("https://claude.ai/", "https://claude.ai"),
    ("", ""),
])
def test_canonical_forms(link, canon):
    assert canonical_url(link) == canon
    assert db.normalize_canonical_url(link) == canon


def test_different_pages_stay_apart():
    assert canonical_url(f"https://www.youtube.com/watch?v={VIDEO}") != canonical_url(f"https://www.youtube.com/watch?v={OTHER}")
    assert canonical_url("https://news.ycombinator.com/item?id=1") != canonical_url("https://news.ycombinator.com/item?id=2")
    assert canonical_url("https://www.bilibili.com/video/BV1x?p=1") != canonical_url("https://www.bilibili.com/video/BV1x?p=2")


def test_search_key_is_inside_every_equivalent_link():
    for link in (f"https://youtu.be/{VIDEO}?si=x", f"https://www.youtube.com/watch?si=1&v={VIDEO}",
                 "https://twitter.com/Foo/status/1888?s=20", "https://www.example.com/Post/1?utm_source=x"):
        assert search_key(canonical_url(link)) in link.lower()


def _item(item_id, url):
    db.save_item({"id": item_id, "url": url, "title_l1": item_id, "summary_l1": "", "category_name": "影片"})


def test_lookup_finds_the_same_page_under_another_link():
    _item("yt", f"https://youtu.be/{VIDEO}?si=share")
    _item("tw", "https://twitter.com/foo/status/1888?s=20")
    _item("hn", "https://news.ycombinator.com/item?id=7&utm_source=rss")
    assert db.find_item_by_canonical_or_url(f"https://www.youtube.com/watch?v={VIDEO}&t=9")["id"] == "yt"
    assert db.find_item_by_canonical_or_url("https://x.com/Foo/status/1888")["id"] == "tw"
    assert db.find_item_by_canonical_or_url("https://news.ycombinator.com/item?id=7")["id"] == "hn"
    assert db.find_item_by_canonical_or_url(f"https://www.youtube.com/watch?v={OTHER}") is None
    assert db.find_item_by_canonical_or_url("https://news.ycombinator.com/item?id=8") is None


def test_a_cited_video_no_longer_answers_for_every_other_video():
    # The bug: a citation of one YouTube video was stored as https://www.youtube.com/watch,
    # so the queue took any new video for that one.
    _item("cited", f"https://www.youtube.com/watch?v={VIDEO}")
    _item("parent", "https://example.com/digest")
    db.save_citation({"source_parent_id": "parent", "target_item_id": "cited",
                      "target_canonical_url": f"https://www.youtube.com/watch?v={VIDEO}"})
    assert db.find_item_by_canonical_or_url(f"https://www.youtube.com/watch?v={OTHER}") is None
    assert db.find_item_by_canonical_or_url(f"https://youtu.be/{VIDEO}")["id"] == "cited"


async def test_radar_skips_a_known_page_and_the_same_story_from_two_feeds():
    _item("known", "https://example.com/known-article")
    raws = [
        RawFeedItem(url="https://example.com/known-article?utm_source=rss", title="Known", content="",
                    source_id="s1", source_type="rss"),
        RawFeedItem(url="https://example.com/fresh?utm_medium=feed", title="Fresh A", content="",
                    source_id="s1", source_type="rss"),
        RawFeedItem(url="https://example.com/fresh/?fbclid=1", title="Fresh B", content="",
                    source_id="s2", source_type="rss"),
    ]

    class Adapter:
        async def fetch_latest(self, src):
            return raws

    analyzed = AsyncMock(return_value=None)
    with patch("app.radar.scheduler.get_all_radar_sources", return_value=[{"id": "s1", "source_type": "rss"}]), \
            patch("app.radar.scheduler.get_adapter", return_value=Adapter()), \
            patch("app.radar.scheduler.is_source_due", return_value=True), \
            patch("app.radar.scheduler.pregate_item", return_value=(1.0, False)), \
            patch("app.radar.scheduler.get_radar_settings",
                  return_value={"max_analyze_per_cycle": 5, "notification_mode": "silent"}), \
            patch("app.radar.scheduler._backfill_pending", new=AsyncMock(return_value=[])), \
            patch("app.radar.scheduler._analyze_candidate", new=analyzed):
        from app.radar.scheduler import run_radar_cycle
        await run_radar_cycle(force=True, auto_digest=False)
    assert [call.args[0] for call in analyzed.await_args_list] == ["https://example.com/fresh?utm_medium=feed"]


def test_same_page_keeps_a_repositorys_pages_apart():
    _item("repo", "https://github.com/acme/tool")
    _item("rel1", "https://github.com/acme/tool/releases/tag/v1.0.0")
    assert canonical_url("https://github.com/acme/tool/releases/tag/v2.0.0") == "https://github.com/acme/tool"
    assert canonical_url("https://github.com/Acme/tool/releases/tag/v2.0.0/", repo_level=False) == \
        "https://github.com/acme/tool/releases/tag/v2.0.0"
    assert db.find_item_by_same_page("https://github.com/acme/tool/releases/tag/v2.0.0") is None
    assert db.find_item_by_same_page("https://github.com/acme/tool/releases/tag/v1.0.0?utm_source=x")["id"] == "rel1"
    _item("yt2", f"https://youtu.be/{OTHER}")
    assert db.find_item_by_same_page(f"https://www.youtube.com/watch?v={OTHER}&si=1")["id"] == "yt2"


async def test_radar_still_analyzes_a_new_release_of_a_known_repository():
    _item("repo2", "https://github.com/acme/widget")
    raws = [RawFeedItem(url="https://github.com/acme/widget/releases/tag/v3.0.0", title="v3", content="",
                        source_id="gh", source_type="github")]

    class Adapter:
        async def fetch_latest(self, src):
            return raws

    analyzed = AsyncMock(return_value=None)
    with patch("app.radar.scheduler.get_all_radar_sources", return_value=[{"id": "gh", "source_type": "github"}]), \
            patch("app.radar.scheduler.get_adapter", return_value=Adapter()), \
            patch("app.radar.scheduler.is_source_due", return_value=True), \
            patch("app.radar.scheduler.pregate_item", return_value=(1.0, False)), \
            patch("app.radar.scheduler.get_radar_settings",
                  return_value={"max_analyze_per_cycle": 5, "notification_mode": "silent"}), \
            patch("app.radar.scheduler._backfill_pending", new=AsyncMock(return_value=[])), \
            patch("app.radar.scheduler._analyze_candidate", new=analyzed):
        from app.radar.scheduler import run_radar_cycle
        await run_radar_cycle(force=True, auto_digest=False)
    assert [call.args[0] for call in analyzed.await_args_list] == [raws[0].url]
