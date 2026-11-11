"""local-auth must never hand out the API key to traffic relayed by a reverse proxy."""
import logging

from fastapi.testclient import TestClient
import pytest
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.config import settings
from app.main import app

SYNTHETIC_KEY = "test-synthetic-key-12345"
# The address a browser on the same machine uses; local-auth refuses any other Host.
LOCAL = "http://127.0.0.1:5000"
DENIED = {"authenticated": False, "api_key": ""}


@pytest.fixture
def auto_login(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_AUTO_LOGIN", True)
    monkeypatch.setattr(settings, "API_KEY", SYNTHETIC_KEY)


def test_plain_loopback_still_auto_logs_in(auto_login):
    with TestClient(app, base_url=LOCAL) as client:
        res = client.get("/api/session/local-auth")
    assert res.json() == {"authenticated": True, "api_key": SYNTHETIC_KEY}


@pytest.mark.parametrize("headers", [
    # What Tailscale serve sends for a tailnet user (ipn/ipnlocal/serve.go).
    {
        "X-Forwarded-For": "100.101.102.103",
        "X-Forwarded-Host": "desktop.tailnet-name.ts.net",
        "X-Forwarded-Proto": "https",
        "Tailscale-User-Login": "owner@example.com",
        "Tailscale-User-Name": "Owner",
        "Tailscale-Headers-Info": "https://tailscale.com/s/serve-headers",
    },
    # Tailscale Funnel: no identity headers, only the funnel marker.
    {"X-Forwarded-For": "203.0.113.9", "Tailscale-Funnel-Request": "?1"},
    {"X-Forwarded-For": "203.0.113.9"},
    {"Forwarded": "for=203.0.113.9;proto=https"},
    {"X-Forwarded-Host": "example.trycloudflare.com"},
    {"X-Forwarded-Proto": "https"},
    {"X-Real-IP": "203.0.113.9"},
    {"CF-Connecting-IP": "203.0.113.9"},
    {"True-Client-IP": "203.0.113.9"},
    {"Via": "1.1 proxy"},
    {"Tailscale-User-Login": "owner@example.com"},
    {"x-FORWARDED-for": "203.0.113.9"},
])
def test_proxy_headers_block_auto_login(auto_login, headers):
    with TestClient(app, base_url=LOCAL) as client:
        res = client.get("/api/session/local-auth", headers=headers)
    assert res.status_code == 200
    assert res.json() == DENIED


def test_spoofed_loopback_forwarded_for_is_refused_under_uvicorn(auto_login):
    # uvicorn trusts X-Forwarded-For from 127.0.0.1 by default and rewrites
    # request.client from it. A proxy that passes the header through unchanged
    # lets a remote client claim to be 127.0.0.1.
    proxied = ProxyHeadersMiddleware(app, trusted_hosts="127.0.0.1,::1")
    with TestClient(proxied, base_url=LOCAL, client=("127.0.0.1", 50000)) as client:
        res = client.get("/api/session/local-auth", headers={"X-Forwarded-For": "127.0.0.1"})
    assert res.json() == DENIED


def test_startup_warns_when_local_auto_login_enabled(auto_login, caplog):
    with caplog.at_level(logging.WARNING, logger="omnikeep.main"):
        with TestClient(app):
            pass
    assert any("LOCAL_AUTO_LOGIN" in r.getMessage() for r in caplog.records)


def test_startup_is_quiet_when_local_auto_login_disabled(monkeypatch, caplog):
    monkeypatch.setattr(settings, "LOCAL_AUTO_LOGIN", False)
    with caplog.at_level(logging.WARNING, logger="omnikeep.main"):
        with TestClient(app):
            pass
    assert not any("LOCAL_AUTO_LOGIN" in r.getMessage() for r in caplog.records)
