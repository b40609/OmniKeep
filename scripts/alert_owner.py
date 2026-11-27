"""Send an owner notification through OmniKeep's existing channels (2026-11-26 review A-08).

Called by scripts/watchdog.ps1 after restarting a hung process, using ASCII-only CLI flags
so Windows PowerShell 5.1 never mangles Traditional Chinese text.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app import owner_alert  # noqa: E402

SERVICE_LABELS = {
    "omnikeep": "OmniKeep 服務",
    "gateway": "OmniKeep AI 閘道",
}


def build_watchdog_restart_message(
    service: str,
    old_pids: str,
    new_pid: str,
    failures: int,
    recovered: bool,
) -> tuple[str, str]:
    label = SERVICE_LABELS.get(service.lower(), service)
    title = f"{label}無回應，已自動重啟"
    status_line = (
        f"已啟動新行程（PID {new_pid or '未知'}）並已恢復健康檢查。"
        if recovered
        else f"已嘗試啟動新行程（PID {new_pid or '未啟動'}），但健康檢查尚未通過，請檢視 watchdog.log。"
    )
    body = (
        f"連續 {failures} 次健康檢查逾時無回應，watchdog 已終止卡住的行程（PID {old_pids or '未知'}）。\n"
        f"{status_line}"
    )
    return title, body


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Notify OmniKeep owner via configured channels.")
    parser.add_argument("--event", choices=["watchdog-restart", "custom"], default="custom")
    parser.add_argument("--service", default="omnikeep")
    parser.add_argument("--old-pids", default="")
    parser.add_argument("--new-pid", default="")
    parser.add_argument("--failures", type=int, default=3)
    parser.add_argument("--recovered", default="false")
    parser.add_argument("--title", default="")
    parser.add_argument("--body", default="")
    parser.add_argument("--key", default="")
    parser.add_argument("--tag", default="omnikeep-watchdog")
    args = parser.parse_args(argv)

    if args.event == "watchdog-restart":
        recovered = args.recovered.strip().lower() in {"1", "true", "yes", "ok"}
        title, body = build_watchdog_restart_message(
            service=args.service,
            old_pids=args.old_pids,
            new_pid=args.new_pid,
            failures=args.failures,
            recovered=recovered,
        )
    else:
        title = args.title.strip()
        body = args.body.strip()
        if not title or not body:
            print("alert_owner: --title and --body are required for custom events", file=sys.stderr)
            return 2

    if args.key.strip():
        asyncio.run(owner_alert.alert_once_async(args.key.strip(), title, body, tag=args.tag))
    else:
        asyncio.run(owner_alert.send(title, body, tag=args.tag))
    return 0


if __name__ == "__main__":
    sys.exit(main())
