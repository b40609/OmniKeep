"""The item list can be narrowed to one kind, ordered oldest first, paged, and reports
how many items the whole result holds."""
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import (ITEM_KINDS, count_items, get_db_connection, get_items, item_kind, save_item)
from app.main import app

client = TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"})


def _item(name, url, source_type="web", day=1, title=None, **extra):
    """An item whose age is set by `day`: a higher day is newer."""
    item_id = save_item({"url": url, "title_l1": title or f"項目 {name}", "summary_l1": "摘要",
                         "source_type": source_type, "tech_tags": [], **extra})
    with closing(get_db_connection()) as db, db:
        db.execute("UPDATE items SET created_at = ? WHERE id = ?", (f"2026-01-{day:02d}T00:00:00+00:00", item_id))
    return item_id


@pytest.mark.parametrize("url, source_type, kind", [
    ("https://github.com/owner/repo", "github", "project"),
    ("https://github.com/owner/repo", "web", "project"),
    ("https://www.github.com/owner/repo", "web", "project"),
    ("https://owner.github.io/project/", "github", "article"),
    ("https://gist.github.com/owner/abc", "web", "article"),
    ("", "github", "project"),
    ("https://www.threads.net/@someone/post/abc", "threads", "post"),
    ("https://www.threads.com/@someone/post/abc", "web", "post"),
    ("https://www.facebook.com/groups/1/posts/2", "web", "post"),
    ("https://x.com/someone/status/1", "web", "post"),
    ("https://www.instagram.com/p/abc/", "instagram", "post"),
    ("https://www.youtube.com/watch?v=abc", "youtube", "video"),
    ("https://youtu.be/abc", "web", "video"),
    ("https://m.youtube.com/shorts/abc", "web", "video"),
    ("https://www.bilibili.com/video/BV1", "bilibili", "video"),
    ("https://www.instagram.com/reel/abc/", "reel", "video"),
    ("https://animations.dev/", "web", "article"),
    ("https://example.com/feed/1", "rss", "article"),
    ("note://abc", "note", "article"),
    (None, None, "article"),
    # A look-alike host is not the site.
    ("https://notgithub.com/owner/repo", "web", "article"),
    ("https://fakeyoutube.com/watch", "web", "article"),
])
def test_every_item_is_one_kind_and_project_means_a_github_address(url, source_type, kind):
    # The same cases as frontend/tests/wall.test.mjs: the list filter and the icon must agree.
    assert item_kind(url, source_type) == kind
    assert kind in ITEM_KINDS


def _mixed():
    return {
        "repo": _item("repo", "https://github.com/owner/repo", "github", day=1),
        "video": _item("video", "https://youtu.be/abc", "web", day=2),
        "post": _item("post", "https://www.threads.net/@a/post/b", "threads", day=3),
        "article": _item("article", "https://example.com/post", "web", day=4),
        "repo2": _item("repo2", "https://github.com/owner/other", "web", day=5, is_starred=1),
    }


def test_the_list_narrows_to_one_kind_and_counts_the_whole_result():
    ids = _mixed()
    listed = lambda **filters: [row["id"] for row in get_items(limit=50, **filters)]
    assert listed(kind="project") == [ids["repo2"], ids["repo"]]
    assert listed(kind="video") == [ids["video"]]
    assert listed(kind="post") == [ids["post"]]
    assert listed(kind="article") == [ids["article"]]
    assert sorted(listed()) == sorted(ids.values())
    # The kind works together with the other filters.
    assert listed(kind="project", is_starred=True) == [ids["repo2"]]
    assert count_items(kind="project") == 2
    assert count_items(kind="project", is_starred=True) == 1
    assert count_items() == 5
    assert sum(count_items(kind=kind) for kind in ITEM_KINDS) == 5


def test_oldest_first_reverses_the_list_and_pages_do_not_overlap():
    ids = [_item(f"n{day}", f"https://example.com/{day}", day=1 + day // 2) for day in range(7)]  # pairs share a day
    newest = [row["id"] for row in get_items(limit=50)]
    oldest = [row["id"] for row in get_items(limit=50, sort="oldest")]
    assert oldest == newest[::-1]
    assert oldest[0] == ids[0] and newest[0] == ids[-1]
    # Items saved at the same instant keep one order from page to page.
    for sort in ("newest", "oldest"):
        whole = [row["id"] for row in get_items(limit=50, sort=sort)]
        paged = [row["id"] for offset in range(0, 7, 2) for row in get_items(limit=2, offset=offset, sort=sort)]
        assert paged == whole


def test_a_search_stays_ranked_by_relevance_and_can_still_be_narrowed():
    title_hit = _item("t", "https://github.com/owner/kubernetes-tool", "github", day=1, title="Kubernetes 排程工具")
    body_hit = _item("b", "https://example.com/cluster", "web", day=5, title="叢集筆記",
                     content_raw="這篇提到 Kubernetes 的排程")
    for sort in ("newest", "oldest"):
        assert [row["id"] for row in get_items(query="Kubernetes", sort=sort)] == [title_hit, body_hit]
    assert [row["id"] for row in get_items(query="Kubernetes", kind="article")] == [body_hit]
    assert count_items(query="Kubernetes") == 2
    assert count_items(query="Kubernetes", kind="project") == 1
    # Widening to any word is counted the way it is listed.
    assert count_items(query="Kubernetes 不存在的詞彙") == len(get_items(query="Kubernetes 不存在的詞彙")) == 2


def test_unknown_kinds_and_orders_are_refused_before_any_sql_runs():
    _mixed()
    with pytest.raises(ValueError):
        get_items(kind="project' OR 1=1 --")
    with pytest.raises(ValueError):
        count_items(kind="everything")
    with pytest.raises(ValueError):
        get_items(sort="created_at; DROP TABLE items")
    assert count_items() == 5


def test_the_api_takes_kind_and_sort_and_reports_the_total_in_a_header():
    ids = _mixed()
    res = client.get("/api/items", params={"kind": "project", "sort": "oldest", "limit": 1})
    assert res.status_code == 200
    assert [row["id"] for row in res.json()] == [ids["repo"]]      # one page...
    assert res.headers["X-Total-Count"] == "2"                      # ...of two items in all
    second = client.get("/api/items", params={"kind": "project", "sort": "oldest", "limit": 1, "offset": 1})
    assert [row["id"] for row in second.json()] == [ids["repo2"]]
    # Without the new parameters the response is what it always was: a list, newest first.
    plain = client.get("/api/items")
    assert isinstance(plain.json(), list) and plain.json()[0]["id"] == ids["repo2"]
    assert plain.headers["X-Total-Count"] == "5"
    assert client.get("/api/items", params={"starred": "true"}).headers["X-Total-Count"] == "1"


@pytest.mark.parametrize("params", [
    {"kind": "everything"}, {"kind": "project' OR 1=1 --"}, {"sort": "random"}, {"sort": "created_at DESC; --"},
])
def test_the_api_rejects_values_it_does_not_know(params):
    assert client.get("/api/items", params=params).status_code == 422
