"""Multi-sink backup for the second brain (single SQLite file + FTS).

Sinks (BACKUP_SINK in .env) — self-hosters pick what they have:
  local  rotating zip snapshots into BACKUP_DIR (default, zero deps)
  rclone one binary covers 40+ cloud backends (GDrive/OneDrive/Dropbox/S3/B2/WebDAV…)
  git    auto-commit the snapshot into a private repo clone (versioned history)
  off    disabled
The DB snapshot is taken via sqlite3's online-backup API so a live WAL
database is copied consistently without stopping the server.
"""
import asyncio
import shutil
import sqlite3
import subprocess
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.config import settings
from app.database import log_backup_run, get_backup_runs


def _snapshot_db(tmp_dir: Path) -> Path:
    """Consistent copy of a live WAL database via the sqlite3 backup API."""
    snap = tmp_dir / "omnikeep.db"
    src = sqlite3.connect(settings.DATABASE_PATH)
    dst = sqlite3.connect(str(snap))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    return snap


def _make_zip(snap_db: Path, zip_path: Path) -> int:
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(snap_db, "omnikeep.db")
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
    for args in (["git", "-C", str(repo_dir), "add", "."],
                 ["git", "-C", str(repo_dir), "commit", "-m", f"omnikeep backup {zip_path.stem}"],
                 ["git", "-C", str(repo_dir), "push"]):
        res = subprocess.run(args, capture_output=True, text=True, timeout=300)
        if res.returncode != 0 and "nothing to commit" not in res.stdout:
            raise RuntimeError(f"git step failed: {res.stderr[:400]}")


def run_backup() -> Dict[str, Any]:
    sink = settings.BACKUP_SINK.lower()
    if sink == "off":
        return {"status": "skipped", "sink": sink}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    zip_path = Path(settings.BACKUP_DIR) / f"omnikeep-backup-{stamp}.zip"
    tmp_dir = Path(settings.BACKUP_DIR) / ".tmp"
    try:
        tmp_dir.mkdir(parents=True, exist_ok=True)
        Path(settings.BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        snap = _snapshot_db(tmp_dir)
        size = _make_zip(snap, zip_path)
        _rotate_local(settings.BACKUP_KEEP)
        if sink == "rclone":
            _rclone_push(zip_path)
        elif sink == "git":
            _git_push(zip_path)
        if sink in ("rclone", "git"):
            zip_path.unlink(missing_ok=True)
        rec = log_backup_run(sink, "ok", str(zip_path), size)
        return {"status": "ok", **rec}
    except Exception as e:
        rec = log_backup_run(sink, "failed", str(zip_path), 0, error=str(e)[:500])
        return {"status": "failed", **rec}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def last_successful_date() -> Optional[str]:
    runs: List[Dict[str, Any]] = get_backup_runs(limit=20)
    for r in runs:
        if r.get("status") == "ok":
            return str(r.get("created_at", ""))[:10]
    return None


async def backup_loop(interval_seconds: int = 1800) -> None:
    """Daily scheduler: fire on the first tick at/after BACKUP_HOUR local time."""
    from app.main import logger  # avoid import cycle at module load
    done_for = last_successful_date()
    while True:
        try:
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            if now.hour >= settings.BACKUP_HOUR and done_for != today and settings.BACKUP_SINK != "off":
                logger.info("Backup window reached (%s >= %02d) — running %s backup",
                            today, settings.BACKUP_HOUR, settings.BACKUP_SINK)
                result = await asyncio.to_thread(run_backup)
                if result.get("status") == "ok":
                    done_for = today
                else:
                    done_for = None  # retry next tick
                    await asyncio.sleep(600)
                    continue
        except Exception:
            logger.exception("Backup loop iteration failed")
        await asyncio.sleep(interval_seconds)
