"""Which commit this process started from, read once at startup (2026-11-26 review A-14, B-06).

/health reports it so "is production running what was pushed" can be checked by a machine
(scripts/check_deployed.py) instead of being assumed.
"""
from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
_SHA = re.compile(r"[0-9a-f]{40}")


def _git(repo: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                                timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def read_commit(repo: Path = REPO_ROOT) -> tuple[str | None, bool | None]:
    """(commit, dirty). OMNIKEEP_COMMIT wins (the Docker image has no .git); dirty is None
    when it is not known. Only tracked files count as dirty: logs and the database are untracked."""
    env = (os.environ.get("OMNIKEEP_COMMIT") or "").strip().lower()
    if _SHA.fullmatch(env):
        return env, None
    if not (repo / ".git").exists():
        return None, None
    head = (_git(repo, "rev-parse", "HEAD") or "").strip()
    if not _SHA.fullmatch(head):
        return None, None
    status = _git(repo, "status", "--porcelain", "--untracked-files=no")
    return head, (None if status is None else bool(status.strip()))


STARTUP_COMMIT, STARTUP_DIRTY = read_commit()
STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")
