"""Fresh-user core workflow works without a paid provider or background radar."""

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_import_and_search_without_llm_keys(isolated_runtime, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    monkeypatch.setattr(settings, "GEMINI_API_KEYS_RAW", "")
    monkeypatch.setattr(settings, "RADAR_ENABLED", False)
    monkeypatch.setattr(settings, "LOCAL_AUTO_LOGIN", False)

    headers = {"Authorization": f"Bearer {settings.API_KEY}"}
    with TestClient(app) as client:
        guest = client.get("/api/items")
        assert guest.status_code == 401
        assert client.get("/api/session/local-auth").json()["authenticated"] is False

        imported = client.post("/api/items/import/bookmarks", headers=headers, json={
            "filename": "bookmarks.html",
            "content": '<DL><DT><A HREF="https://example.org/docs">WelcomeToOmniKeepManual</A></DL>',
            "enqueue_ai": False,
        })
        assert imported.status_code == 200
        assert imported.json()["imported_count"] == 1
        assert imported.json()["queued_count"] == 0

        found = client.get("/api/items", headers=headers, params={"q": "WelcomeToOmniKeepManual"})
        assert found.status_code == 200
        assert len(found.json()) == 1
        assert found.json()[0]["title_l1"] == "WelcomeToOmniKeepManual"
