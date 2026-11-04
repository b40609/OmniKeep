"""The conftest network guard must hold on every connection path, sync and async.

Windows' default asyncio loop (Proactor) connects through overlapped ConnectEx and
never calls ``socket.socket.connect``; a guard on that method alone once let a
test send a fake key to a real provider. Every case here aims at a local listener
or a reserved address (192.0.2.0/24, ``.invalid``) so a broken guard cannot reach
anything real.
"""
import asyncio
import socket
import sys

import httpx
import pytest

pytestmark = pytest.mark.network_refusals_expected

BLOCKED_MARKERS = ("disabled in unit tests",)
EXTERNAL_IP = "192.0.2.1"  # RFC 5737 TEST-NET-1: documentation only, never routed
EXTERNAL_HOST = "omnikeep-test.invalid"  # RFC 2606: never resolves

LOOP_FACTORIES = [pytest.param(asyncio.SelectorEventLoop, id="selector")]
if sys.platform == "win32":
    LOOP_FACTORIES.append(pytest.param(asyncio.ProactorEventLoop, id="proactor"))


def _chain(exc):
    """Yield exc, its causes/contexts and ExceptionGroup members."""
    seen, stack = set(), [exc]
    while stack:
        item = stack.pop()
        if item is None or id(item) in seen:
            continue
        seen.add(id(item))
        yield item
        stack += [item.__cause__, item.__context__, *getattr(item, "exceptions", ())]


def _assert_guarded(exc):
    messages = [str(item) for item in _chain(exc)]
    assert any(marker in message for message in messages for marker in BLOCKED_MARKERS), (
        f"not stopped by the test network guard: {messages!r}")


@pytest.fixture
def listener():
    """A loopback TCP listener; it must never see a connection."""
    server = socket.create_server(("127.0.0.1", 0))
    server.setblocking(False)
    yield server
    try:
        peer, address = server.accept()
    except BlockingIOError:
        pass
    else:
        peer.close()
        pytest.fail(f"listener accepted a connection from {address}: guard leaked")
    finally:
        server.close()


def _run(factory, coro_fn):
    loop = factory()
    try:
        return loop.run_until_complete(coro_fn(loop))
    finally:
        loop.close()


# --- reproduction: async httpx on the default loop -------------------------

@pytest.mark.parametrize("url", [f"http://{EXTERNAL_IP}/", f"http://{EXTERNAL_HOST}/"],
                         ids=["ip-literal", "hostname"])
async def test_async_httpx_external_connection_is_blocked(url):
    async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
        with pytest.raises(httpx.TransportError) as caught:
            await client.get(url)
    _assert_guarded(caught.value)


async def test_async_httpx_loopback_connection_never_reaches_listener(listener):
    port = listener.getsockname()[1]
    async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
        with pytest.raises(httpx.TransportError) as caught:
            await client.get(f"http://127.0.0.1:{port}/")
    _assert_guarded(caught.value)


# --- asyncio primitives on both loop implementations -----------------------

@pytest.mark.parametrize("factory", LOOP_FACTORIES)
def test_loop_sock_connect_is_blocked(factory, listener):
    address = listener.getsockname()

    async def attempt(loop):
        with socket.socket() as sock:
            sock.setblocking(False)
            await loop.sock_connect(sock, address)

    with pytest.raises(OSError) as caught:
        _run(factory, attempt)
    _assert_guarded(caught.value)


@pytest.mark.parametrize("factory", LOOP_FACTORIES)
def test_loop_create_connection_is_blocked(factory, listener):
    host, port = listener.getsockname()

    async def attempt(loop):
        await loop.create_connection(asyncio.Protocol, host, port)

    with pytest.raises(OSError) as caught:
        _run(factory, attempt)
    _assert_guarded(caught.value)


@pytest.mark.parametrize("factory", LOOP_FACTORIES)
def test_loop_datagram_to_remote_is_blocked(factory):
    async def attempt(loop):
        await loop.create_datagram_endpoint(asyncio.DatagramProtocol,
                                            remote_addr=(EXTERNAL_IP, 53))

    with pytest.raises(OSError) as caught:
        _run(factory, attempt)
    _assert_guarded(caught.value)


@pytest.mark.parametrize("factory", LOOP_FACTORIES)
def test_loop_getaddrinfo_is_blocked(factory):
    async def attempt(loop):
        await loop.getaddrinfo(EXTERNAL_HOST, 443)

    with pytest.raises(OSError) as caught:
        _run(factory, attempt)
    _assert_guarded(caught.value)


# --- synchronous paths ------------------------------------------------------

def test_sync_connections_and_lookups_are_blocked(listener):
    with pytest.raises(OSError) as caught:
        socket.create_connection(listener.getsockname(), timeout=2)
    _assert_guarded(caught.value)

    with socket.socket() as sock, pytest.raises(OSError) as caught:
        sock.connect_ex(listener.getsockname())
    _assert_guarded(caught.value)

    for lookup in (lambda: socket.getaddrinfo(EXTERNAL_HOST, 443),
                   lambda: socket.gethostbyname(EXTERNAL_HOST),
                   lambda: socket.gethostbyname_ex(EXTERNAL_HOST),
                   lambda: socket.gethostbyaddr(EXTERNAL_IP)):
        with pytest.raises(OSError) as caught:
            lookup()
        _assert_guarded(caught.value)

    with pytest.raises(httpx.TransportError) as caught:
        httpx.get(f"http://{EXTERNAL_HOST}/", timeout=2.0, trust_env=False)
    _assert_guarded(caught.value)


def test_udp_sendto_is_blocked():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        with pytest.raises(OSError) as caught:
            sock.sendto(b"x", (EXTERNAL_IP, 53))
    _assert_guarded(caught.value)


# --- local plumbing the suite relies on must keep working ------------------

def test_socketpair_and_local_resolution_still_work():
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b"ping")
        assert right.recv(4) == b"ping"
    assert socket.getaddrinfo("127.0.0.1", 80)
    assert socket.getaddrinfo("localhost", 80)
    assert socket.getaddrinfo(None, 80, flags=socket.AI_PASSIVE)


@pytest.mark.parametrize("factory", LOOP_FACTORIES)
def test_event_loops_still_start_and_wake(factory):
    async def roundtrip(loop):
        done = loop.create_future()
        # call_soon_threadsafe writes to the loop's self-pipe (a socketpair)
        loop.call_soon_threadsafe(done.set_result, "woke")
        return await asyncio.wait_for(done, 2)

    assert _run(factory, roundtrip) == "woke"


def _ping_app():
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/ping")
    def ping():
        return {"ok": True}

    return app


async def test_in_process_async_transports_still_work():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_ping_app()),
                                 base_url="http://testserver") as client:
        assert (await client.get("/ping")).json() == {"ok": True}

    mock = httpx.MockTransport(lambda request: httpx.Response(200, json={"mock": True}))
    async with httpx.AsyncClient(transport=mock) as client:
        assert (await client.get(f"http://{EXTERNAL_HOST}/")).json() == {"mock": True}


def test_test_client_still_works():
    from fastapi.testclient import TestClient

    with TestClient(_ping_app()) as client:
        assert client.get("/ping").json() == {"ok": True}
