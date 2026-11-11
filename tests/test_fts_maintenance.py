"""The full-text index is rewritten only when an item's text changes, and the daily backup
(and the bulk-update scripts) merge it and give free pages back."""
import hashlib
import importlib.util
import logging
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from app import backup, database
from app.config import settings
from app.database import (get_db_connection, get_items, optimize_fts, save_item, update_item_field,
                          vacuum_if_fragmented)

ROOT = Path(__file__).resolve().parents[1]
OLD_TRIGGER = """
    CREATE TRIGGER items_au AFTER UPDATE ON items BEGIN
        DELETE FROM items_fts WHERE id = old.id;
        INSERT INTO items_fts(id, title_l1, summary_l1, tech_tags, deep_analysis, content_raw)
        VALUES (new.id, new.title_l1, new.summary_l1, new.tech_tags, new.deep_analysis, new.content_raw);
    END;
"""


def _item(name, title="時序資料庫實測", content="原文內容。" * 50):
    return save_item({"url": f"https://fts.test/{name}", "title_l1": title, "summary_l1": "摘要",
                      "tech_tags": ["SQLite"], "deep_analysis": "## 分析", "content_raw": content})


def _index_state():
    """Row count and content hash of the index's own storage."""
    digest = hashlib.sha256()
    with closing(get_db_connection()) as db:
        rows = db.execute("SELECT id, block FROM items_fts_data ORDER BY id").fetchall()
    for row in rows:
        digest.update(str(row["id"]).encode() + bytes(row["block"]))
    return len(rows), digest.hexdigest()


def _segments():
    with closing(get_db_connection()) as db:
        return db.execute("SELECT COUNT(DISTINCT segid) FROM items_fts_idx").fetchone()[0]


def _trigger_sql():
    with closing(get_db_connection()) as db:
        return db.execute("SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = 'items_au'").fetchone()[0]


def _free_ratio():
    with closing(get_db_connection()) as db:
        return db.execute("PRAGMA freelist_count").fetchone()[0] / db.execute("PRAGMA page_count").fetchone()[0]


def _found(query):
    return [row["id"] for row in get_items(query=query, limit=50)]


def test_starring_reading_and_moving_an_item_leave_the_index_alone():
    item = _item("a")
    before = _index_state()
    update_item_field(item, {"is_starred": 1})
    update_item_field(item, {"is_read": 1})
    update_item_field(item, {"category_name": "工具"})
    assert _index_state() == before
    update_item_field(item, {"title_l1": "改過的標題"})  # and the comparison does notice a text change
    assert _index_state() != before


def test_a_changed_title_is_searchable_whichever_way_it_was_written():
    item = _item("a")
    update_item_field(item, {"title_l1": "知識圖譜入門"})
    assert _found("知識圖譜") == [item] and _found("時序資料庫") == []
    save_item({"url": "https://fts.test/a", "title_l1": "向量索引比較", "summary_l1": "摘要", "tech_tags": []})
    assert _found("向量索引") == [item] and _found("知識圖譜") == []  # the upsert fires the trigger too


def test_an_old_trigger_is_replaced_and_init_db_can_run_again():
    item = _item("a")
    with closing(get_db_connection()) as db, db:
        db.execute("DROP TRIGGER items_au")
        db.execute(OLD_TRIGGER)
    before = _index_state()
    update_item_field(item, {"is_starred": 1})
    assert _index_state() != before  # the old trigger rewrote the entry for a star

    database.init_db()
    migrated = _trigger_sql()
    assert "UPDATE OF title_l1, summary_l1, tech_tags, deep_analysis, content_raw ON items" in migrated
    database.init_db()
    assert _trigger_sql() == migrated

    before = _index_state()
    update_item_field(item, {"is_starred": 0})
    assert _index_state() == before
    update_item_field(item, {"title_l1": "遷移後改的標題"})
    assert _found("遷移後改的標題") == [item]


def test_optimize_merges_the_index_and_search_finds_the_same_items():
    ids = [_item(f"n{n}", title=f"第 {n} 篇：混合搜尋筆記") for n in range(6)]
    for item in ids[:3]:
        update_item_field(item, {"summary_l1": "改寫過的摘要，提到重排序"})
    queries = ("混合搜尋", "重排序", "摘要", "原文內容")
    before = {q: _found(q) for q in queries}
    assert _segments() > 1

    optimize_fts()

    assert _segments() == 1
    assert {q: _found(q) for q in queries} == before
    assert sorted(before["混合搜尋"]) == sorted(ids) and sorted(before["重排序"]) == sorted(ids[:3])


def _make_free_pages():
    for n in range(40):
        _item(f"big{n}", content="很長的原文。" * 800)
    kept = _item("kept", title="留下來的項目")
    with closing(get_db_connection()) as db, db:
        db.execute("DELETE FROM items WHERE url LIKE 'https://fts.test/big%'")
    return kept


def test_vacuum_runs_only_above_the_threshold_and_keeps_the_data():
    _item("small")
    assert vacuum_if_fragmented() is False
    kept = _make_free_pages()
    optimize_fts()
    assert _free_ratio() > 0.2
    size_before = Path(settings.DATABASE_PATH).stat().st_size

    assert vacuum_if_fragmented() is True

    assert _free_ratio() == 0 and Path(settings.DATABASE_PATH).stat().st_size < size_before
    assert _found("留下來的項目") == [kept]
    with closing(get_db_connection()) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_vacuum_keeps_the_vector_index_answering():
    from app.vector import is_sqlite_vec_available, search_similar_items, store_item_embedding
    if not is_sqlite_vec_available():
        pytest.skip("sqlite-vec cannot load into this Python's sqlite3")
    kept = _make_free_pages()
    store_item_embedding(kept, [1.0] + [0.0] * 255, model="m")
    store_item_embedding("other", [0.0, 1.0] + [0.0] * 254, model="m")
    optimize_fts()
    assert vacuum_if_fragmented() is True
    assert [r["item_id"] for r in search_similar_items([1.0] + [0.0] * 255, limit=1)] == [kept]


def test_the_backup_compacts_the_database_first(monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_SINK", "local")
    kept = _make_free_pages()
    live_before = Path(settings.DATABASE_PATH).stat().st_size

    result = backup.run_backup()

    assert result["status"] == "ok" and _segments() == 1 and _free_ratio() == 0
    with zipfile.ZipFile(result["file_path"]) as archive:
        assert archive.getinfo("omnikeep.db").file_size < live_before / 2
    assert _found("留下來的項目") == [kept]


def test_a_failing_compaction_never_stops_the_backup(monkeypatch, caplog):
    monkeypatch.setattr(settings, "BACKUP_SINK", "local")
    _item("a")

    def locked(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(backup, "optimize_fts", locked)
    monkeypatch.setattr(backup, "vacuum_if_fragmented", locked)
    with caplog.at_level(logging.WARNING, logger="omnikeep.backup"):
        result = backup.run_backup()
    assert result["status"] == "ok" and Path(result["file_path"]).is_file()
    messages = [r.getMessage() for r in caplog.records if r.name == "omnikeep.backup"]
    assert any("optimize" in m for m in messages) and any("vacuum" in m for m in messages)


def test_compaction_gives_up_while_another_connection_is_writing(monkeypatch):
    _make_free_pages()
    real = database.get_db_connection

    def impatient():
        conn = real()
        conn.execute("PRAGMA busy_timeout = 50")
        return conn

    monkeypatch.setattr(database, "get_db_connection", impatient)
    writer = real()
    try:
        writer.execute("BEGIN IMMEDIATE")
        writer.execute("UPDATE items SET is_read = 1")
        with pytest.raises(sqlite3.OperationalError):
            vacuum_if_fragmented()
        backup._compact_database()  # logs and returns
    finally:
        writer.rollback()
        writer.close()
    assert _free_ratio() > 0.2  # left for the next run


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("name", ["reanalyze_items", "annotate_sources", "blocked_items"])
def test_bulk_update_scripts_merge_the_index_when_they_finish(name, isolated_runtime, monkeypatch):
    for n in range(5):
        update_item_field(_item(f"n{n}"), {"summary_l1": f"第 {n} 次改寫"})
    assert _segments() > 1
    tool = _script(name)
    out = isolated_runtime / "run"
    out.mkdir()
    (out / "before.jsonl").write_text("", encoding="utf-8")
    args = ["--out", str(out), "--restore"]
    assert tool.main(args if name != "blocked_items" else ["--db", settings.DATABASE_PATH] + args) == 0
    assert _segments() == 1

    monkeypatch.setattr(database, "optimize_fts", lambda: (_ for _ in ()).throw(sqlite3.OperationalError("busy")))
    if hasattr(tool, "optimize_fts"):
        monkeypatch.setattr(tool, "optimize_fts", database.optimize_fts)
    tool.tidy_index()  # a failure here is reported, not raised
