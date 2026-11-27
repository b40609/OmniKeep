"""Regression tests for monitoring guardrails (2026-11-26 review A-07, A-08).

Covers:
1. Telegram polling (A-07): skips a poison update after 5 consecutive failures,
   advances offset so subsequent messages keep flowing, and notifies the owner once.
2. scripts/alert_owner.py (A-08): invokes app.owner_alert through OmniKeep's
   existing owner channels without leaking secrets.
3. scripts/watchdog.ps1 (A-08): executed under real Windows PowerShell 5.1 against
   an isolated hanging dummy server, verifying it tolerates transient/startup states
   and restarts + alerts once consecutive failures reach the hang threshold.
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.telegram_bot import TelegramBot
from scripts import alert_owner

REPO = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_telegram_polling_skips_poison_update_after_five_failures_and_alerts_owner():
    """A-07: same update_id failing 5 times in a row is skipped, owner alerted once, next update processed."""
    bot = TelegramBot(token="test-bot-token")
    poll_calls = 0

    async def fake_get(url, params=None):
        nonlocal poll_calls
        poll_calls += 1
        offset = (params or {}).get("offset", 0)
        if poll_calls > 12:
            # Safety guard so an unfixed infinite replay loop fails fast instead of hanging pytest.
            bot.running = False
            return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "result": []})
        updates = [
            {
                "update_id": 100,
                "message": {"chat": {"id": 42}, "from": {"id": 42}, "text": "poison message"},
            },
            {
                "update_id": 101,
                "message": {"chat": {"id": 42}, "from": {"id": 42}, "text": "healthy message"},
            },
        ]
        pending = [u for u in updates if u["update_id"] >= offset]
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True, "result": pending})

    client = MagicMock(get=AsyncMock(side_effect=fake_get))
    bot.get_client = AsyncMock(return_value=client)

    seen: list[int] = []

    async def handle(update):
        uid = update["update_id"]
        seen.append(uid)
        if uid == 100:
            raise ValueError("persistent malformed payload")
        if uid == 101:
            bot.running = False

    bot.handle_update = handle
    alerts: list[tuple[str, str, str]] = []

    def fake_alert_once(key: str, title: str, body: str, tag: str | None = None) -> bool:
        alerts.append((key, title, body))
        return True

    with patch("app.bot.telegram_bot.asyncio.sleep", new=AsyncMock()), \
         patch("app.owner_alert.alert_once", side_effect=fake_alert_once):
        await bot.run_polling()

    assert seen == [100, 100, 100, 100, 100, 101]
    assert len(alerts) == 1
    alert_id, title, body = alerts[0]
    assert alert_id == "telegram-skip-100"
    assert "跳過" in title
    assert "100" in body
    assert "ValueError" in body


@pytest.mark.asyncio
async def test_telegram_polling_resets_failure_count_after_recovery():
    """Transient failure (<5 times) still replays and succeeds without alerting."""
    bot = TelegramBot(token="test-bot-token")
    attempts = 0

    async def fake_get(url, params=None):
        offset = (params or {}).get("offset", 0)
        updates = [{"update_id": 200}, {"update_id": 201}]
        return SimpleNamespace(
            status_code=200,
            json=lambda: {"ok": True, "result": [u for u in updates if u["update_id"] >= offset]},
        )

    bot.get_client = AsyncMock(return_value=MagicMock(get=AsyncMock(side_effect=fake_get)))

    async def handle(update):
        nonlocal attempts
        if update["update_id"] == 200:
            attempts += 1
            if attempts <= 4:
                raise RuntimeError("transient glitch")
        else:
            bot.running = False

    bot.handle_update = handle
    with patch("app.bot.telegram_bot.asyncio.sleep", new=AsyncMock()), \
         patch("app.owner_alert.alert_once") as alert_mock:
        await bot.run_polling()

    assert attempts == 5
    alert_mock.assert_not_called()


def test_alert_owner_cli_formats_watchdog_restart_and_calls_owner_alert(monkeypatch):
    sent: list[tuple[str, str, str]] = []

    async def fake_alert_once_async(key: str, title: str, body: str, tag: str | None = None):
        sent.append((key, title, body))
        return {"telegram": 1, "web_push": 0, "line": 0}

    monkeypatch.setattr("app.owner_alert.alert_once_async", fake_alert_once_async)
    rc = alert_owner.main([
        "--event", "watchdog-restart",
        "--service", "omnikeep",
        "--old-pids", "111,222",
        "--new-pid", "333",
        "--failures", "3",
        "--recovered", "true",
        "--key", "watchdog-test-1",
    ])
    assert rc == 0
    assert len(sent) == 1
    alert_id, title, body = sent[0]
    assert alert_id == "watchdog-test-1"
    assert "OmniKeep" in title and "重啟" in title
    assert "3" in body and "111,222" in body and "333" in body and "已恢復" in body


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.mark.skipif(sys.platform != "win32", reason="watchdog.ps1 is Windows-only")
def test_watchdog_restarts_hung_process_after_threshold_and_notifies(tmp_path):
    """Real Windows PowerShell 5.1 integration test for A-08 hung-process restart."""
    ps_exe = shutil.which("powershell.exe")
    if not ps_exe:
        pytest.skip("Windows PowerShell 5.1 not available")

    port = _free_port()
    proj = tmp_path / "proj"
    logs = tmp_path / "logs"
    scripts_dir = proj / "scripts"
    scripts_dir.mkdir(parents=True)
    logs.mkdir(parents=True)
    (proj / ".env").write_text(f"PORT={port}\n", encoding="utf-8")

    # Mode file: "hang" binds port but never answers HTTP; "healthy" answers /health 200.
    mode_file = tmp_path / "mode.txt"
    mode_file.write_text("hang", encoding="utf-8")
    started_pids_file = tmp_path / "started_pids.txt"
    alert_log = tmp_path / "alerts.jsonl"

    dummy_run = proj / "run.py"
    dummy_run.write_text(
        f"""import json, os, socket, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

mode = Path({str(mode_file)!r}).read_text(encoding="utf-8").strip()
with open({str(started_pids_file)!r}, "a", encoding="utf-8") as fh:
    fh.write(f"{{os.getpid()}}:{{mode}}\\n")

if mode == "hang":
    # Switch mode so the restarted process comes up healthy.
    Path({str(mode_file)!r}).write_text("healthy", encoding="utf-8")
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("127.0.0.1", {port}))
    sock.listen(5)
    # Deliberately never accept()/answer /health to simulate an event-loop deadlock.
    while True:
        time.sleep(1)
else:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({{"status": "healthy", "service": "OmniKeep"}}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, format, *args):
            pass
    HTTPServer(("127.0.0.1", {port}), Handler).serve_forever()
""",
        encoding="utf-8",
    )

    dummy_alert = scripts_dir / "alert_owner.py"
    dummy_alert.write_text(
        f"""import json, sys
with open({str(alert_log)!r}, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:]) + "\\n")
""",
        encoding="utf-8",
    )

    # Start the hung dummy run.py
    hung_proc = subprocess.Popen(
        [sys.executable, "-B", str(dummy_run)],
        cwd=str(proj),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    restarted_pids: list[int] = []
    try:
        # Wait briefly for hung process to bind the port
        deadline = time.time() + 10
        while not started_pids_file.exists() and time.time() < deadline:
            time.sleep(0.1)
        assert hung_proc.poll() is None

        env = os.environ.copy()
        env.update({
            "OMNIKEEP_WATCHDOG_ROOT": str(proj),
            "OMNIKEEP_WATCHDOG_LOG_DIR": str(logs),
            "OMNIKEEP_WATCHDOG_PYTHON": sys.executable,
            "OMNIKEEP_WATCHDOG_MUTEX_NAME": f"Local\\OmniKeep-Test-{port}",
            "OMNIKEEP_WATCHDOG_HANG_THRESHOLD": "3",
            "OMNIKEEP_WATCHDOG_STARTUP_GRACE_SECONDS": "0",
            "OMNIKEEP_WATCHDOG_HEALTH_TIMEOUT_SECONDS": "1",
            "OMNIKEEP_WATCHDOG_STARTUP_WAIT_ATTEMPTS": "10",
            "OMNIKEEP_WATCHDOG_SKIP_OLLAMA": "1",
        })

        def run_watchdog():
            ps_out = tmp_path / "watchdog.ps.out"
            ps_err = tmp_path / "watchdog.ps.err"
            # Redirect to files instead of pipes so the detached restarted server never holds pipes open.
            with ps_out.open("wb") as out_f, ps_err.open("wb") as err_f:
                res = subprocess.run(
                    [ps_exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                     "-File", str(REPO / "scripts" / "watchdog.ps1")],
                    env=env, stdout=out_f, stderr=err_f, timeout=45, check=False,
                )
            assert res.returncode == 0, (
                f"watchdog failed ({res.returncode}): "
                f"{ps_out.read_text(encoding='utf-8', errors='replace')}\n"
                f"{ps_err.read_text(encoding='utf-8', errors='replace')}"
            )

        # Runs 1 and 2: below threshold -> process must stay alive, no alert yet.
        run_watchdog()
        assert hung_proc.poll() is None
        assert not alert_log.exists()

        run_watchdog()
        assert hung_proc.poll() is None
        assert not alert_log.exists()

        # Run 3: reaches threshold (3/3) -> kills hung process, restarts healthy one, alerts owner.
        run_watchdog()
        assert hung_proc.wait(timeout=5) is not None

        lines = started_pids_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        assert lines[0].endswith(":hang")
        assert lines[1].endswith(":healthy")
        restarted_pids.append(int(lines[1].split(":")[0]))

        # Alert script must have been invoked once with restart details.
        assert alert_log.exists()
        alert_calls = [json.loads(line) for line in alert_log.read_text(encoding="utf-8").splitlines()]
        assert len(alert_calls) == 1
        argv = alert_calls[0]
        assert "--event" in argv and "watchdog-restart" in argv
        assert "--service" in argv and "omnikeep" in argv
        assert "--recovered" in argv and "true" in argv

        # Run 4: now healthy -> state failure counter stays reset to 0 and no second alert.
        run_watchdog()
        state = json.loads((logs / "watchdog-state.json").read_text(encoding="utf-8"))
        assert state["omnikeep"]["failures"] == 0
        assert len(alert_log.read_text(encoding="utf-8").splitlines()) == 1
    finally:
        if started_pids_file.exists():
            for line in started_pids_file.read_text(encoding="utf-8").splitlines():
                pid_str = line.split(":", 1)[0].strip()
                if pid_str.isdigit() and int(pid_str) != hung_proc.pid:
                    restarted_pids.append(int(pid_str))
        if hung_proc.poll() is None:
            hung_proc.terminate()
            try:
                hung_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                hung_proc.kill()
        for pid in set(restarted_pids):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True, check=False)


@pytest.mark.skipif(sys.platform != "win32", reason="watchdog.ps1 is Windows-only")
def test_watchdog_respects_startup_grace_window(tmp_path):
    """A freshly started process inside the startup grace window must not be killed."""
    ps_exe = shutil.which("powershell.exe")
    if not ps_exe:
        pytest.skip("Windows PowerShell 5.1 not available")

    port = _free_port()
    proj = tmp_path / "proj"
    logs = tmp_path / "logs"
    proj.mkdir(parents=True)
    logs.mkdir(parents=True)
    (proj / ".env").write_text(f"PORT={port}\n", encoding="utf-8")

    dummy_run = proj / "run.py"
    dummy_run.write_text("import time\nwhile True:\n    time.sleep(1)\n", encoding="utf-8")

    proc = subprocess.Popen(
        [sys.executable, "-B", str(dummy_run)],
        cwd=str(proj),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.5)
        env = os.environ.copy()
        env.update({
            "OMNIKEEP_WATCHDOG_ROOT": str(proj),
            "OMNIKEEP_WATCHDOG_LOG_DIR": str(logs),
            "OMNIKEEP_WATCHDOG_PYTHON": sys.executable,
            "OMNIKEEP_WATCHDOG_MUTEX_NAME": f"Local\\OmniKeep-Grace-{port}",
            "OMNIKEEP_WATCHDOG_HANG_THRESHOLD": "1",
            "OMNIKEEP_WATCHDOG_STARTUP_GRACE_SECONDS": "300",
            "OMNIKEEP_WATCHDOG_HEALTH_TIMEOUT_SECONDS": "1",
            "OMNIKEEP_WATCHDOG_SKIP_OLLAMA": "1",
        })
        ps_out = tmp_path / "grace.out"
        with ps_out.open("wb") as out_f:
            res = subprocess.run(
                [ps_exe, "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(REPO / "scripts" / "watchdog.ps1")],
                env=env, stdout=out_f, stderr=out_f, timeout=30, check=False,
            )
        assert res.returncode == 0
        assert proc.poll() is None
        assert "starting up" in (logs / "watchdog.log").read_text(encoding="utf-8")
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
