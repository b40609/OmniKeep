"""Experimental features (設定 › 實驗功能): off by default, switched per feature, display only."""
from contextlib import closing

import pytest
from fastapi.testclient import TestClient

from app import app_settings
from app.config import Settings, settings
from app.database import get_db_connection, get_radar_settings, update_radar_settings
from app.main import app

HEADERS = {"Authorization": f"Bearer {settings.API_KEY}"}
KEYS = ("EXPERIMENT_RADAR", "EXPERIMENT_WATCH", "EXPERIMENT_DAILY_REVIEW")


def _labs(body):
    return next(group for group in body["groups"] if group["id"] == "labs")


def _put(client, values=None, reset=None):
    return client.put("/api/settings", headers=HEADERS, json={"values": values or {}, "reset": reset or []})


def test_every_experiment_is_off_until_switched_on():
    for key in KEYS:
        assert Settings.model_fields[key].default is False
    with TestClient(app) as client:
        labs = _labs(client.get("/api/settings", headers=HEADERS).json())
    assert labs["label"] == "實驗功能"
    assert [field["key"] for field in labs["fields"]] == list(KEYS)
    for field in labs["fields"]:
        assert (field["kind"], field["value"], field["source"]) == ("bool", False, "default")
        assert field["help"]  # says what the switch does not stop


def test_switches_are_saved_one_by_one_in_the_existing_table():
    with TestClient(app) as client:
        res = _put(client, {"EXPERIMENT_RADAR": True})
        assert res.status_code == 200, res.text
        values = {field["key"]: field["value"] for field in _labs(res.json())["fields"]}
        assert values == {"EXPERIMENT_RADAR": True, "EXPERIMENT_WATCH": False, "EXPERIMENT_DAILY_REVIEW": False}
        assert settings.EXPERIMENT_RADAR is True
        # A row in the key-value table every other setting uses: no schema change.
        with closing(get_db_connection()) as conn:
            row = conn.execute("SELECT value, is_secret FROM app_settings WHERE key = 'EXPERIMENT_RADAR'").fetchone()
        assert (row["value"], row["is_secret"]) == ("true", 0)

        # Another browser (another device) reads the same answer.
        with TestClient(app) as other:
            again = _labs(other.get("/api/settings", headers=HEADERS).json())
        assert next(f for f in again["fields"] if f["key"] == "EXPERIMENT_RADAR")["value"] is True

        back = _put(client, reset=["EXPERIMENT_RADAR"])
        assert back.status_code == 200
        assert settings.EXPERIMENT_RADAR is False
        assert next(f for f in _labs(back.json())["fields"] if f["key"] == "EXPERIMENT_RADAR")["source"] == "default"


@pytest.mark.parametrize("value", ["maybe", 1, None])
def test_a_switch_takes_only_on_or_off(value):
    with TestClient(app) as client:
        res = _put(client, {"EXPERIMENT_WATCH": value})
    assert res.status_code == 400
    assert "EXPERIMENT_WATCH" in res.json()["errors"]
    assert settings.EXPERIMENT_WATCH is False


def test_changes_are_in_the_audit_log_under_their_own_group():
    with TestClient(app) as client:
        _put(client, {"EXPERIMENT_DAILY_REVIEW": True})
        entry = client.get("/api/settings/audit", headers=HEADERS).json()["entries"][0]
    assert (entry["key"], entry["label"], entry["group"], entry["action"]) == (
        "EXPERIMENT_DAILY_REVIEW", "每日回顧", "實驗功能", "set")


def test_hiding_the_radar_does_not_stop_its_background_scans():
    """The switch is display only: the scheduler reads radar_settings.enabled, nothing else."""
    update_radar_settings(enabled=True)
    with TestClient(app) as client:
        _put(client, {"EXPERIMENT_RADAR": True})
        _put(client, {"EXPERIMENT_RADAR": False})
    assert get_radar_settings()["enabled"] is True
    assert app_settings.SPEC_BY_KEY["EXPERIMENT_RADAR"].hook == ""
    update_radar_settings(enabled=False)
