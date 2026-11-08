"""Phone sign-in with a one-time code: the code stands in for the key, once, for a few minutes."""
from fastapi.testclient import TestClient
import pytest

from app import pairing
from app.config import settings
from app.main import app

STRONG_KEY = "synthetic-pairing-key-abcdefghijklmnopqrstuvwxyz-0123456789"
AUTH = {"Authorization": f"Bearer {STRONG_KEY}"}
# What Tailscale serve adds for a tailnet phone: pairing must work through it.
VIA_TAILSCALE = {"X-Forwarded-For": "100.101.102.103", "X-Forwarded-Host": "desktop.tailnet-name.ts.net",
                 "Tailscale-User-Login": "owner@example.com"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", STRONG_KEY)
    monkeypatch.setattr(pairing, "phone_urls", lambda: ["https://desktop.tailnet-name.ts.net"])
    pairing.cancel()
    with TestClient(app) as c:
        yield c
    pairing.cancel()


def test_only_a_signed_in_screen_can_make_a_code(client):
    assert client.post("/api/session/pairing").status_code == 401
    assert client.get("/api/session/pairing").status_code == 401
    res = client.post("/api/session/pairing", headers=AUTH)
    assert res.status_code == 200
    body = res.json()
    assert len(body["code"]) == pairing.LENGTH and set(body["code"]) <= set(pairing.ALPHABET)
    assert STRONG_KEY not in res.text  # the code never carries the key
    assert body["phone_urls"] == ["https://desktop.tailnet-name.ts.net"] and body["ttl"] == pairing.TTL


def test_the_code_signs_a_phone_in_once(client):
    code = client.post("/api/session/pairing", headers=AUTH).json()["code"]
    typed = f"{code[:4].lower()}-{code[4:].lower()} "  # as someone might type it on a phone
    res = client.post("/api/session/pair", json={"code": typed}, headers=VIA_TAILSCALE)
    assert res.status_code == 200 and res.json() == {"api_key": STRONG_KEY}
    assert res.headers["cache-control"] == "no-store"
    assert client.get("/api/session/pairing", headers=AUTH).json()["used_at"] > 0

    again = client.post("/api/session/pair", json={"code": code}, headers=VIA_TAILSCALE)
    assert again.status_code == 400 and STRONG_KEY not in again.text


def test_wrong_guesses_drop_the_code(client):
    code = client.post("/api/session/pairing", headers=AUTH).json()["code"]
    wrong = "".join("2" if ch != "2" else "3" for ch in code)
    for _ in range(pairing.MAX_WRONG):
        assert client.post("/api/session/pair", json={"code": wrong}).status_code == 400
    assert client.post("/api/session/pair", json={"code": code}).status_code == 400
    assert client.get("/api/session/pairing", headers=AUTH).json()["active"] is False


def test_an_expired_or_replaced_code_does_nothing():
    first = pairing.create(now=1000.0)["code"]
    assert pairing.redeem(first, now=1000.0 + pairing.TTL) is False
    old = pairing.create(now=2000.0)["code"]
    new = pairing.create(now=2001.0)["code"]
    assert old == new or pairing.redeem(old, now=2002.0) is False
    assert pairing.redeem(new, now=2002.0) is True
    pairing.cancel()


def test_no_code_no_key_and_a_weak_key_is_never_handed_out(client, monkeypatch):
    assert client.post("/api/session/pair", json={"code": "ABCD2345"}).status_code == 400
    code = client.post("/api/session/pairing", headers=AUTH).json()["code"]
    monkeypatch.setattr(settings, "API_KEY", "short-key")
    res = client.post("/api/session/pair", json={"code": code})
    assert res.status_code == 400 and "short-key" not in res.text
    assert client.post("/api/session/pair", json={"code": "x" * 40}).status_code == 422
