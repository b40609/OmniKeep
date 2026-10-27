import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.config import settings
from app.database import seed_demo_items, get_items

client = TestClient(app, headers={"Authorization": f"Bearer {settings.API_KEY}"})

def test_seed_demo_items_database():
    items = seed_demo_items()
    assert len(items) == 3
    source_types = {it["source_type"] for it in items}
    assert "youtube" in source_types
    assert "bilibili" in source_types
    assert "web" in source_types

    all_items = get_items(limit=10)
    assert len(all_items) >= 3
    sample = next(i for i in all_items if i["source_type"] == "youtube")
    assert "Andrej Karpathy" in sample["title_l1"]
    assert sample["summary_l1"] != ""
    assert sample["deep_analysis"] != ""

def test_seed_demo_endpoint():
    res = client.post("/api/items/seed-demo")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    assert data["count"] == 3
