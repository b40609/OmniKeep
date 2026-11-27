"""/health says which commit the running process started from (2026-11-26 review A-14, B-06).

The production process ran code from 11-24 while main had moved on to 11-25, and nothing showed
it. The commit is read once at startup, so a later `git pull` on disk does not change what
/health reports until the process restarts — which is exactly the gap it has to expose.
"""
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from app import build_info
from app.main import app

REPO = Path(__file__).resolve().parents[1]


def _git_head() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                              text=True, timeout=10, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def test_health_reports_the_commit_read_at_startup():
    with TestClient(app) as client:
        body = client.get("/health").json()
    assert body["status"] == "healthy"
    assert "commit" in body and "started_at" in body
    head = _git_head()
    if head:
        assert body["commit"] == head


def test_commit_comes_from_the_environment_when_there_is_no_checkout(monkeypatch, tmp_path):
    # The Docker image has no .git; the build passes the commit in OMNIKEEP_COMMIT.
    monkeypatch.setenv("OMNIKEEP_COMMIT", "a" * 40)
    assert build_info.read_commit(tmp_path) == ("a" * 40, None)


def test_no_checkout_and_no_environment_reports_none(monkeypatch, tmp_path):
    monkeypatch.delenv("OMNIKEEP_COMMIT", raising=False)
    assert build_info.read_commit(tmp_path) == (None, None)


def test_dirty_working_tree_is_reported(monkeypatch, tmp_path):
    monkeypatch.delenv("OMNIKEEP_COMMIT", raising=False)
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "x"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("1", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=tmp_path, check=True)
    commit, dirty = build_info.read_commit(tmp_path)
    assert commit and len(commit) == 40
    assert dirty is True
