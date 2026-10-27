"""Cookie Bridge browser mode changes must never show a window automatically."""

from unittest.mock import Mock

import pytest
from fastapi import HTTPException

from app.config import settings
from app.parsers import cookie_manager
from app.parsers.cookie_manager import ensure_cdp_browser, restore_headless_cdp_browser
from app.routers import session


def _mock_cdp_launch(monkeypatch, tmp_path, *, initially_running=False):
    chrome = tmp_path / "chrome.exe"
    chrome.touch()
    monkeypatch.setattr(settings, "BROWSER_CDP_AUTOLAUNCH", True)
    monkeypatch.setattr(settings, "BROWSER_CDP_HEADLESS", True)
    monkeypatch.setattr(cookie_manager, "_CDP_LAUNCH_PATHS", [str(chrome)])
    state = {"up": initially_running, "launches": []}

    def popen(args, **kwargs):
        state["launches"].append((args, kwargs))
        state["up"] = True
        return Mock()

    monkeypatch.setattr(cookie_manager, "_cdp_reachable", lambda port: state["up"])
    monkeypatch.setattr(cookie_manager.subprocess, "Popen", popen)
    monkeypatch.setattr(cookie_manager.time, "sleep", lambda seconds: None)
    return state


def test_background_launch_is_headless(monkeypatch, isolated_runtime):
    state = _mock_cdp_launch(monkeypatch, isolated_runtime)
    assert ensure_cdp_browser() is True
    args, _ = state["launches"][0]
    assert "--headless=new" in args
    assert "--remote-debugging-address=127.0.0.1" in args
    assert f"--user-data-dir={settings.BROWSER_CDP_PROFILE_DIR}" in args
    assert ensure_cdp_browser() is True
    assert len(state["launches"]) == 1


def test_login_switches_headless_to_visible_using_same_profile(monkeypatch, isolated_runtime):
    state = _mock_cdp_launch(monkeypatch, isolated_runtime, initially_running=True)
    process = Mock()
    process.cmdline.return_value = ["chrome.exe", "--headless=new"]
    monkeypatch.setattr(cookie_manager, "_managed_cdp_browser", lambda: process)

    def close_managed(proc):
        assert proc is process
        state["up"] = False
        return True

    monkeypatch.setattr(cookie_manager, "_close_managed_browser", close_managed)
    assert ensure_cdp_browser(visible=True) is True
    args, _ = state["launches"][0]
    assert not any(a.startswith("--headless") for a in args)
    assert f"--user-data-dir={settings.BROWSER_CDP_PROFILE_DIR}" in args


def test_visible_login_reuses_existing_visible_browser(monkeypatch, isolated_runtime):
    state = _mock_cdp_launch(monkeypatch, isolated_runtime, initially_running=True)
    process = Mock()
    process.cmdline.return_value = ["chrome.exe", "--remote-debugging-port=9222"]
    monkeypatch.setattr(cookie_manager, "_managed_cdp_browser", lambda: process)
    assert ensure_cdp_browser(visible=True) is True
    assert state["launches"] == []


def test_login_does_not_close_unmanaged_cdp_browser(monkeypatch, isolated_runtime):
    state = _mock_cdp_launch(monkeypatch, isolated_runtime, initially_running=True)
    monkeypatch.setattr(cookie_manager, "_managed_cdp_browser", lambda: None)
    assert ensure_cdp_browser(visible=True) is False
    assert state["launches"] == []


def test_manual_login_available_when_autolaunch_disabled(monkeypatch, isolated_runtime):
    state = _mock_cdp_launch(monkeypatch, isolated_runtime)
    monkeypatch.setattr(settings, "BROWSER_CDP_AUTOLAUNCH", False)
    assert ensure_cdp_browser() is False
    assert state["launches"] == []
    assert ensure_cdp_browser(visible=True) is True
    assert "--headless=new" not in state["launches"][0][0]


def test_refresh_restores_background_after_manual_login(monkeypatch, isolated_runtime):
    state = _mock_cdp_launch(monkeypatch, isolated_runtime, initially_running=True)
    process = Mock()
    process.cmdline.return_value = ["chrome.exe", "--remote-debugging-port=9222"]
    monkeypatch.setattr(cookie_manager, "_managed_cdp_browser", lambda: process)

    def close_managed(proc):
        assert proc is process
        state["up"] = False
        return True

    monkeypatch.setattr(cookie_manager, "_close_managed_browser", close_managed)
    assert restore_headless_cdp_browser() is True
    assert "--headless=new" in state["launches"][0][0]


@pytest.mark.asyncio
async def test_refresh_endpoint_returns_to_background(monkeypatch):
    steps = []
    monkeypatch.setattr(session, "get_cookie_jar", lambda force: steps.append(("refresh", force)))
    monkeypatch.setattr(session, "restore_headless_cdp_browser", lambda: steps.append("headless") or True)
    monkeypatch.setattr(session, "_bridge_snapshot", lambda: {"mode": "cdp"})
    assert await session.session_refresh() == {"bridge": {"mode": "cdp"}}
    assert steps == [("refresh", True), "headless"]


@pytest.mark.asyncio
async def test_login_endpoint_requests_visible_chrome(monkeypatch):
    requested = []

    def ensure(*, visible=False):
        requested.append(visible)
        return False

    monkeypatch.setattr(session, "ensure_cdp_browser", ensure)
    with pytest.raises(HTTPException) as error:
        await session.session_login(session.LoginRequest(platform="instagram"))
    assert error.value.status_code == 503
    assert requested == [True]
