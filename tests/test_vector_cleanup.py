"""Deleting an item deletes its vectors, and the rebuild tool removes vectors left by older versions."""
from contextlib import closing
from pathlib import Path

from app import reindex, vector
from app.config import settings
from app.database import delete_item, get_db_connection, save_item
from app.vector import init_vector_db, is_sqlite_vec_available, load_vec_extension, store_item_embedding
from scripts.rebuild_embeddings import main as rebuild

VEC = [1.0] + [0.0] * 255


def _item(name):
    item_id = save_item({"url": f"https://vec.test/{name}", "title_l1": name, "summary_l1": "摘要", "tech_tags": []})
    store_item_embedding(item_id, VEC, model="m")
    return item_id


def _vector_ids():
    """(ids in item_embeddings, ids in the sqlite-vec mirror or None where it cannot load)."""
    with closing(get_db_connection()) as conn:
        stored = {r["item_id"] for r in conn.execute("SELECT item_id FROM item_embeddings")}
        mirror = {r["item_id"] for r in conn.execute("SELECT item_id FROM vec_items")} \
            if load_vec_extension(conn) else None
    return stored, mirror


def _expect(ids):
    stored, mirror = _vector_ids()
    assert stored == set(ids)
    assert mirror is None or mirror == set(ids)


def test_deleting_an_item_deletes_its_vectors_in_both_tables():
    init_vector_db()
    kept, gone = _item("kept"), _item("gone")
    _expect({kept, gone})
    assert delete_item(gone) is True
    _expect({kept})
    assert delete_item("no-such-item") is False
    _expect({kept})


def test_deleting_works_where_sqlite_vec_cannot_load(monkeypatch):
    init_vector_db()
    kept, gone = _item("kept"), _item("gone")
    monkeypatch.setattr(vector, "is_sqlite_vec_available", lambda: False)
    assert delete_item(gone) is True
    with closing(get_db_connection()) as conn:
        assert {r["item_id"] for r in conn.execute("SELECT item_id FROM item_embeddings")} == {kept}


def test_deleting_works_before_any_vector_table_exists():
    item_id = save_item({"url": "https://vec.test/plain", "title_l1": "plain", "summary_l1": "", "tech_tags": []})
    with closing(get_db_connection()) as conn, conn:
        conn.execute("DROP TABLE item_embeddings")
    assert delete_item(item_id) is True


def test_the_rebuild_tool_removes_vectors_of_deleted_items(capsys):
    init_vector_db()
    kept = _item("kept")
    store_item_embedding("left-behind", VEC, model="m")  # what a delete used to leave
    if is_sqlite_vec_available():  # and one only the mirror still holds
        with closing(get_db_connection()) as conn, conn:
            load_vec_extension(conn)
            conn.execute("INSERT INTO vec_items (item_id, embedding) VALUES (?, ?)",
                         ("mirror-only", vector.struct.pack("256f", *VEC)))
    orphans = reindex.orphan_vector_ids()
    assert "left-behind" in orphans and kept not in orphans

    assert rebuild(["--prune-orphans"]) == 0  # the plan only
    assert "Dry run: nothing changed" in capsys.readouterr().out
    assert reindex.orphan_vector_ids() == orphans

    assert rebuild(["--prune-orphans", "--yes"]) == 0
    assert f"Removed the vectors of {len(orphans)} deleted items" in capsys.readouterr().out
    _expect({kept})
    assert reindex.orphan_vector_ids() == []
    assert len(list(Path(settings.BACKUP_DIR).glob("omnikeep-prerebuild-*.zip"))) == 1  # backed up first

    assert rebuild(["--prune-orphans", "--yes"]) == 0  # nothing left: no second archive
    assert "Nothing to change" in capsys.readouterr().out
