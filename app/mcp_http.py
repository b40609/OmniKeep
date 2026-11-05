"""MCP over Streamable HTTP, served by the main service at /mcp-http.

For an agent on another computer (design §7): it connects through Tailscale
with OmniKeep's API key, which app.security checks for every path. The SSE
transport stays at /mcp for clients that still use it.

Host checks (DNS-rebinding protection) admit loopback names, Tailscale names
this machine has (found with the tailscale CLI at startup) and any extra names
in MCP_ALLOWED_HOSTS (comma-separated, e.g. "box.tail1234.ts.net").
"""
import asyncio
import json
import logging
import os
import shutil
from contextlib import asynccontextmanager
from typing import List

from fastapi.responses import JSONResponse

from app.config import settings
from app.mcp_server import mcp

logger = logging.getLogger("omnikeep.mcp_http")

STREAMABLE_HTTP_PATH = "/mcp-http"
_LOOPBACK = ("127.0.0.1", "localhost", "[::1]")
_remote: List[str] = []
_running = False


def _security():
    return mcp.settings.transport_security


def allow_hosts(names) -> None:
    """Admit these host names (and any port on them) for both MCP transports."""
    security = _security()
    for raw in names:
        name = str(raw).strip().rstrip(".").lower()
        if not name or name in _remote or name in _LOOPBACK:
            continue
        _remote.append(name)
        for host in (name, f"{name}:*"):
            if host not in security.allowed_hosts:
                security.allowed_hosts.append(host)
        for origin in (f"https://{name}", f"https://{name}:*", f"http://{name}:*"):
            if origin not in security.allowed_origins:
                security.allowed_origins.append(origin)


def remote_hosts() -> List[str]:
    return list(_remote)


def configure_transport_security() -> None:
    """Loopback with or without a port, plus MCP_ALLOWED_HOSTS. Shared by SSE and Streamable HTTP."""
    from mcp.server.transport_security import TransportSecuritySettings
    if mcp.settings.transport_security is None:
        mcp.settings.transport_security = TransportSecuritySettings(enable_dns_rebinding_protection=True)
    security = mcp.settings.transport_security
    security.enable_dns_rebinding_protection = True
    for name in _LOOPBACK:
        for host in (name, f"{name}:*"):
            if host not in security.allowed_hosts:
                security.allowed_hosts.append(host)
        origin = f"http://{name}:*"
        if origin not in security.allowed_origins:
            security.allowed_origins.append(origin)
    allow_hosts((settings.MCP_ALLOWED_HOSTS or "").split(","))


def _tailscale_names() -> List[str]:
    """This machine's MagicDNS name and Tailscale IPs, or [] without the tailscale CLI."""
    import subprocess
    exe = shutil.which("tailscale")
    if not exe and os.name == "nt":
        candidate = os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Tailscale", "tailscale.exe")
        exe = candidate if os.path.isfile(candidate) else None
    if not exe:
        return []
    try:
        done = subprocess.run([exe, "status", "--json"], capture_output=True,
                              timeout=5, text=True, encoding="utf-8", errors="replace",
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        me = json.loads(done.stdout or "{}").get("Self") or {}
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    names = [me.get("DNSName") or ""]
    names += [ip if ":" not in ip else f"[{ip}]" for ip in me.get("TailscaleIPs") or []]
    return [n for n in names if n]


async def _discover_tailscale() -> None:
    try:
        names = await asyncio.to_thread(_tailscale_names)
    except Exception:
        return
    if names:
        allow_hosts(names)
        logger.info("MCP over HTTP accepts Tailscale names: %s", ", ".join(_remote))


class StreamableHTTPEndpoint:
    """ASGI endpoint for the current session manager (a new one per app lifespan)."""

    async def __call__(self, scope, receive, send):
        if not _running:
            response = JSONResponse({"error": "MCP over HTTP is not running"}, status_code=503)
            await response(scope, receive, send)
            return
        await mcp.session_manager.handle_request(scope, receive, send)


@asynccontextmanager
async def streamable_http_session():
    """Run the Streamable HTTP session manager for one app lifespan.

    A session manager runs once, and tests start the app's lifespan many times,
    so each lifespan builds a fresh one through mcp.streamable_http_app().
    """
    global _running
    mcp._session_manager = None  # FastMCP builds a new manager on the next call
    mcp.streamable_http_app()
    discovery = None
    if os.environ.get("OMNIKEEP_TESTING") != "1":
        discovery = asyncio.create_task(_discover_tailscale())
    async with mcp.session_manager.run():
        _running = True
        try:
            yield
        finally:
            _running = False
            if discovery and not discovery.done():
                discovery.cancel()


configure_transport_security()
