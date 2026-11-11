"""A bookmark import without AI and the demo data never overwrite an item that is already stored."""
from contextlib import closing

from starlette.testclient import TestClient

from app.config import settings
from app.database import (get_db_connection, get_item_by_id, save_item, save_item_if_new, seed_demo_items)
from app.main import app

ANALYSED = {"url": "https://blog.example.com/rrf", "title_l1": "RRF 混合搜尋", "summary_l1": "AI 寫的摘要",
            "tech_tags": ["RRF"], "deep_analysis": "## 深度分析\n- 重點", "content_raw": "完整的原文。" * 20,
            "category_name": "文章", "is_starred": 1}
KEPT_FIELDS = ("title_l1", "summary_l1", "tech_tags", "deep_analysis", "content_raw", "category_name",
               "analysis_status", "is_starred", "origin")


def _client():
    return TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"})


def _count():
    with closing(get_db_connection()) as db:
        return db.execute("SELECT COUNT(*) FROM items").fetchone()[0]


def _kept(item_id):
    item = get_item_by_id(item_id)
    return {field: item[field] for field in KEPT_FIELDS}


def test_importing_a_stored_link_keeps_its_analysis_and_content():
    item_id = save_item(dict(ANALYSED))
    before = _kept(item_id)
    csv = ("url,title,tags,folder\n"
           "https://blog.example.com/rrf,Bookmark title,x,Folder\n"                      # the same URL
           "https://blog.example.com/rrf?utm_source=newsletter&utm_medium=email,Tracked,x,Folder\n"  # the same page
           "https://blog.example.com/other,New page,x,Folder\n"
           "https://127.0.0.1/admin,Private,x,Folder\n")

    data = _client().post("/api/items/import/bookmarks",
                          json={"content": csv, "filename": "bookmarks.csv", "enqueue_ai": False}).json()

    assert _kept(item_id) == before
    assert _count() == 2
    assert (data["total_parsed"], data["imported_count"], data["existing_count"], data["skipped_count"]) == (4, 1, 2, 3)
    assert len(data["sample_ids"]) == 1 and get_item_by_id(data["sample_ids"][0])["title_l1"] == "New page"
    assert data["errors"] == []


def test_importing_the_same_file_twice_adds_nothing_the_second_time():
    csv = "url,title\nhttps://a.example.com/1,One\nhttps://a.example.com/2,Two\nhttps://a.example.com/1,One again\n"
    first = _client().post("/api/items/import/bookmarks", json={"content": csv, "filename": "b.csv"}).json()
    second = _client().post("/api/items/import/bookmarks", json={"content": csv, "filename": "b.csv"}).json()
    assert (first["imported_count"], first["existing_count"]) == (2, 1)
    assert (second["imported_count"], second["existing_count"], second["skipped_count"]) == (0, 3, 3)
    assert _count() == 2


def test_an_empty_import_reports_the_new_counter_too():
    data = _client().post("/api/items/import/bookmarks", json={"content": "url,title\n", "filename": "b.csv"}).json()
    assert data["existing_count"] == 0 and data["skipped_count"] == 0


def test_demo_data_leaves_a_saved_page_alone():
    mine = save_item({**ANALYSED, "url": "https://github.com/fastapi/fastapi"})
    video = save_item({**ANALYSED, "url": "https://youtu.be/kCc8FmEb1nY?si=abc"})  # another link to a demo video
    before = _kept(mine), _kept(video)

    created = seed_demo_items()

    assert (_kept(mine), _kept(video)) == before
    assert [d["source_type"] for d in created] == ["bilibili"] and _count() == 3
    again = _client().post("/api/items/seed-demo").json()
    assert again["success"] is True and again["count"] == 0 and _count() == 3


def test_save_item_still_overwrites_for_reanalysis():
    item_id = save_item(dict(ANALYSED))
    assert save_item_if_new({**ANALYSED, "summary_l1": "不該寫入"}) is None
    assert save_item({**ANALYSED, "summary_l1": "重新分析的摘要"}) == item_id
    assert get_item_by_id(item_id)["summary_l1"] == "重新分析的摘要"
