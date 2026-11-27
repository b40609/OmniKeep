"""Is the running service on the commit that was pushed? Read-only (2026-11-26 review A-14, B-06).

Compares, and exits 1 when any of them disagree:
  - local HEAD and origin/<branch> (pushed?)
  - the commit /health reports (read once when the process started) and HEAD (restarted?)
  - the latest GitHub Actions CI run for HEAD, when `gh` is available (green?)

Usage: python scripts/check_deployed.py [--url http://127.0.0.1:5000] [--no-ci]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True, check=True).stdout.strip()


def ci_conclusion(sha: str) -> str:
    gh = shutil.which("gh")
    if not gh:
        return "unknown (gh not installed)"
    result = subprocess.run([gh, "run", "list", "--commit", sha, "--workflow", "ci.yml", "--limit", "1",
                             "--json", "status,conclusion"], cwd=REPO, capture_output=True, text=True)
    if result.returncode != 0:
        return f"unknown (gh: {result.stderr.strip()[:120]})"
    runs = json.loads(result.stdout or "[]")
    if not runs:
        return "none"
    run = runs[0]
    return run.get("conclusion") or run.get("status") or "unknown"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=f"http://127.0.0.1:{os.environ.get('PORT', '5000')}")
    parser.add_argument("--no-ci", action="store_true")
    args = parser.parse_args()

    problems: list[str] = []
    head = git("rev-parse", "HEAD")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    try:
        upstream = git("rev-parse", f"origin/{branch}")
    except subprocess.CalledProcessError:
        upstream = None
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    print(f"HEAD            {head} ({branch}{', uncommitted changes' if dirty else ''})")
    print(f"origin/{branch:<8} {upstream}")
    if upstream != head:
        problems.append(f"HEAD is not origin/{branch} (not pushed, or behind)")

    try:
        with urllib.request.urlopen(f"{args.url}/health", timeout=10) as response:
            health = json.load(response)
    except OSError as exc:
        health = {}
        problems.append(f"/health did not answer: {exc}")
    running = health.get("commit")
    print(f"/health commit  {running} (started {health.get('started_at')}, dirty {health.get('commit_dirty')})")
    if health and running != head:
        problems.append("the running process did not start from HEAD (restart it)")
    if health.get("commit_dirty"):
        problems.append("the running process started from a working tree with uncommitted changes")

    if not args.no_ci:
        ci = ci_conclusion(head)
        print(f"CI for HEAD     {ci}")
        if ci != "success":
            problems.append(f"CI for HEAD is {ci}")

    for p in problems:
        print(f"NOT OK: {p}")
    if not problems:
        print("OK: production runs the pushed HEAD" + ("" if args.no_ci else " and its CI is green"))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
