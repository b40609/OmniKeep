"""Web Push: subscription API, encrypted/signed delivery, radar hooks. No real push service is contacted."""
import base64
import json
import os
import time
from unittest.mock import AsyncMock, Mock

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi.testclient import TestClient
import http_ece
import httpx
import pytest

from app import push
from app.config import settings
from app.database import (
    add_watch_target,
    get_item_by_id,
    get_proposals,
    get_watch_target,
    list_push_subscriptions,
    save_item,
    save_proposal,
    update_watch_target,
    upsert_push_subscription,
)
from app.main import app
from app.watch import relevance, scanner
from scripts.generate_vapid_keys import generate_vapid_pair

ENDPOINT = "https://fcm.googleapis.com/fcm/send/synthetic-device-1"


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


@pytest.fixture
def vapid(monkeypatch):
    public, private = generate_vapid_pair()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    monkeypatch.setattr(settings, "VAPID_SUBJECT", "mailto:owner@example.com")
    return public


class Browser:
    """What a browser holds after PushManager.subscribe(): receiver key pair and auth secret."""

    def __init__(self, endpoint=ENDPOINT):
        self.endpoint = endpoint
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.auth = os.urandom(16)

    def subscription(self):
        public = self.private.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        return {"endpoint": self.endpoint, "keys": {"p256dh": _b64url(public), "auth": _b64url(self.auth)}}

    def decrypt(self, body: bytes) -> dict:
        return json.loads(http_ece.decrypt(body, private_key=self.private, auth_secret=self.auth,
                                           version="aes128gcm"))


def _client():
    return TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"})


def _mock_push_service(monkeypatch, status_for=lambda request: 201):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(status_for(request))

    monkeypatch.setattr(push, "public_http_client",
                        lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    return seen


def _subscribe(browser):
    sub = browser.subscription()
    upsert_push_subscription(sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"])


# ── API ──────────────────────────────────────────────────────────

def test_config_reports_public_key_only_when_configured(vapid, monkeypatch):
    with _client() as client:
        assert client.get("/api/push/config").json() == {
            "configured": True, "public_key": vapid, "subscriptions": 0}
        monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
        assert client.get("/api/push/config").json()["public_key"] == ""


def test_push_routes_require_the_api_key(vapid):
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/push/config").status_code == 401
        assert anonymous.post("/api/push/subscribe", json=Browser().subscription()).status_code == 401
        assert anonymous.post("/api/push/test").status_code == 401


def test_subscribe_upserts_and_unsubscribe_removes(vapid):
    first, renewed = Browser(), Browser()
    with _client() as client:
        assert client.post("/api/push/subscribe", json=first.subscription()).json() == {"success": True}
        assert client.post("/api/push/subscribe", json=renewed.subscription()).status_code == 200
        rows = list_push_subscriptions()
        assert len(rows) == 1  # same endpoint, keys replaced
        assert rows[0]["p256dh"] == renewed.subscription()["keys"]["p256dh"]
        assert client.post("/api/push/unsubscribe", json={"endpoint": ENDPOINT}).json()["removed"] is True
        assert client.post("/api/push/unsubscribe", json={"endpoint": ENDPOINT}).json()["removed"] is False
    assert list_push_subscriptions() == []


@pytest.mark.parametrize("endpoint", [
    "http://fcm.googleapis.com/fcm/send/x",       # not https
    "https://127.0.0.1/push",                     # loopback
    "https://10.0.0.8/push",                      # private network
    "https://localhost/push",
    "https://fcm.googleapis.com:8443/fcm/send/x",  # non-standard port
])
def test_subscribe_rejects_unsafe_endpoints(vapid, endpoint):
    with _client() as client:
        res = client.post("/api/push/subscribe", json=Browser(endpoint).subscription())
    assert res.status_code == 400
    assert list_push_subscriptions() == []


def test_subscribe_rejects_malformed_keys(vapid):
    sub = Browser().subscription()
    with _client() as client:
        bad_point = {**sub, "keys": {**sub["keys"], "p256dh": _b64url(b"\x04" + b"\x01" * 64)}}
        short_auth = {**sub, "keys": {**sub["keys"], "auth": _b64url(b"abc")}}
        assert client.post("/api/push/subscribe", json=bad_point).status_code == 400
        assert client.post("/api/push/subscribe", json=short_auth).status_code == 400


def test_subscribe_and_test_need_vapid_keys():
    with _client() as client:
        assert client.get("/api/push/config").json()["configured"] is False
        assert client.post("/api/push/subscribe", json=Browser().subscription()).status_code == 503
        assert client.post("/api/push/test").status_code == 503


# ── Delivery ─────────────────────────────────────────────────────

async def test_payload_is_encrypted_for_the_browser_and_signed_with_vapid(vapid, monkeypatch):
    browser = Browser()
    _subscribe(browser)
    seen = _mock_push_service(monkeypatch)

    result = await push.send_push("📰 晨間戰報", "• 第一則\n• 第二則", url="/", tag="radar-digest")

    assert result == {"sent": 1, "removed": 0, "failed": 0}
    request = seen[0]
    assert request.method == "POST" and str(request.url) == ENDPOINT
    assert request.headers["content-encoding"] == "aes128gcm"
    assert request.headers["ttl"] == str(24 * 3600)
    assert request.headers["topic"] == "radar-digest"
    assert browser.decrypt(request.content) == {
        "title": "📰 晨間戰報", "body": "• 第一則\n• 第二則", "url": "/", "tag": "radar-digest"}

    # RFC 8292: "vapid t=<ES256 JWT>,k=<server public key>"
    scheme, params = request.headers["authorization"].split(" ", 1)
    fields = dict(part.split("=", 1) for part in params.split(","))
    assert scheme == "vapid" and fields["k"] == vapid
    header_b64, claims_b64, sig_b64 = fields["t"].split(".")
    pad = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
    assert json.loads(pad(header_b64))["alg"] == "ES256"
    claims = json.loads(pad(claims_b64))
    assert claims["aud"] == "https://fcm.googleapis.com"
    assert claims["sub"] == "mailto:owner@example.com"
    assert time.time() < claims["exp"] <= time.time() + 24 * 3600  # Apple: at most one day ahead
    raw = pad(sig_b64)
    server_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pad(vapid))
    server_key.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                      f"{header_b64}.{claims_b64}".encode(), ec.ECDSA(hashes.SHA256()))
    assert list_push_subscriptions()[0]["last_success_at"]


async def test_gone_subscriptions_are_removed_and_errors_recorded(vapid, monkeypatch):
    gone, broken, healthy = (Browser(f"https://fcm.googleapis.com/fcm/send/{n}") for n in ("gone", "broken", "ok"))
    for b in (gone, broken, healthy):
        _subscribe(b)
    statuses = {gone.endpoint: 410, broken.endpoint: 500, healthy.endpoint: 201}
    _mock_push_service(monkeypatch, lambda request: statuses[str(request.url)])

    assert await push.send_push("t", "b") == {"sent": 1, "removed": 1, "failed": 1}

    rows = {r["endpoint"]: r for r in list_push_subscriptions()}
    assert gone.endpoint not in rows
    assert "HTTP 500" in rows[broken.endpoint]["last_error"]
    assert rows[healthy.endpoint]["last_error"] is None


async def test_stored_unsafe_endpoint_is_never_contacted(vapid, monkeypatch):
    sub = Browser("https://127.0.0.1/push").subscription()
    upsert_push_subscription(sub["endpoint"], sub["keys"]["p256dh"], sub["keys"]["auth"])
    seen = _mock_push_service(monkeypatch)
    assert await push.send_push("t", "b") == {"sent": 0, "removed": 0, "failed": 1}
    assert seen == []


async def test_click_target_stays_on_this_origin_and_body_is_bounded(vapid, monkeypatch):
    browser = Browser()
    _subscribe(browser)
    seen = _mock_push_service(monkeypatch)
    await push.send_push("t", "長" * 2000, url="https://evil.example/")
    await push.send_push("t", "b", url="//evil.example/")
    first, second = (browser.decrypt(r.content) for r in seen)
    assert first["url"] == "/" and second["url"] == "/"
    assert len(first["body"]) == 400 and len(seen[0].content) < 4096


async def test_without_keys_nothing_is_sent(monkeypatch):
    _subscribe(Browser())
    seen = _mock_push_service(monkeypatch)
    assert await push.send_push("t", "b") == {"sent": 0, "removed": 0, "failed": 0}
    assert seen == []


def test_test_endpoint_reports_delivery(vapid, monkeypatch):
    browser = Browser()
    _subscribe(browser)
    seen = _mock_push_service(monkeypatch)
    with _client() as client:
        assert client.post("/api/push/test").json() == {"success": True, "sent": 1, "removed": 0, "failed": 0}
    assert browser.decrypt(seen[0].content)["title"] == "OmniKeep 推播測試"


def test_push_handlers_script_is_served_uncached(isolated_runtime):
    from fastapi import FastAPI
    from app.static_assets import CurrentBuildFiles

    root = isolated_runtime / "static"
    (root / "dist").mkdir(parents=True)
    (root / "dist/sw.js").write_text('define(["./workbox-abc"],function(e){importScripts("push-sw.js")})')
    (root / "dist/push-sw.js").write_text("self.addEventListener('push', () => {})")
    test_app = FastAPI()
    test_app.mount("/static", CurrentBuildFiles(directory=root))
    with TestClient(test_app) as client:
        res = client.get("/static/dist/push-sw.js")
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-cache"


# ── Radar hooks: same events Telegram announces ──────────────────

class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


@pytest.fixture
def radar_outlets(monkeypatch):
    from app.radar import scheduler
    pushed = []

    async def fake_send_push(title, body, url="/", tag=None, ttl=0):
        pushed.append({"title": title, "body": body, "tag": tag})
        return {"sent": 1, "removed": 0, "failed": 0}

    bot = FakeBot()
    monkeypatch.setattr(scheduler, "send_push", fake_send_push)
    monkeypatch.setattr("app.bot.telegram_bot.get_telegram_bot", lambda: bot)
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", "42")
    return scheduler, pushed, bot


async def test_digest_goes_to_telegram_and_web(radar_outlets):
    scheduler, pushed, bot = radar_outlets
    ranked = [{"title_l1": "Rust 年度回顧"}, {"title_l1": "SQLite 向量檢索"}]
    await scheduler._announce_digest({"success": True, "title": "晨間雷達戰報"}, ranked)
    assert len(bot.sent) == 1 and "晨間雷達戰報" in bot.sent[0][1]
    assert pushed == [{"title": "📰 晨間雷達戰報", "body": "• Rust 年度回顧\n• SQLite 向量檢索",
                       "tag": "radar-digest"}]


async def test_failed_digest_is_not_announced(radar_outlets):
    scheduler, pushed, bot = radar_outlets
    await scheduler._announce_digest({"success": False}, [{"title_l1": "x"}])
    assert pushed == [] and bot.sent == []


async def test_autostar_announces_only_starred_items(radar_outlets):
    scheduler, pushed, bot = radar_outlets
    items = [{"title_l1": "收藏一", "auto_starred": True}, {"title_l1": "沒收藏"},
             {"title_l1": "收藏二", "auto_starred": True}]
    await scheduler._announce_autostar(items)
    assert pushed == [{"title": "🤖 雷達自動收藏", "body": "⭐ 收藏一\n⭐ 收藏二", "tag": "radar-autostar"}]
    assert len(bot.sent) == 1
    await scheduler._announce_autostar([{"title_l1": "沒收藏"}])
    assert len(pushed) == 1


async def test_web_push_works_without_telegram(radar_outlets, monkeypatch):
    scheduler, pushed, _ = radar_outlets
    monkeypatch.setattr("app.bot.telegram_bot.get_telegram_bot", lambda: None)
    await scheduler._announce_digest({"success": True, "title": "戰報"}, [{"title_l1": "a"}])
    assert len(pushed) == 1


# ── New proposals: web only, Telegram never announced them ───────

async def test_new_proposal_links_to_the_proposals_tab(vapid, monkeypatch):
    browser = Browser()
    _subscribe(browser)
    seen = _mock_push_service(monkeypatch)
    card = save_item({"url": "fixture://proposal/push", "title_l1": "🔗 提案：app/network.py ⟷ httpx 2.0"})
    proposal = save_proposal({"item_id": card, "impact": 8, "confidence": 9, "effort": 2.5})

    assert await push.notify_new_proposal(proposal) == {"sent": 1, "removed": 0, "failed": 0}
    assert browser.decrypt(seen[0].content) == {
        "title": "📋 新的待決提案",
        "body": "🔗 提案：app/network.py ⟷ httpx 2.0\n影響 8 · 信心 9 · 成本 2.5",
        "url": "/?open=proposals",
        "tag": f"proposal-{proposal['id']}",
    }
    # Each proposal has its own Topic, so the push service never collapses two of them.
    assert seen[0].headers["topic"] == f"proposal-{proposal['id']}"


async def test_proposal_push_failure_never_reaches_the_caller(monkeypatch):
    monkeypatch.setattr(push, "get_item_by_id", Mock(side_effect=RuntimeError("database is locked")))
    proposal = {"id": "p1", "item_id": "i1", "impact": 1, "confidence": 1, "effort": 1}
    assert await push.notify_new_proposal(proposal) == {"sent": 0, "removed": 0, "failed": 0}


async def test_risk_scan_pushes_a_new_proposal_once_without_filenames(vapid, monkeypatch, isolated_runtime):
    browser = Browser()
    _subscribe(browser)
    seen = _mock_push_service(monkeypatch)
    (isolated_runtime / "password.txt").write_text("SYNTHETIC_NEVER_READ")
    target = add_watch_target("DemoOS", str(isolated_runtime), preset="strict")
    provider = Mock(generate_json=AsyncMock(return_value={"title_l1": "fingerprint"}))
    monkeypatch.setattr(scanner, "get_primary_provider", lambda: provider)

    await scanner.scan_target(target)
    await scanner.scan_target(get_watch_target(target["id"]))  # same risk → deduplicated, no second push

    assert len(seen) == 1
    sent = browser.decrypt(seen[0].content)
    assert sent["tag"] == f"proposal-{get_proposals()[0]['id']}"
    assert "DemoOS" in sent["body"] and "疑似明文機密檔" in sent["body"]
    assert "password.txt" not in json.dumps(sent, ensure_ascii=False)  # lock screens show the body


def _fingerprinted_target(isolated_runtime, consent):
    fingerprint = save_item({"url": "watch://fixture", "origin": "watch", "title_l1": "fp",
                             "tech_tags": ["Python", "SQLite"]})
    target = add_watch_target("DemoOS", str(isolated_runtime), "folder", "custom",
                              read_scope={"filenames": True}, outbound_consent=consent)
    update_watch_target(target["id"], {"fingerprint_item_id": fingerprint})
    return get_item_by_id(save_item({"url": "https://example.com/news", "title_l1": "SQLite 3.50 發布",
                                     "tech_tags": ["Python", "SQLite", "新聞"]}))


async def test_relevance_proposal_is_pushed_once(vapid, monkeypatch, isolated_runtime):
    browser = Browser()
    _subscribe(browser)
    seen = _mock_push_service(monkeypatch)
    news = _fingerprinted_target(isolated_runtime, {"summary": False})

    proposal = await relevance.maybe_propose_for_item(news)
    assert await relevance.maybe_propose_for_item(news) is None  # 30-day dedup

    assert len(seen) == 1
    sent = browser.decrypt(seen[0].content)
    assert sent["tag"] == f"proposal-{proposal['id']}" and sent["url"] == "/?open=proposals"
    assert "SQLite 3.50 發布" in sent["body"]


async def test_rejected_relevance_is_not_pushed(vapid, monkeypatch, isolated_runtime):
    _subscribe(Browser())
    seen = _mock_push_service(monkeypatch)
    news = _fingerprinted_target(isolated_runtime, {"summary": True})
    provider = Mock(generate_json=AsyncMock(return_value={"relevant": False}))
    monkeypatch.setattr(relevance, "get_primary_provider", lambda: provider)

    assert await relevance.maybe_propose_for_item(news) is None
    assert seen == [] and get_proposals() == []
