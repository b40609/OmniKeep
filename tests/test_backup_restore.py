"""Backups carry the database and HTML snapshots, and restore puts both back without deleting anything."""
import json
import os
import sqlite3
import subprocess
import sys
import zipfile
from contextlib import closing
from pathlib import Path

import pytest

from app import __version__, backup
from app.config import settings
from app.database import get_db_connection, save_item
from app.file_lock import FileLock
from app.snapshot import save_html_snapshot

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def local_sink(monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_SINK", "local")


def _item(title):
    return save_item({"url": f"https://example.com/{title}", "title_l1": title})


def _titles(path=None):
    with closing(sqlite3.connect(path or settings.DATABASE_PATH)) as conn:
        return sorted(row[0] for row in conn.execute("SELECT title_l1 FROM items"))


def _snap_dir():
    return Path(settings.SNAPSHOT_DIR)


def _live_files():
    db = Path(settings.DATABASE_PATH)
    return [db, Path(f"{db}-wal"), Path(f"{db}-shm")]


def _stop_server_connections():
    """What a stopped server leaves behind: the WAL checkpointed into the file."""
    with closing(sqlite3.connect(settings.DATABASE_PATH)) as conn:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def test_backup_archive_holds_database_snapshots_and_manifest(local_sink):
    kept = _item("kept")
    save_html_snapshot(kept, "<html><body>原文快照</body></html>", "https://example.com/kept")
    (_snap_dir() / "notes.txt").write_text("not a snapshot")  # only <item id>.html is backed up

    result = backup.run_backup()

    with zipfile.ZipFile(result["file_path"]) as archive:
        assert sorted(archive.namelist()) == ["backup.json", "omnikeep.db", f"snapshots/{kept}.html"]
        manifest = json.loads(archive.read("backup.json"))
    assert manifest["format"] == 2 and manifest["app_version"] == __version__ and manifest["snapshots"] == 1


def test_backup_then_loss_then_restore_brings_everything_back(local_sink):
    kept = _item("kept")
    save_html_snapshot(kept, "<html><body>原文快照</body></html>", "https://example.com/kept")
    snapshot = (_snap_dir() / f"{kept}.html").read_bytes()
    archive = backup.run_backup()["file_path"]
    _stop_server_connections()

    for path in _live_files() + [_snap_dir() / f"{kept}.html"]:
        path.unlink(missing_ok=True)  # the disaster

    result = backup.restore_backup(archive)

    assert result["items"] == 1 and result["snapshots"] == 1 and result["snapshots_written"] == 1
    assert _titles() == ["kept"]
    assert (_snap_dir() / f"{kept}.html").read_bytes() == snapshot
    with closing(get_db_connection()) as conn:  # the app opens it normally
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT COUNT(*) FROM items_fts").fetchone()[0] == 1


def test_restore_refuses_while_the_server_owns_the_database(local_sink):
    _item("kept")
    archive = backup.run_backup()["file_path"]
    _item("newer")
    server = FileLock(f"{settings.DATABASE_PATH}.worker.lock")  # what task_worker holds while running
    assert server.acquire()
    try:
        with pytest.raises(backup.RestoreError, match="stop it"):
            backup.restore_backup(archive)
    finally:
        server.release()
    assert _titles() == ["kept", "newer"]
    assert not list(Path(settings.BACKUP_DIR).glob("omnikeep-prerestore-*"))


def test_replaced_files_are_set_aside_and_restoring_them_undoes_the_restore(local_sink):
    kept = _item("kept")
    save_html_snapshot(kept, "<html><body>舊版</body></html>", "https://example.com/kept")
    archive = backup.run_backup()["file_path"]
    _item("newer")
    save_html_snapshot(kept, "<html><body>新版</body></html>", "https://example.com/kept")
    newer_snapshot = (_snap_dir() / f"{kept}.html").read_bytes()
    _stop_server_connections()

    result = backup.restore_backup(archive)

    assert _titles() == ["kept"]
    aside = Path(result["set_aside"])
    assert _titles(aside / "omnikeep.db") == ["kept", "newer"]
    assert (aside / "snapshots" / f"{kept}.html").read_bytes() == newer_snapshot

    undone = backup.restore_backup(aside)
    assert undone["items"] == 2 and _titles() == ["kept", "newer"]
    assert (_snap_dir() / f"{kept}.html").read_bytes() == newer_snapshot


def test_orphaned_wal_is_moved_aside_instead_of_replayed(local_sink):
    _item("kept")
    archive = backup.run_backup()["file_path"]
    _stop_server_connections()
    # A WAL holding frames the database file never received (e.g. a crash mid-session).
    writer = sqlite3.connect(settings.DATABASE_PATH)
    writer.execute("PRAGMA wal_autocheckpoint = 0")
    writer.execute("UPDATE items SET title_l1 = 'from a stale WAL'")
    writer.commit()
    wal = Path(f"{settings.DATABASE_PATH}-wal")
    stale = wal.read_bytes()
    writer.close()  # checkpoints and removes the WAL
    Path(settings.DATABASE_PATH).unlink()
    wal.write_bytes(stale)  # the database file is gone, its WAL is not

    result = backup.restore_backup(archive)

    assert _titles() == ["kept"]
    assert (Path(result["set_aside"]) / "omnikeep.db-wal").read_bytes() == stale
    with closing(sqlite3.connect(settings.DATABASE_PATH)) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_a_corrupt_live_database_is_set_aside_and_replaced(local_sink):
    _item("kept")
    archive = backup.run_backup()["file_path"]
    _stop_server_connections()
    Path(settings.DATABASE_PATH).write_bytes(b"this is not a database" * 100)

    result = backup.restore_backup(archive)

    assert _titles() == ["kept"]
    assert (Path(result["set_aside"]) / "omnikeep.db").read_bytes().startswith(b"this is not a database")


def test_bad_archives_are_refused_before_anything_is_touched(local_sink, isolated_runtime):
    _item("kept")
    good = backup.run_backup()["file_path"]
    _stop_server_connections()
    db_before = Path(settings.DATABASE_PATH).read_bytes()

    traversal = isolated_runtime / "traversal.zip"
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(traversal, "w") as dst:
        dst.writestr("omnikeep.db", src.read("omnikeep.db"))
        dst.writestr("snapshots/../../escaped.html", "<html></html>")
    not_db = isolated_runtime / "not-db.zip"
    with zipfile.ZipFile(not_db, "w") as dst:
        dst.writestr("omnikeep.db", b"garbage" * 200)
    empty = isolated_runtime / "empty.zip"
    with zipfile.ZipFile(empty, "w") as dst:
        dst.writestr("readme.txt", "hi")

    for bad, reason in ((traversal, "Unexpected entry"), (not_db, "unreadable"), (empty, "omnikeep.db is missing")):
        with pytest.raises(backup.RestoreError, match=reason):
            backup.restore_backup(bad)
    assert Path(settings.DATABASE_PATH).read_bytes() == db_before
    assert not (isolated_runtime / "escaped.html").exists()
    assert not list(Path(settings.BACKUP_DIR).glob("omnikeep-prerestore-*"))


def test_database_only_archives_from_before_format_2_still_restore(local_sink, isolated_runtime):
    kept = _item("kept")
    save_html_snapshot(kept, "<html><body>留著</body></html>", "https://example.com/kept")
    current = backup.run_backup()["file_path"]
    old_style = isolated_runtime / "omnikeep-backup-old.zip"
    with zipfile.ZipFile(current) as src, zipfile.ZipFile(old_style, "w") as dst:
        dst.writestr("omnikeep.db", src.read("omnikeep.db"))
    _item("newer")
    _stop_server_connections()

    result = backup.restore_backup(old_style)

    assert result["format"] == 1 and result["snapshots"] == 0
    assert _titles() == ["kept"]
    assert (_snap_dir() / f"{kept}.html").is_file()  # snapshots the archive lacks are left alone


def test_cli_lists_and_restores_the_latest_backup(local_sink, isolated_runtime):
    kept = _item("kept")
    save_html_snapshot(kept, "<html><body>原文</body></html>", "https://example.com/kept")
    backup.run_backup()
    _stop_server_connections()
    for path in _live_files():
        path.unlink(missing_ok=True)
    env = {**os.environ, "DATABASE_PATH": settings.DATABASE_PATH, "SNAPSHOT_DIR": settings.SNAPSHOT_DIR,
           "BACKUP_DIR": settings.BACKUP_DIR}
    script = [sys.executable, str(REPO / "scripts/restore_backup.py")]

    listing = subprocess.run(script + ["--list"], env=env, capture_output=True, text=True, timeout=60)
    restored = subprocess.run(script + ["--latest", "--yes"], env=env, capture_output=True, text=True, timeout=60)
    cancelled = subprocess.run(script + ["--latest"], env=env, input="no\n", capture_output=True, text=True, timeout=60)

    assert listing.returncode == 0 and "format 2, 1 snapshots" in listing.stdout
    assert restored.returncode == 0, restored.stdout + restored.stderr
    assert "Restored 1 items and 1 snapshots" in restored.stdout
    assert _titles() == ["kept"]
    assert cancelled.returncode == 1 and "nothing changed" in cancelled.stdout
