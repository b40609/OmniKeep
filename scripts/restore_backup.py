"""Restore an OmniKeep backup (database + HTML snapshots). Stop OmniKeep first.

  python scripts/restore_backup.py --list
  python scripts/restore_backup.py --latest
  python scripts/restore_backup.py backups/omnikeep-backup-20261104-040000-000000.zip
  python scripts/restore_backup.py backups/omnikeep-prerestore-20261104-101500-000000   (undo)

Paths come from .env / environment like the server's (DATABASE_PATH, SNAPSHOT_DIR,
BACKUP_DIR). Nothing is deleted: what gets replaced is moved into
BACKUP_DIR/omnikeep-prerestore-<stamp>/.
"""
import argparse
from pathlib import Path
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backup import RestoreError, inspect_backup, restore_backup  # noqa: E402
from app.config import settings  # noqa: E402


def _candidates():
    root = Path(settings.BACKUP_DIR)
    backups = sorted(root.glob("omnikeep-backup-*.zip"))
    undo = sorted(p for p in root.glob("omnikeep-prerestore-*") if p.is_dir())
    return backups, undo


def _describe(path: Path) -> str:
    info = inspect_backup(path)
    size = f"{path.stat().st_size / 1024:,.0f} KiB" if path.is_file() else "folder"
    made = f", made {info['created_at'][:19]} by {info['app_version']}" if info["created_at"] else ""
    return f"{path.name}  ({size}, format {info['format']}, {len(info['snapshots'])} snapshots{made})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("source", nargs="?", type=Path, help="backup .zip or omnikeep-prerestore-* folder")
    parser.add_argument("--latest", action="store_true", help="restore the newest backup in BACKUP_DIR")
    parser.add_argument("--list", action="store_true", help="list backups in BACKUP_DIR and exit")
    parser.add_argument("--yes", action="store_true", help="do not ask for confirmation")
    args = parser.parse_args()

    backups, undo = _candidates()
    if args.list:
        print(f"Backups in {settings.BACKUP_DIR}:")
        for path in backups + undo:
            print("  " + _describe(path))
        if not backups and not undo:
            print("  (none)")
        return 0

    if args.latest == bool(args.source):
        parser.error("give either a backup path or --latest")
    if args.latest:
        if not backups:
            print(f"No omnikeep-backup-*.zip in {settings.BACKUP_DIR}")
            return 1
        args.source = backups[-1]

    set_aside_before = set(undo)
    try:
        print(f"Restore  {_describe(args.source)}")
        print(f"Into     {settings.DATABASE_PATH}  (snapshots: {settings.SNAPSHOT_DIR})")
        if not args.yes:
            print("OmniKeep must be stopped, and scripts/watchdog.ps1's scheduled task disabled so it cannot restart it.")
            if input("Type 'restore' to continue: ").strip() != "restore":
                print("Cancelled; nothing changed.")
                return 1
        result = restore_backup(args.source)
    except (RestoreError, OSError, ValueError, zipfile.BadZipFile) as exc:
        print(f"Restore failed: {exc}")
        for folder in sorted(set(_candidates()[1]) - set_aside_before):
            print(f"Files replaced before the failure are in {folder}.")
        return 1
    print(f"Restored {result['items']} items and {result['snapshots']} snapshots "
          f"({result['snapshots_written']} written, the rest already identical).")
    if result["set_aside"]:
        print(f"The replaced files are in {result['set_aside']}; restore that folder to undo.")
    print("Start OmniKeep again when ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
