"""Backups carry the database and HTML snapshots, and restore puts both back without deleting anything."""
import json
import zipfile
from pathlib import Path

import pytest

from app import __version__, backup
from app.config import settings
from app.database import save_item
from app.snapshot import save_html_snapshot


@pytest.fixture
def local_sink(monkeypatch):
    monkeypatch.setattr(settings, "BACKUP_SINK", "local")


def _item(title):
    return save_item({"url": f"https://example.com/{title}", "title_l1": title})


def _snap_dir():
    return Path(settings.SNAPSHOT_DIR)


def test_backup_archive_holds_database_snapshots_and_manifest(local_sink):
    kept = _item("kept")
    save_html_snapshot(kept, "<html><body>原文快照</body></html>", "https://example.com/kept")
    (_snap_dir() / "notes.txt").write_text("not a snapshot")  # only <item id>.html is backed up

    result = backup.run_backup()

    with zipfile.ZipFile(result["file_path"]) as archive:
        assert sorted(archive.namelist()) == ["backup.json", "omnikeep.db", f"snapshots/{kept}.html"]
        manifest = json.loads(archive.read("backup.json"))
    assert manifest["format"] == 2 and manifest["app_version"] == __version__ and manifest["snapshots"] == 1
