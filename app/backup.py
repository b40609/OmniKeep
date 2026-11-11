"""Multi-sink backup for the second brain (SQLite database + HTML snapshots).

Sinks (BACKUP_SINK in .env) — self-hosters pick what they have:
  local  rotating zip snapshots into BACKUP_DIR (default, zero deps)
  rclone one binary covers 40+ cloud backends (GDrive/OneDrive/Dropbox/S3/B2/WebDAV…)
  git    auto-commit the snapshot into a private repo clone (versioned history)
  off    disabled
The DB snapshot is taken via sqlite3's online-backup API so a live WAL
database is copied consistently without stopping the server. That copy
includes free pages, so run_backup() first merges the full-text index and
vacuums the database when a fifth of the file is free.

Archive layout (format 2): omnikeep.db, snapshots/<item id>.html, backup.json.
Format 1 archives hold omnikeep.db only; restore_backup() accepts both.
"""
import asyncio
import json
import logging
import re
import shutil
import sqlite3
import subprocess
import zipfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

from app import __version__
from app.config import settings
from app.database import log_backup_run, optimize_fts, vacuum_if_fragmented
from app.file_lock import FileLock

logger = logging.getLogger("omnikeep.backup")

ARCHIVE_FORMAT = 2
# app/snapshot.py names each snapshot after its item id.
_SNAPSHOT_NAME = re.compile(r"^[A-Za-z0-9_-]+\.html$")
# VACUUM before the snapshot once this share of the database file is free pages.
VACUUM_FREE_PAGE_RATIO = 0.2


def _compact_database() -> None:
    """Shrink what the snapshot is about to copy: merge the full-text index, then give
    back free pages when they are a large share of the file. Neither step may stop the
    backup: a busy database (VACUUM needs the write lock) is left for the next run."""
    try:
        optimize_fts()
    except Exception as exc:
        logger.warning("Could not optimize the full-text index before the backup: %s", exc)
    try:
        if vacuum_if_fragmented(VACUUM_FREE_PAGE_RATIO):
            logger.info("Vacuumed the database before the backup")
    except Exception as exc:
        logger.warning("Could not vacuum the database before the backup: %s", exc)


def _snapshot_db(tmp_dir: Path) -> Path:
    """Consistent copy of a live WAL database via the sqlite3 backup API."""
    snap = tmp_dir / "omnikeep.db"
    uri = Path(settings.DATABASE_PATH).resolve().as_uri() + "?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as src, closing(sqlite3.connect(str(snap))) as dst:
        with dst:
            src.backup(dst)
    return snap


def _snapshot_files() -> List[Path]:
    root = Path(settings.SNAPSHOT_DIR)
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir()
                  if _SNAPSHOT_NAME.match(path.name) and path.is_file() and not path.is_symlink())


def _make_zip(snap_db: Path, zip_path: Path) -> int:
    snapshots = _snapshot_files()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(snap_db, "omnikeep.db")
        for path in snapshots:
            zf.write(path, f"snapshots/{path.name}")
        zf.writestr("backup.json", json.dumps({
            "format": ARCHIVE_FORMAT,
            "app_version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "snapshots": len(snapshots),
        }, indent=2))
    return zip_path.stat().st_size


def _rotate_local(keep: int) -> None:
    backups = sorted(Path(settings.BACKUP_DIR).glob("omnikeep-backup-*.zip"))
    for old in backups[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)


def _rclone_push(zip_path: Path) -> None:
    remote = settings.BACKUP_RCLONE_REMOTE
    if not remote:
        raise RuntimeError("BACKUP_RCLONE_REMOTE not configured")
    res = subprocess.run(["rclone", "copy", str(zip_path), remote],
                         capture_output=True, text=True, timeout=600)
    if res.returncode != 0:
        raise RuntimeError(f"rclone failed: {res.stderr[:400]}")


def _git_push(zip_path: Path) -> None:
    repo = settings.BACKUP_GIT_REPO_DIR
    if not repo:
        raise RuntimeError("BACKUP_GIT_REPO_DIR not configured")
    repo_dir = Path(repo)
    if not (repo_dir / ".git").exists():
        raise RuntimeError(f"{repo} is not a git clone")
    dst = repo_dir / zip_path.name
    shutil.copy2(zip_path, dst)
    for args in (["git", "-C", str(repo_dir), "add", "--", zip_path.name],
                 ["git", "-C", str(repo_dir), "commit", "--only", "-m", f"omnikeep backup {zip_path.stem}", "--", zip_path.name],
                 ["git", "-C", str(repo_dir), "push"]):
        res = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if res.returncode != 0 and "nothing to commit" not in res.stdout:
            raise RuntimeError(f"git step failed: {res.stderr[:400]}")


def snapshot_archive(label: str) -> Path:
    """A restorable archive of the current data, taken before a bulk change. Named
    omnikeep-<label>-<stamp>.zip, so local rotation (omnikeep-backup-*) never removes it."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_dir = Path(settings.BACKUP_DIR)
    backup_dir.mkdir(parents=True, exist_ok=True)
    zip_path = backup_dir / f"omnikeep-{label}-{stamp}.zip"
    with tempfile.TemporaryDirectory(prefix="snapshot-", dir=backup_dir) as tmp_dir:
        _make_zip(_snapshot_db(Path(tmp_dir)), zip_path)
    return zip_path


def run_backup() -> Dict[str, Any]:
    sink = settings.BACKUP_SINK.lower()
    if sink == "off":
        return {"status": "skipped", "sink": sink}
    if sink not in ("local", "rclone", "git"):
        raise ValueError("Unsupported backup sink")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    zip_path = Path(settings.BACKUP_DIR) / f"omnikeep-backup-{stamp}.zip"
    ownership = FileLock(Path(settings.BACKUP_DIR) / ".backup.lock")
    if not ownership.acquire():
        return {"status": "busy", "sink": sink}
    try:
        Path(settings.BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        _compact_database()
        with tempfile.TemporaryDirectory(prefix="snapshot-", dir=settings.BACKUP_DIR) as tmp_dir:
            snap = _snapshot_db(Path(tmp_dir))
            size = _make_zip(snap, zip_path)
        if sink == "rclone":
            _rclone_push(zip_path)
        elif sink == "git":
            _git_push(zip_path)
        # Retain the local snapshot; rotate only after remote delivery succeeded.
        _rotate_local(max(1, settings.BACKUP_KEEP))
        rec = log_backup_run(sink, "ok", str(zip_path), size)
        return {"status": "ok", **rec}
    except Exception as e:
        rec = log_backup_run(sink, "failed", str(zip_path), 0, error=type(e).__name__)
        return {"status": "failed", **rec}
    finally:
        ownership.release()


# ── Restore ──────────────────────────────────────────────────────

class RestoreError(RuntimeError):
    """The source cannot be restored, or restoring now would be unsafe."""


# Names used inside archives and set-aside folders, whatever DATABASE_PATH is called.
_DB_NAMES = ("omnikeep.db", "omnikeep.db-wal", "omnikeep.db-shm")


def _live_db_files() -> List[Path]:
    db = Path(settings.DATABASE_PATH)
    return [db, Path(f"{db}-wal"), Path(f"{db}-shm")]


def _check_archive(archive: zipfile.ZipFile) -> Dict[str, Any]:
    names = archive.namelist()
    if "omnikeep.db" not in names:
        raise RestoreError("Not an OmniKeep backup: omnikeep.db is missing")
    snapshots = []
    for name in names:
        if name in ("omnikeep.db", "backup.json"):
            continue
        folder, _, file = name.partition("/")
        # Anything else (absolute paths, "..", other folders) is refused, never extracted.
        if folder != "snapshots" or not _SNAPSHOT_NAME.match(file):
            raise RestoreError(f"Unexpected entry in backup: {name!r}")
        snapshots.append(file)
    try:
        meta = json.loads(archive.read("backup.json")) if "backup.json" in names else {"format": 1}
    except ValueError as exc:
        raise RestoreError("backup.json is unreadable") from exc
    return {"format": meta.get("format", 1), "app_version": meta.get("app_version", ""),
            "created_at": meta.get("created_at", ""), "snapshots": sorted(set(snapshots))}


def inspect_backup(source) -> Dict[str, Any]:
    """What a backup archive or set-aside folder holds, without touching any data."""
    source = Path(source)
    if source.is_dir():
        if not (source / "omnikeep.db").is_file():
            raise RestoreError(f"{source} holds no omnikeep.db")
        snap_dir = source / "snapshots"
        snapshots = sorted(p.name for p in snap_dir.iterdir() if _SNAPSHOT_NAME.match(p.name)) \
            if snap_dir.is_dir() else []
        return {"format": "set-aside folder", "app_version": "", "created_at": "", "snapshots": snapshots}
    with zipfile.ZipFile(source) as archive:
        return _check_archive(archive)


def _stage_database(source: Path, staging: Path) -> int:
    """Copy the source database into staging as one self-contained, checked file; return its item count."""
    staged = staging / "omnikeep.db"
    if source.is_dir():
        for name in _DB_NAMES[:2]:  # the -shm index is rebuilt by SQLite
            if (source / name).is_file():
                shutil.copy2(source / name, staging / name)
    else:
        with zipfile.ZipFile(source) as archive, archive.open("omnikeep.db") as src, staged.open("wb") as dst:
            shutil.copyfileobj(src, dst)
    try:
        with closing(sqlite3.connect(str(staged))) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # fold a copied WAL into the file
            result = conn.execute("PRAGMA integrity_check").fetchall()
            items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    except sqlite3.DatabaseError as exc:
        raise RestoreError(f"The backup's database is unreadable ({exc})") from exc
    if result != [("ok",)]:
        raise RestoreError(f"The backup's database failed integrity_check: {result[:3]}")
    return items


def _set_aside_database(keep: Path) -> List[Tuple[Path, Path]]:
    """Move the live database files into keep/. WAL files go first and are never left
    behind: a stray -wal would be replayed onto the restored database and corrupt it."""
    moved = []
    try:
        for live, name in reversed(list(zip(_live_db_files(), _DB_NAMES))):
            if live.exists():
                keep.mkdir(parents=True, exist_ok=True)
                shutil.move(str(live), keep / name)
                moved.append((keep / name, live))
    except BaseException:
        _put_back(moved)
        raise
    return moved


def _put_back(moved: List[Tuple[Path, Path]]) -> None:
    for kept, live in reversed(moved):
        shutil.move(str(kept), live)


def _restore_snapshots(source: Path, names: List[str], keep: Path) -> int:
    """Write the source's snapshots back by name. A differing file already in place is
    moved into keep/snapshots/ first; snapshot files the source lacks are left alone."""
    snap_dir = Path(settings.SNAPSHOT_DIR)
    written = 0
    archive = None if source.is_dir() else zipfile.ZipFile(source)
    try:
        for name in names:
            data = (source / "snapshots" / name).read_bytes() if archive is None \
                else archive.read(f"snapshots/{name}")
            target = snap_dir / name
            if target.is_file() and not target.is_symlink() and target.read_bytes() == data:
                continue
            if target.exists() or target.is_symlink():
                (keep / "snapshots").mkdir(parents=True, exist_ok=True)
                shutil.move(str(target), keep / "snapshots" / name)
            snap_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            written += 1
    finally:
        if archive is not None:
            archive.close()
    return written


def restore_backup(source) -> Dict[str, Any]:
    """Put a backup's database and snapshots back in place.

    `source` is a backup archive (format 1 or 2) or an omnikeep-prerestore-<stamp>
    folder left by an earlier restore. OmniKeep must be stopped: holding the queue
    worker's lock proves no server owns this database and keeps one from starting
    meanwhile. Whatever gets replaced is moved, not deleted, into
    BACKUP_DIR/omnikeep-prerestore-<stamp>/; restoring that folder undoes this restore.
    """
    source = Path(source).resolve()
    info = inspect_backup(source)
    ownership = FileLock(f"{settings.DATABASE_PATH}.worker.lock")
    if not ownership.acquire():
        raise RestoreError("OmniKeep is running on this database; stop it before restoring")
    try:
        backup_dir = Path(settings.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)
        keep = backup_dir / f"omnikeep-prerestore-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}"
        with tempfile.TemporaryDirectory(prefix="restore-", dir=backup_dir) as tmp:
            items = _stage_database(source, Path(tmp))
            moved = _set_aside_database(keep)
            db = Path(settings.DATABASE_PATH)
            try:
                db.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(Path(tmp) / "omnikeep.db", db)
            except BaseException:
                db.unlink(missing_ok=True)  # a partial copy of the staged file
                _put_back(moved)
                raise
        snapshots = _restore_snapshots(source, info["snapshots"], keep)
        return {"status": "ok", "source": str(source), **info, "snapshots": len(info["snapshots"]),
                "items": items, "snapshots_written": snapshots,
                "set_aside": str(keep) if keep.exists() else None}
    finally:
        ownership.release()


def last_successful_date() -> Optional[str]:
    from app.database import get_db_connection
    with closing(get_db_connection()) as conn:
        row = conn.execute("SELECT created_at FROM backup_runs WHERE status = 'ok' ORDER BY julianday(created_at) DESC LIMIT 1").fetchone()
    if row:
        stamp = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone().date().isoformat()
    return None


async def run_backup_async():
    # Cancelling to_thread does not stop SQLite/file I/O; join it before shutdown.
    task = asyncio.create_task(asyncio.to_thread(run_backup))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


async def backup_loop(interval_seconds: int = 1800) -> None:
    """Daily scheduler: fire on the first tick at/after BACKUP_HOUR local time."""
    from app.main import logger  # avoid import cycle at module load
    done_for = None
    while True:
        try:
            done_for = last_successful_date() or done_for
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            if now.hour >= settings.BACKUP_HOUR and done_for != today and settings.BACKUP_SINK != "off":
                logger.info("Backup window reached (%s >= %02d) — running %s backup",
                            today, settings.BACKUP_HOUR, settings.BACKUP_SINK)
                result = await run_backup_async()
                if result.get("status") == "ok":
                    done_for = today
                else:
                    done_for = None  # retry next tick
                    await asyncio.sleep(600)
                    continue
        except Exception:
            logger.exception("Backup loop iteration failed")
        await asyncio.sleep(interval_seconds)
