"""Bootstrap isolation before test modules import application singletons."""
import ipaddress
import os
import socket
import sys
import tempfile
import threading
from pathlib import Path

import pytest

# No test may contact a provider, Telegram, browser bridge, or real host — not even
# loopback, where Ollama or the live OmniKeep server may be listening. The guard is
# installed at import, before collection, so module imports and every fixture run
# under it too. Only socket.socketpair() may connect: on Windows it is built from a
# loopback connect, and asyncio's self-pipe depends on it.
NETWORK_BLOCKED = "External connections are disabled in unit tests"
DNS_BLOCKED = "DNS lookups are disabled in unit tests"
EXPECTS_REFUSALS = "network_refusals_expected"
_guard_state = threading.local()
# Refusals seen during the current test. Code under test often swallows the
# OSError, so isolated_runtime fails the test instead: stub the client/provider.
_refusals = []


def _refuse(address):
    _refusals.append(f"connect {address!r}")
    raise OSError(f"{NETWORK_BLOCKED}: {address!r}")


def _host_text(host):
    return host.decode("ascii", "replace") if isinstance(host, (bytes, bytearray)) else host


def _resolves_locally(host):
    """Names whose forward lookup needs no DNS server: numeric, localhost, passive."""
    host = _host_text(host)
    if host is None or host == "" or host.lower().rstrip(".") == "localhost":
        return True
    try:
        ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        return False
    return True


def _is_loopback(host):
    host = _host_text(host)
    if host.lower().rstrip(".") == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.split("%", 1)[0]).is_loopback
    except ValueError:
        return False


def _install_network_guard():
    original_socketpair = socket.socketpair
    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo
    original_gethostbyname = socket.gethostbyname
    original_gethostbyname_ex = socket.gethostbyname_ex
    original_gethostbyaddr = socket.gethostbyaddr
    original_getnameinfo = socket.getnameinfo

    def internal():
        return getattr(_guard_state, "socketpair", False)

    def socketpair(*args, **kwargs):
        _guard_state.socketpair = True
        try:
            return original_socketpair(*args, **kwargs)
        finally:
            _guard_state.socketpair = False

    def connect(sock, address):
        if internal():
            return original_connect(sock, address)
        _refuse(address)

    def connect_ex(sock, address):
        if internal():
            return original_connect_ex(sock, address)
        _refuse(address)

    def sendto(sock, data, *args):  # sendto(data, address) / sendto(data, flags, address)
        _refuse(args[-1] if args else None)

    def no_dns(host):
        _refusals.append(f"DNS {_host_text(host)!r}")
        raise socket.gaierror(socket.EAI_NONAME, f"{DNS_BLOCKED}: {_host_text(host)!r}")

    def getaddrinfo(host, *args, **kwargs):
        if not _resolves_locally(host):
            no_dns(host)
        return original_getaddrinfo(host, *args, **kwargs)

    def gethostbyname(host):
        if not _resolves_locally(host):
            no_dns(host)
        return original_gethostbyname(host)

    def gethostbyname_ex(host):
        if not _resolves_locally(host):
            no_dns(host)
        return original_gethostbyname_ex(host)

    def gethostbyaddr(host):  # reverse lookups query DNS even for numeric input
        if not _is_loopback(host):
            no_dns(host)
        return original_gethostbyaddr(host)

    def getnameinfo(sockaddr, flags):
        if not (flags & socket.NI_NUMERICHOST or _is_loopback(sockaddr[0])):
            no_dns(sockaddr[0])
        return original_getnameinfo(sockaddr, flags)

    # Module attributes are what socket.create_connection, http.client, asyncio's
    # loop.getaddrinfo and anyio look up at call time.
    socket.socketpair = socketpair
    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = gethostbyname
    socket.gethostbyname_ex = gethostbyname_ex
    socket.gethostbyaddr = gethostbyaddr
    socket.getnameinfo = getnameinfo
    # Every socket.socket (ssl.SSLSocket included) and the selector event loop's
    # sock_connect / create_connection / datagram transports go through these.
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.socket.sendto = sendto

    if sys.platform == "win32":
        # The Proactor loop (Windows default) connects with overlapped ConnectEx
        # (TCP) or WSAConnect (UDP) inside IocpProactor and never calls
        # socket.socket.connect; unconnected UDP goes out through WSASendTo.
        from asyncio import windows_events

        proactor = windows_events.IocpProactor
        original_proactor_connect = proactor.connect
        original_proactor_sendto = proactor.sendto

        def proactor_connect(self, conn, address):
            if internal():
                return original_proactor_connect(self, conn, address)
            _refuse(address)

        def proactor_sendto(self, conn, buf, flags=0, addr=None):
            if addr is not None:
                _refuse(addr)
            return original_proactor_sendto(self, conn, buf, flags, addr)

        proactor.connect = proactor_connect
        proactor.sendto = proactor_sendto


_install_network_guard()

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


def pytest_configure(config):
    config.addinivalue_line(
        "markers", f"{EXPECTS_REFUSALS}: the test deliberately hits the network guard")


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, request):
    from app.config import settings
    from app import database
    from app.parsers import cookie_manager

    root = Path(tempfile.mkdtemp(prefix="case-", dir=_SESSION)).resolve()
    monkeypatch.setattr(settings, "DATABASE_PATH", str(root / "test.db"))
    monkeypatch.setattr(settings, "BACKUP_DIR", str(root / "backups"))
    monkeypatch.setattr(settings, "SNAPSHOT_DIR", str(root / "snapshots"))
    monkeypatch.setattr(settings, "BACKUP_SINK", "off")
    monkeypatch.setattr(settings, "BROWSER_COOKIE_FILE", str(root / "cookies.txt"))
    monkeypatch.setattr(settings, "BROWSER_CDP_PROFILE_DIR", str(root / "chrome"))
    monkeypatch.setattr(settings, "BROWSER_CDP_AUTOLAUNCH", False)
    monkeypatch.setattr(settings, "BACKGROUND_SERVICES_ENABLED", False)
    monkeypatch.setattr(cookie_manager, "ensure_cdp_browser", lambda: False)
    monkeypatch.setattr(cookie_manager, "_cached_jar", None)
    monkeypatch.setattr(cookie_manager, "_cached_jar_time", 0)
    monkeypatch.setattr(cookie_manager.yt_dlp.cookies, "load_cookies", lambda *a, **k: None)
    # The network guard is installed once at import (see _install_network_guard).
    database.init_db()
    _refusals.clear()
    yield root
    # Values saved through the settings page are applied onto the shared `settings`
    # object; undo them before monkeypatch restores its own originals.
    from app.app_settings import restore_baseline
    restore_baseline()
    attempts, _refusals[:] = list(_refusals), []
    if attempts and not request.node.get_closest_marker(EXPECTS_REFUSALS):
        pytest.fail("test tried to reach the network (refused by the conftest guard): "
                    + ", ".join(dict.fromkeys(attempts))
                    + " — stub the provider/client instead", pytrace=False)
