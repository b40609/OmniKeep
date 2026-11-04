"""Regression test for review-20261102 bug 2.

The RadarDialog offers google_news / web_change sources, but
POST /api/radar/sources only whitelisted youtube / github / rss, so the UI
got a 400. The whitelist is now derived from the adapter registry.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database import init_db, get_all_radar_sources
from app.radar.adapters import get_adapter, supported_source_types
from app.config import settings


@pytest.fixture(autouse=True)
def _db():
    init_db()


def test_whitelist_matches_adapter_registry():
    types = supported_source_types()
    assert set(types) >= {"youtube", "github", "rss", "google_news", "web_change"}
    for t in types:
        assert get_adapter(t) is not None


@pytest.mark.parametrize("source_type,url", [
    ("google_news", "DeepSeek R1"),
    ("web_change", "https://example.test/changelog"),
    ("rss", "https://example.test/feed.xml"),
])
def test_create_source_accepts_every_registered_type(source_type, url):
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.API_KEY}"}
    resp = client.post("/api/radar/sources", headers=headers, json={
        "name": f"test {source_type}",
        "source_type": source_type.upper(),  # router lower()s it
        "url": url,
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["success"] is True
    stored = {s["id"]: s for s in get_all_radar_sources()}[resp.json()["source_id"]]
    assert stored["source_type"] == source_type
    assert stored["url"] == url


def test_create_source_rejects_unknown_type():
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.API_KEY}"}
    resp = client.post("/api/radar/sources", headers=headers, json={
        "name": "nope", "source_type": "telegram_channel", "url": "x",
    })
    assert resp.status_code == 400
    assert "google_news" in resp.json()["detail"]
