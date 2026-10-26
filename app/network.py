"""HTTP egress: public addresses only, including redirects and DNS rebinding."""
import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpcore
import httpx
from httpcore._backends.auto import AutoBackend
from httpcore._backends.sync import SyncBackend


class UnsafeURL(ValueError):
    pass


def _is_public(ip):
    address = ipaddress.ip_address(ip)
    return (address.is_global and not address.is_multicast and not address.is_reserved
            and not address.is_unspecified and not getattr(address, "ipv4_mapped", None)
            and not getattr(address, "is_site_local", False)
            and not (getattr(address, "sixtofour", None) and not address.sixtofour.is_global))


def validate_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or "%" in parsed.hostname or parsed.port not in (None, 80, 443)):
            raise UnsafeURL("Only public HTTP(S) URLs on ports 80/443 are allowed")
        try:
            address = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            if parsed.hostname.lower() in ("localhost", "localhost.localdomain"):
                raise UnsafeURL("Local destinations are not allowed")
        else:
            if not _is_public(address):
                raise UnsafeURL("Non-public destinations are not allowed")
    except ValueError as exc:
        raise UnsafeURL("Invalid or non-public URL") from exc
    return url


class PublicNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self):
        self.backend = AutoBackend()

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        # Connect to the validated numeric address, never resolve the hostname twice.
        addresses = await asyncio.wait_for(asyncio.to_thread(
            socket.getaddrinfo, host, port, 0, socket.SOCK_STREAM), timeout=timeout or 10)
        ips = list(dict.fromkeys(row[4][0] for row in addresses))
        if not ips or any(not _is_public(ip) for ip in ips):
            raise UnsafeURL("DNS resolved to a non-public destination")
        last_error = None
        for ip in ips:
            try:
                return await self.backend.connect_tcp(ip, port, timeout, local_address, socket_options)
            except (OSError, httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error

    async def connect_unix_socket(self, *args, **kwargs):
        raise UnsafeURL("Unix sockets are not allowed")

    async def sleep(self, seconds):
        await asyncio.sleep(seconds)


class PublicHTTPTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__(trust_env=False)
        self._pool._network_backend = PublicNetworkBackend()


class PublicSyncBackend(httpcore.NetworkBackend):
    def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        addresses = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
        ips = list(dict.fromkeys(row[4][0] for row in addresses))
        if not ips or any(not _is_public(ip) for ip in ips):
            raise UnsafeURL("DNS resolved to a non-public destination")
        last_error = None
        for ip in ips:
            try:
                return SyncBackend().connect_tcp(ip, port, timeout, local_address, socket_options)
            except (OSError, httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
        raise last_error

    def connect_unix_socket(self, *args, **kwargs):
        raise UnsafeURL("Unix sockets are not allowed")


def public_sync_client(**kwargs):
    transport = httpx.HTTPTransport(trust_env=False)
    transport._pool._network_backend = PublicSyncBackend()
    kwargs.update(transport=transport, trust_env=False,
                  event_hooks={"request": [lambda request: validate_url(str(request.url))]})
    return httpx.Client(**kwargs)


async def _validate_request(request):
    validate_url(str(request.url))


def public_http_client(**kwargs):
    kwargs.update(transport=PublicHTTPTransport(), trust_env=False,
                  event_hooks={"request": [_validate_request]})
    return httpx.AsyncClient(**kwargs)
