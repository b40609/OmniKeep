"""This computer signs in without the key by default; nothing else ever gets the key that way."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import app_settings
from app.config import Settings, settings
from app.main import app

REPO = Path(__file__).resolve().parents[1]
LOCAL = "http://127.0.0.1:5000"
KEY = settings.API_KEY
HEADERS = {"Authorization": f"Bearer {KEY}"}
GRANTED = {"authenticated": True, "api_key": KEY}
DENIED = {"authenticated": False, "api_key": ""}
URL = "/api/session/local-auth"


def _ask(headers=None, base_url=LOCAL, client=("127.0.0.1", 50000)):
    with TestClient(app, base_url=base_url, client=client) as browser:
        return browser.get(URL, headers=headers or {})


def _field(body):
    system = next(group for group in body["groups"] if group["id"] == "system")
    return next(field for field in system["fields"] if field["key"] == "LOCAL_AUTO_LOGIN")


def test_a_new_install_signs_this_computer_in_without_the_key():
    assert Settings.model_fields["LOCAL_AUTO_LOGIN"].default is True
    assert settings.LOCAL_AUTO_LOGIN is True  # nothing in the test environment sets it
    res = _ask()
    assert res.status_code == 200 and res.json() == GRANTED


def test_the_example_env_leaves_the_default_alone_and_an_explicit_false_still_wins(isolated_runtime):
    assert Settings(_env_file=REPO / ".env.example").LOCAL_AUTO_LOGIN is True
    older = isolated_runtime / "older.env"
    older.write_text("LOCAL_AUTO_LOGIN=false\n", encoding="utf-8")
    assert Settings(_env_file=older).LOCAL_AUTO_LOGIN is False


def test_docker_keeps_it_off_unless_the_owner_sets_it():
    compose = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "- LOCAL_AUTO_LOGIN=${LOCAL_AUTO_LOGIN:-false}" in compose


def test_the_key_is_still_required_for_every_api_route():
    with TestClient(app, base_url=LOCAL, client=("127.0.0.1", 50000)) as browser:
        assert browser.get("/api/items").status_code == 401
        assert browser.get("/api/settings").status_code == 401
        assert browser.put("/api/settings", json={"values": {"LOCAL_AUTO_LOGIN": True}}).status_code == 401
        assert browser.post(URL).status_code == 401  # only GET is public


@pytest.mark.parametrize("host", ["localhost", "localhost:5000", "LOCALHOST:5000", "127.0.0.1", "127.0.0.1:8123",
                                  "[::1]", "[::1]:5000"])
def test_local_names_are_accepted_on_any_port(host):
    assert _ask({"Host": host}).json() == GRANTED


@pytest.mark.parametrize("host", [
    "attacker.example", "attacker.example:5000",  # DNS rebinding: the page's own domain
    "localhost.attacker.example", "127.0.0.1.nip.io", "notlocalhost", "localhost.", "testserver",
    "192.168.1.5:5000", "0.0.0.0:5000", "127.0.0.2", "[::2]:5000", "desktop.tailnet-name.ts.net",
    "localhost:5000@attacker.example", "localhost:port", "localhost:5000:5000", "localhost attacker.example", "",
])
def test_any_other_host_is_refused(host):
    assert _ask({"Host": host}).json() == DENIED


def test_two_host_headers_are_refused():
    with TestClient(app, base_url=LOCAL, client=("127.0.0.1", 50000)) as browser:
        res = browser.get(URL, headers=[("Host", "127.0.0.1:5000"), ("Host", "attacker.example")])
    assert res.json() == DENIED


@pytest.mark.parametrize("headers", [
    {"Origin": "https://attacker.example"},
    {"Origin": "http://attacker.example:5000"},
    {"Origin": "http://localhost:5000"},      # another name for this machine is another origin
    {"Origin": "http://127.0.0.1:3000"},      # another local port
    {"Origin": "http://127.0.0.1"},
    {"Origin": "https://127.0.0.1:5000"},
    {"Origin": "null"},                        # a sandboxed frame, such as a snapshot
    {"Origin": ""},
    {"Origin": "http://127.0.0.1:5000/"},
    {"Sec-Fetch-Site": "cross-site"},
    {"Sec-Fetch-Site": "same-site"},
    {"Sec-Fetch-Site": "anything-else"},
    {"Origin": "http://127.0.0.1:5000", "Sec-Fetch-Site": "cross-site"},
    {"Origin": "https://attacker.example", "Sec-Fetch-Site": "same-origin"},
])
def test_a_request_from_another_site_is_refused(headers):
    assert _ask(headers).json() == DENIED


@pytest.mark.parametrize("headers", [
    {"Origin": "http://127.0.0.1:5000"},
    {"Origin": "HTTP://127.0.0.1:5000"},
    {"Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Site": "none"},  # typed into the address bar
    {"Origin": "http://127.0.0.1:5000", "Sec-Fetch-Site": "same-origin", "Sec-Fetch-Mode": "cors"},
])
def test_omnikeeps_own_page_is_accepted(headers):
    assert _ask(headers).json() == GRANTED


def test_default_ports_compare_equal():
    assert _ask({"Origin": "http://localhost"}, base_url="http://localhost").json() == GRANTED
    assert _ask({"Origin": "http://localhost:80"}, base_url="http://localhost").json() == GRANTED
    assert _ask({"Origin": "http://localhost:81"}, base_url="http://localhost").json() == DENIED


@pytest.mark.parametrize("client", [("192.168.1.100", 50000), ("100.101.102.103", 50000), ("172.17.0.1", 50000),
                                    ("203.0.113.9", 443), ("::ffff:192.168.1.5", 50000)])
def test_another_device_is_refused_even_when_it_names_this_machine(client):
    assert _ask({"Host": "localhost:5000"}, client=client).json() == DENIED


def test_a_reverse_proxy_is_refused():
    assert _ask({"X-Forwarded-For": "203.0.113.9"}).json() == DENIED
    assert _ask({"Tailscale-User-Login": "owner@example.com", "X-Forwarded-Host": "desktop.tailnet-name.ts.net"}).json() == DENIED


def test_every_answer_is_uncacheable_and_a_refusal_never_says_why(monkeypatch):
    granted = _ask()
    refusals = [
        _ask({"Host": "attacker.example"}),
        _ask({"Origin": "https://attacker.example"}),
        _ask({"Sec-Fetch-Site": "cross-site"}),
        _ask({"X-Forwarded-For": "203.0.113.9"}),
        _ask(client=("192.168.1.100", 50000)),
    ]
    monkeypatch.setattr(settings, "LOCAL_AUTO_LOGIN", False)
    refusals.append(_ask())
    for res in [granted, *refusals]:
        assert res.status_code == 200
        assert res.headers["cache-control"] == "no-store"
        assert res.headers["cross-origin-resource-policy"] == "same-origin"
        assert "access-control-allow-origin" not in res.headers
    assert {res.text for res in refusals} == {refusals[0].text}
    assert refusals[0].json() == DENIED


# ── The switch in 設定 → 系統 ───────────────────────────────────

def test_the_switch_is_a_system_setting_and_applies_at_once():
    with TestClient(app, base_url=LOCAL, client=("127.0.0.1", 50000)) as browser:
        field = _field(browser.get("/api/settings", headers=HEADERS).json())
        assert field == {**field, "label": "這台電腦免登入", "kind": "bool", "value": True, "source": "default"}
        assert field["help"]

        off = browser.put("/api/settings", headers=HEADERS, json={"values": {"LOCAL_AUTO_LOGIN": False}})
        assert off.status_code == 200, off.text
        assert _field(off.json()) == {**_field(off.json()), "value": False, "source": "app"}
        assert settings.LOCAL_AUTO_LOGIN is False
        assert browser.get(URL).json() == DENIED
        assert browser.get("/api/items/stats", headers=HEADERS).status_code == 200  # the key still works

        on = browser.put("/api/settings", headers=HEADERS, json={"values": {"LOCAL_AUTO_LOGIN": True}})
        assert _field(on.json())["value"] is True
        assert browser.get(URL).json() == GRANTED

        audit = browser.get("/api/settings/audit", headers=HEADERS).json()["entries"]
        assert [(e["key"], e["label"], e["group"], e["action"]) for e in audit] == [
            ("LOCAL_AUTO_LOGIN", "這台電腦免登入", "系統", "set")] * 2


def test_the_switch_survives_a_restart():
    from app import database
    with TestClient(app, base_url=LOCAL) as browser:
        browser.put("/api/settings", headers=HEADERS, json={"values": {"LOCAL_AUTO_LOGIN": False}})
    app_settings.restore_baseline()  # what a fresh process starts from
    assert settings.LOCAL_AUTO_LOGIN is True
    database.init_db()
    assert settings.LOCAL_AUTO_LOGIN is False
    assert _ask().json() == DENIED


def test_an_install_with_false_in_env_stays_off_until_the_owner_switches_it_on(monkeypatch):
    monkeypatch.setattr(settings, "LOCAL_AUTO_LOGIN", False)  # what .env provides
    with TestClient(app, base_url=LOCAL, client=("127.0.0.1", 50000)) as browser:
        assert browser.get(URL).json() == DENIED
        field = _field(browser.get("/api/settings", headers=HEADERS).json())
        assert (field["value"], field["source"], field["env_available"]) == (False, "env", True)

        on = browser.put("/api/settings", headers=HEADERS, json={"values": {"LOCAL_AUTO_LOGIN": True}})
        field = _field(on.json())
        assert (field["value"], field["source"], field["env_value"]) == (True, "app", False)
        assert browser.get(URL).json() == GRANTED

        back = browser.put("/api/settings", headers=HEADERS, json={"reset": ["LOCAL_AUTO_LOGIN"]})
        assert (_field(back.json())["value"], _field(back.json())["source"]) == (False, "env")
        assert browser.get(URL).json() == DENIED


def test_the_switch_is_no_longer_listed_as_a_read_only_startup_setting():
    with TestClient(app) as browser:
        body = browser.get("/api/settings", headers=HEADERS).json()
    assert [row["key"] for row in body["bootstrap"]] == ["HOST", "PORT", "DATABASE_PATH", "API_KEY"]
    assert [group["id"] for group in body["groups"]][-1] == "system"
