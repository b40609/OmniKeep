"""Global HTTP protection and credential rotation, using synthetic secrets only."""
import base64
import hashlib
import hmac

from dotenv import dotenv_values
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
import pytest

from app.config import settings
from app.main import app
from app.security import verify_api_key
from scripts.rotate_api_key import rotate_api_key


def test_global_gate_protects_future_routes_and_mounts():
    future = FastAPI()
    child = FastAPI()
    called = []

    @child.api_route("/private", methods=["GET", "POST", "OPTIONS"])
    @future.api_route("/future-private", methods=["GET", "POST", "OPTIONS"])
    def private():
        called.append(True)
        return {"ok": True}

    future.mount("/future-mount", child)
    future.middleware("http")(verify_api_key)
    with TestClient(future) as client:
        for path in ("/future-private", "/future-mount/private", "/docs", "/openapi.json"):
            for method in ("GET", "POST", "OPTIONS"):
                assert client.request(method, path).status_code == 401
        assert not called
        response = client.get("/future-mount/private", headers={"X-API-Key": settings.API_KEY})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert len(called) == 1


def test_preflight_does_not_invoke_private_handler():
    future = FastAPI()
    future.add_middleware(CORSMiddleware, allow_origins=["https://fixture.invalid"],
                          allow_methods=["POST"], allow_headers=["Authorization"])
    future.middleware("http")(verify_api_key)

    @future.options("/private")
    def private_options():
        pytest.fail("Unauthenticated preflight reached private handler")

    with TestClient(future) as client:
        assert client.options("/private", headers={"Access-Control-Request-Method": "POST"}).status_code == 401
        response = client.options("/private", headers={
            "Origin": "https://fixture.invalid", "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Authorization"})
        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "https://fixture.invalid"


def test_public_boot_and_exact_signed_webhook_exception(monkeypatch):
    monkeypatch.setattr(settings, "API_KEY", "")
    monkeypatch.setattr(settings, "LINE_CHANNEL_SECRET", "synthetic-line-secret")
    body = b'{"events": []}'
    signature = base64.b64encode(hmac.new(
        b"synthetic-line-secret", body, hashlib.sha256).digest()).decode()
    with TestClient(app) as client:
        assert client.get("/").status_code == 200
        assert client.get("/health").status_code == 200
        assert client.get("/static/dist/index.html").status_code in (200, 404)
        assert client.post("/api/line/webhook", content=body).status_code == 400
        assert client.post("/api/line/webhook", content=body,
                           headers={"X-Line-Signature": signature}).status_code == 200
        for method, path in (("GET", "/api/line/webhook"),
                             ("POST", "/api/line/webhook/"),
                             ("POST", "/static/new-private"), ("GET", "/docs")):
            assert client.request(method, path, follow_redirects=False).status_code == 503


def test_rotation_revokes_previous_key_without_exposing_values(isolated_runtime, monkeypatch, capsys):
    monkeypatch.delenv("API_KEY", raising=False)
    path = isolated_runtime / ".env"
    original = "synthetic-original-credential-for-rotation-test"
    path.write_text(f"# fixture\nAPI_KEY='{original}'\nOTHER_SECRET='line1\nline2'\n"
                    f"export API_KEY={original}\nPORT=5000", encoding="utf-8")
    before = dotenv_values(path)
    rotate_api_key(path)
    after = dotenv_values(path)
    assert len(after["API_KEY"]) >= 64
    assert len(set(after["API_KEY"])) >= 12
    assert after["API_KEY"] != original
    assert {k: v for k, v in after.items() if k != "API_KEY"} == {
        k: v for k, v in before.items() if k != "API_KEY"}
    assert original not in path.read_text(encoding="utf-8")
    monkeypatch.setattr(settings, "API_KEY", after["API_KEY"])
    with TestClient(app) as client:
        assert client.get("/api/watch/targets", headers={"X-API-Key": original}).status_code == 401
        assert client.get("/api/watch/targets", headers={"X-API-Key": after["API_KEY"]}).status_code == 200
    assert capsys.readouterr().out == ""


def test_rotation_refuses_environment_override(isolated_runtime, monkeypatch):
    path = isolated_runtime / ".env"
    content = "API_KEY=synthetic-original\n"
    path.write_text(content, encoding="utf-8")
    monkeypatch.setenv("API_KEY", "synthetic-environment-override")
    with pytest.raises(RuntimeError, match="override"):
        rotate_api_key(path)
    assert path.read_text(encoding="utf-8") == content


def test_local_auto_login_loopback_and_remote(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_AUTO_LOGIN", True)
    monkeypatch.setattr(settings, "API_KEY", "test-synthetic-key-12345")
    # Loopback client should get authenticated=True and the API key
    with TestClient(app) as local_client:
        res = local_client.get("/api/session/local-auth")
        assert res.status_code == 200
        assert res.json() == {"authenticated": True, "api_key": "test-synthetic-key-12345"}

    # Remote client should get authenticated=False and empty key
    with TestClient(app, client=("192.168.1.100", 50000)) as remote_client:
        res = remote_client.get("/api/session/local-auth")
        assert res.status_code == 200
        assert res.json() == {"authenticated": False, "api_key": ""}

    # Disabled auto login should return False even for loopback
    monkeypatch.setattr(settings, "LOCAL_AUTO_LOGIN", False)
    with TestClient(app) as local_client:
        res = local_client.get("/api/session/local-auth")
        assert res.status_code == 200
        assert res.json() == {"authenticated": False, "api_key": ""}

