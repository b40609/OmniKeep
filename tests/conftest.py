"""Bootstrap isolation before test modules import application singletons."""
import os
import socket
import tempfile
import threading
from pathlib import Path

import pytest

_ROOT = Path(__file__).parent / ".tmp"
_ROOT.mkdir(exist_ok=True)
_SESSION = Path(tempfile.mkdtemp(prefix="pytest-", dir=_ROOT)).resolve()
os.environ.update({
    "OMNIKEEP_TESTING": "1",
    "OMNIKEEP_TEST_ROOT": str(_SESSION),
    "DATABASE_PATH": str(_SESSION / "collection.db"),
    "BACKUP_DIR": str(_SESSION / "backups"),
    "BACKUP_SINK": "off",
    "API_KEY": "test-only-credential-never-used-in-production",
    "BROWSER_COOKIE_FILE": str(_SESSION / "cookies.txt"),
    "BROWSER_CDP_AUTOLAUNCH": "false",
    "TELEGRAM_BOT_TOKEN": "",
    "LINE_CHANNEL_ACCESS_TOKEN": "",
    "LINE_CHANNEL_SECRET": "",
    "OPENAI_API_KEY": "",
    "GEMINI_API_KEYS": "",
    "GITHUB_TOKEN": "",
})


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, request):
    from app.config import settings
    from app import database
    from app.parsers import cookie_manager

    root = Path(tempfile.mkdtemp(prefix="case-", dir=_SESSION)).resolve()
    monkeypatch.setattr(settings, "DATABASE_PATH", str(root / "test.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(root / "backups"))
    monkeypatch.setattr(settings, "BACKUP_SINK", "off")
    monkeypatch.setattr(settings, "BROWSER_COOKIE_FILE", str(root / "cookies.txt"))
    monkeypatch.setattr(settings, "BROWSER_CDP_PROFILE_DIR", str(root / "chrome"))
    monkeypatch.setattr(settings, "BROWSER_CDP_AUTOLAUNCH", False)
    monkeypatch.setattr(settings, "BACKGROUND_SERVICES_ENABLED", False)
    monkeypatch.setattr(cookie_manager, "ensure_cdp_browser", lambda: False)
    monkeypatch.setattr(cookie_manager, "_cached_jar", None)
    monkeypatch.setattr(cookie_manager, "_cached_jar_time", 0)
    monkeypatch.setattr(cookie_manager.yt_dlp.cookies, "load_cookies", lambda *a, **k: None)
    # No test may contact a provider, Telegram, browser bridge, or real host.
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_socketpair = socket.socketpair
    internal = threading.local()

    def socketpair(*args, **kwargs):
        internal.socketpair = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            internal.socketpair = False

    def blocked_connect(sock, *args, **kwargs):
        if getattr(internal, "socketpair", False):
            return original_connect(sock, *args, **kwargs)
        raise OSError("External connections are disabled in unit tests")

    def blocked_connect_ex(sock, *args, **kwargs):
        if getattr(internal, "socketpair", False):
            return original_connect_ex(sock, *args, **kwargs)
        raise OSError("External connections are disabled in unit tests")

    monkeypatch.setattr(socket, "socketpair", socketpair)
    monkeypatch.setattr(socket.socket, "connect", blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked_connect_ex)
    database.init_db()
    yield root
