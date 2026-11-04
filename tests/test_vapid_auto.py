"""Web Push key pair created on first start and kept in the app's settings, never in .env."""
import asyncio
import base64
from contextlib import closing
from unittest.mock import AsyncMock, Mock

from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app import app_settings, push, secret_box, vapid
from app.config import settings
from app.database import get_db_connection, init_db, list_push_subscriptions, upsert_push_subscription
from app.main import app

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _rows():
    with closing(get_db_connection()) as conn:
        return {r["key"]: (r["value"], r["is_secret"]) for r in conn.execute(
            "SELECT key, value, is_secret FROM app_settings WHERE key LIKE 'VAPID_%'")}


def _audit():
    with closing(get_db_connection()) as conn:
        return [tuple(r) for r in conn.execute(
            "SELECT key, action FROM app_settings_audit WHERE key LIKE 'VAPID_%' ORDER BY id")]


def _subscribe(n=1):
    for i in range(n):
        upsert_push_subscription(f"https://fcm.googleapis.com/fcm/send/device-{i}",
                                 "synthetic-p256dh", "synthetic-auth")


def test_first_start_generates_a_usable_pair_stored_encrypted():
    assert not push.push_configured()
    assert vapid.ensure() == "generated"

    assert push.push_configured()
    public, private = _decode(settings.VAPID_PUBLIC_KEY), _decode(settings.VAPID_PRIVATE_KEY)
    assert len(public) == 65 and public[0] == 0x04 and len(private) == 32
    derived = ec.derive_private_key(int.from_bytes(private, "big"), ec.SECP256R1()).public_key()
    assert derived.public_numbers() == ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), public).public_numbers()
    assert push.vapid_headers("https://fcm.googleapis.com/fcm/send/x")["Authorization"].startswith("vapid t=")

    rows = _rows()
    assert rows["VAPID_PUBLIC_KEY"] == (settings.VAPID_PUBLIC_KEY, 0)  # browsers get it anyway
    stored_private, is_secret = rows["VAPID_PRIVATE_KEY"]
    assert is_secret == 1 and stored_private.startswith("fernet1:")
    assert settings.VAPID_PRIVATE_KEY not in stored_private
    assert _audit() == [("VAPID_PUBLIC_KEY", "generate"), ("VAPID_PRIVATE_KEY", "generate")]


def test_the_pair_survives_a_restart_and_is_not_regenerated():
    vapid.ensure()
    first = (settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY)
    app_settings.restore_baseline()  # what a fresh process starts from
    assert not push.push_configured()
    init_db()
    assert vapid.ensure() == "app"
    assert (settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY) == first
    assert len(_audit()) == 2


def test_a_pair_from_env_is_kept(monkeypatch):
    public, private = vapid.generate_pair()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    assert vapid.ensure() == "env"
    assert (settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY) == (public, private)
    assert _rows() == {} and _audit() == []
    assert vapid.status() == {**vapid.status(), "ready": True, "source": "env"}


def test_half_a_pair_in_env_is_replaced_by_a_complete_one(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "synthetic-orphan-private")
    assert vapid.ensure() == "generated"
    assert push.push_configured() and settings.VAPID_PRIVATE_KEY != "synthetic-orphan-private"


def test_a_lost_master_key_never_regenerates_or_half_applies(monkeypatch):
    vapid.ensure()
    public = settings.VAPID_PUBLIC_KEY
    secret_box.key_file_path().write_bytes(secret_box.Fernet.generate_key())
    secret_box.clear_cache()
    app_settings.restore_baseline()
    init_db()

    assert vapid.ensure() == "undecryptable"
    assert _rows()["VAPID_PUBLIC_KEY"][0] == public  # untouched, in case the right key file comes back
    assert settings.VAPID_PUBLIC_KEY == "" and not push.push_configured()  # never half a pair
    assert vapid.status() == {**vapid.status(), "ready": False, "source": "app", "undecryptable": True}


def test_settings_page_shows_status_but_never_the_pair_and_refuses_edits():
    vapid.ensure()
    _subscribe(2)
    with TestClient(app) as client:
        body = client.get("/api/settings", headers=HEADERS)
        assert settings.VAPID_PRIVATE_KEY not in body.text
        assert body.json()["push"] == {"ready": True, "source": "app", "undecryptable": False, "subscriptions": 2}
        keys = [f["key"] for g in body.json()["groups"] for f in g["fields"]]
        assert "VAPID_PRIVATE_KEY" not in keys and "VAPID_PUBLIC_KEY" not in keys and "VAPID_SUBJECT" in keys

        for payload in ({"values": {"VAPID_PRIVATE_KEY": "x" * 43}}, {"values": {"VAPID_PUBLIC_KEY": "abc"}},
                        {"reset": ["VAPID_PRIVATE_KEY"]}):
            res = client.put("/api/settings", headers=HEADERS, json={"values": {}, "reset": [], **payload})
            assert res.status_code == 400 and "自動產生" in res.text


def test_regenerate_replaces_the_pair_and_drops_orphaned_subscriptions():
    vapid.ensure()
    old_public = settings.VAPID_PUBLIC_KEY
    _subscribe(3)
    with TestClient(app) as client:
        anonymous = client.post("/api/settings/push/regenerate")
        assert anonymous.status_code == 401
        res = client.post("/api/settings/push/regenerate", headers=HEADERS)
    assert res.status_code == 200
    body = res.json()
    assert body["removed_subscriptions"] == 3 and body["push"]["subscriptions"] == 0
    assert settings.VAPID_PRIVATE_KEY not in res.text
    assert settings.VAPID_PUBLIC_KEY != old_public and push.push_configured()
    assert list_push_subscriptions() == []
    assert _audit()[-2:] == [("VAPID_PUBLIC_KEY", "regenerate"), ("VAPID_PRIVATE_KEY", "regenerate")]


def test_regenerate_recovers_from_an_unreadable_pair():
    vapid.ensure()
    secret_box.key_file_path().write_bytes(secret_box.Fernet.generate_key())
    secret_box.clear_cache()
    app_settings.apply_overrides()
    assert not push.push_configured()
    vapid.regenerate()
    assert push.push_configured() and vapid.status()["undecryptable"] is False


def test_importing_env_moves_the_pair_into_the_app_so_subscriptions_keep_working(monkeypatch):
    public, private = vapid.generate_pair()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", public)
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", private)
    with TestClient(app) as client:
        assert {"VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"} <= set(
            client.get("/api/settings", headers=HEADERS).json()["env_importable"])
        res = client.post("/api/settings/import-env", headers=HEADERS)
    assert {"VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY"} <= set(res.json()["imported"])
    assert private not in res.text
    assert _rows()["VAPID_PUBLIC_KEY"][0] == public
    app_settings.restore_baseline()
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "")  # .env lines deleted afterwards
    monkeypatch.setattr(settings, "VAPID_PRIVATE_KEY", "")
    init_db()
    assert (settings.VAPID_PUBLIC_KEY, settings.VAPID_PRIVATE_KEY) == (public, private)


def test_half_a_pair_in_env_is_not_imported(monkeypatch):
    monkeypatch.setattr(settings, "VAPID_PUBLIC_KEY", "synthetic-public-only")
    with TestClient(app) as client:
        importable = client.get("/api/settings", headers=HEADERS).json()["env_importable"]
    assert "VAPID_PUBLIC_KEY" not in importable


async def test_server_start_creates_the_pair(monkeypatch):
    import app.main as main
    from app.background import follow_up_pool
    monkeypatch.setattr(settings, "BACKGROUND_SERVICES_ENABLED", True)
    monkeypatch.setattr(main.task_worker, "start", Mock())
    monkeypatch.setattr(main.task_worker, "stop", AsyncMock())
    monkeypatch.setattr(main.radar_scheduler, "start", Mock())
    monkeypatch.setattr(main.radar_scheduler, "stop", AsyncMock())
    monkeypatch.setattr(follow_up_pool, "start", Mock())
    monkeypatch.setattr(follow_up_pool, "stop", AsyncMock())
    async with main.lifespan(main.app):
        await asyncio.sleep(0)
        assert push.push_configured()
    assert _audit() == [("VAPID_PUBLIC_KEY", "generate"), ("VAPID_PRIVATE_KEY", "generate")]


async def test_a_secondary_instance_does_not_create_one():
    import app.main as main
    async with main.lifespan(main.app):  # BACKGROUND_SERVICES_ENABLED is off in tests
        pass
    assert not push.push_configured() and _rows() == {}


async def test_start_survives_a_failing_generator(monkeypatch):
    import app.main as main
    from app.background import follow_up_pool
    ensure = Mock(side_effect=RuntimeError("synthetic"))
    monkeypatch.setattr(vapid, "ensure", ensure)
    monkeypatch.setattr(settings, "BACKGROUND_SERVICES_ENABLED", True)
    monkeypatch.setattr(main.task_worker, "start", Mock())
    monkeypatch.setattr(main.task_worker, "stop", AsyncMock())
    monkeypatch.setattr(main.radar_scheduler, "start", Mock())
    monkeypatch.setattr(main.radar_scheduler, "stop", AsyncMock())
    monkeypatch.setattr(follow_up_pool, "start", Mock())
    monkeypatch.setattr(follow_up_pool, "stop", AsyncMock())
    started = False
    async with main.lifespan(main.app):
        started = True
    assert started and ensure.called
