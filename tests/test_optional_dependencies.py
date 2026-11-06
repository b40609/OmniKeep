"""Every third-party import is declared, and the optional ones fail with a hint instead of silently.

playwright is installed on Windows only (requirements.txt marker); faster-whisper lives in
requirements-stt.txt (docs/optional_features.md)."""
import logging
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from packaging.requirements import Requirement

from app.parsers import cookie_manager, reel
from app.routers import session

REPO = Path(__file__).resolve().parents[1]


def _requirements(name):
    reqs = {}
    for line in (REPO / name).read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            req = Requirement(line)
            reqs[req.name.lower()] = req
    return reqs


def test_deptry_finds_no_undeclared_or_unused_packages():
    pytest.importorskip("deptry")
    res = subprocess.run(
        [sys.executable, "-m", "deptry", ".",
         "--requirements-files", "requirements.txt,requirements-stt.txt",
         "--requirements-files-dev", "requirements-dev.txt",
         "--known-first-party", "app",
         "--extend-exclude", r"frontend|static|\.agents|\.claude|\.codex|\.impeccable|_bmad.*",
         # FastAPI parses form uploads with it; nothing imports it by name.
         "--per-rule-ignores", "DEP002=python-multipart"],
        cwd=REPO, capture_output=True, text=True, timeout=120,
    )
    assert res.returncode == 0, res.stdout + res.stderr


def test_playwright_is_declared_for_windows_only():
    playwright = _requirements("requirements.txt")["playwright"]
    assert playwright.marker.evaluate({"sys_platform": "win32"})
    assert not playwright.marker.evaluate({"sys_platform": "linux"})
    # route_web_socket (app/parsers/web.py) arrived in 1.48.
    assert playwright.specifier.contains("1.48.0") and not playwright.specifier.contains("1.47.0")


def test_speech_to_text_stays_out_of_the_base_install():
    base, stt = _requirements("requirements.txt"), _requirements("requirements-stt.txt")
    assert {"faster-whisper", "ctranslate2"} <= set(stt)
    assert not {"faster-whisper", "ctranslate2"} & set(base)


@pytest.fixture
def no_playwright(monkeypatch):
    monkeypatch.setitem(sys.modules, "playwright", None)  # find_spec -> None, import -> ImportError
    assert not cookie_manager.playwright_installed()


async def test_login_without_playwright_explains_instead_of_launching_chrome(monkeypatch, no_playwright):
    launches = []
    monkeypatch.setattr(session, "ensure_cdp_browser", lambda **kw: launches.append(kw) or True)
    with pytest.raises(HTTPException) as err:
        await session.session_login(session.LoginRequest(platform="instagram"))
    assert err.value.status_code == 503
    assert "playwright" in err.value.detail and "cookies.txt" in err.value.detail
    assert launches == []


def test_status_reports_missing_playwright(monkeypatch, no_playwright):
    monkeypatch.setattr(session, "_cdp_reachable", lambda port, timeout: True)
    monkeypatch.setattr(session, "_fetch_cdp_cookies", lambda: pytest.fail("needs playwright"))
    bridge = session._bridge_snapshot()
    assert bridge["playwright_installed"] is False
    assert bridge["mode"] == "none"


def test_cookie_bridge_does_not_launch_chrome_without_playwright(monkeypatch, no_playwright):
    monkeypatch.setattr(cookie_manager, "ensure_cdp_browser", lambda **kw: pytest.fail("launched Chrome"))
    assert cookie_manager.get_cookies_via_cdp() is None


def test_close_managed_browser_without_playwright_leaves_chrome_alone(no_playwright):
    class Chrome:
        def wait(self, timeout):
            pytest.fail("waited on a Chrome it never asked to close")
    assert cookie_manager._close_managed_browser(Chrome()) is False


def test_missing_faster_whisper_turns_local_stt_off_with_a_hint(monkeypatch, caplog, isolated_runtime):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)
    monkeypatch.setattr(reel, "_local_whisper_model", None)
    monkeypatch.setattr(reel.subprocess, "run", lambda *a, **k: pytest.fail("ran ffmpeg"))
    audio = isolated_runtime / "clip.mp3"
    audio.write_bytes(b"x")
    with caplog.at_level(logging.WARNING, logger="omnikeep.reel"):
        assert reel.get_local_whisper_model() is None
        assert reel.transcribe_local_whisper(str(audio)) == ""
    hints = [r.getMessage() for r in caplog.records if "requirements-stt.txt" in r.getMessage()]
    assert len(hints) == 1  # logged once, then remembered
