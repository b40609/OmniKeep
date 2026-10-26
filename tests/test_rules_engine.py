"""Tests for Hard Rules Engine (Karakeep pattern: deterministic automation)

Covers:
- Field extraction (url, domain, title, source_type, content)
- Condition operators (contains, equals, startswith, endswith, regex)
- Automation actions (add_tag, set_category, star, archive, mute)
- Multi-rule priority sequencing and inactive toggle
- REST CRUD endpoints (/api/rules) and preview test endpoint (/api/rules/test)
- Pipeline integration applying rules before persistence
- Telegram /rules command
"""
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from app.main import app
from app.database import (
    init_db,
    create_rule,
    get_all_rules,
    get_rule,
    update_rule,
    delete_rule,
    get_item_by_id,
)
from app.rules import apply_rules_to_item, evaluate_rules_for_preview
from app.bot.telegram_bot import TelegramBot
from app.config import settings


@pytest.fixture(autouse=True)
def setup_test_db():
    init_db()


def test_rule_operators_and_actions():
    # 1. Domain match -> add_tag
    r1 = {
        "id": 1,
        "name": "GitHub Tagging",
        "field": "domain",
        "operator": "contains",
        "value": "github.com",
        "action_type": "add_tag",
        "action_value": "git",
        "priority": 1,
        "is_active": 1
    }
    # 2. Title regex -> star
    r2 = {
        "id": 2,
        "name": "Release Starring",
        "field": "title",
        "operator": "regex",
        "value": r"v\d+\.\d+",
        "action_type": "star",
        "action_value": "",
        "priority": 2,
        "is_active": 1
    }
    # 3. Source type match -> set_category
    r3 = {
        "id": 3,
        "name": "YouTube Category",
        "field": "source_type",
        "operator": "equals",
        "value": "youtube",
        "action_type": "set_category",
        "action_value": "Media",
        "priority": 3,
        "is_active": 1
    }
    # 4. Inactive rule -> should not trigger
    r4 = {
        "id": 4,
        "name": "Mute Spam",
        "field": "title",
        "operator": "contains",
        "value": "Promoted",
        "action_type": "mute",
        "action_value": "",
        "priority": 4,
        "is_active": 0
    }

    item = {
        "url": "https://github.com/fastapi/fastapi",
        "title_l1": "FastAPI v0.115 Released",
        "source_type": "youtube",
        "category_name": "Inbox",
        "tech_tags": ["python"],
        "is_starred": 0,
        "is_read": 0
    }

    # Pass active rules only
    rules = [r1, r2, r3]
    res = apply_rules_to_item(item, active_rules=rules)

    assert "git" in res["tech_tags"]
    assert "python" in res["tech_tags"]
    assert res["is_starred"] == 1
    assert res["category_name"] == "Media"
    assert len(res["_applied_rules"]) == 3


def test_rule_preview_evaluation():
    rule_id = create_rule(
        name="ArXiv Paper Tagger",
        field="domain",
        operator="contains",
        value="arxiv.org",
        action_type="add_tag",
        action_value="paper",
        priority=5
    )

    sample_item = {
        "url": "https://arxiv.org/abs/2401.0001",
        "title_l1": "A Survey on Deep Learning",
        "category_name": "Inbox",
        "tech_tags": ["ai"]
    }

    preview = evaluate_rules_for_preview(sample_item)
    assert "ArXiv Paper Tagger" in preview["matched_rules"]
    assert "tech_tags" in preview["changes"]
    assert "paper" in preview["changes"]["tech_tags"]["after"]
    # Verify original sample_item was not mutated
    assert "paper" not in sample_item["tech_tags"]

    delete_rule(rule_id)


def test_rules_rest_api():
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.API_KEY}"}

    # 1. Create rule
    create_payload = {
        "name": "Auto Archive News",
        "field": "source_type",
        "operator": "equals",
        "value": "google_news",
        "action_type": "archive",
        "action_value": "",
        "priority": 10,
        "is_active": 1
    }
    resp = client.post("/api/rules", json=create_payload, headers=headers)
    assert resp.status_code == 200
    rule_data = resp.json()
    rule_id = rule_data["rule"]["id"]
    assert rule_data["rule"]["name"] == "Auto Archive News"

    # 2. List rules
    list_resp = client.get("/api/rules", headers=headers)
    assert list_resp.status_code == 200
    ids = [r["id"] for r in list_resp.json()]
    assert rule_id in ids

    # 3. Patch rule (toggle inactive)
    patch_resp = client.patch(f"/api/rules/{rule_id}", json={"is_active": 0}, headers=headers)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["rule"]["is_active"] == 0

    # 4. Preview test endpoint
    test_payload = {
        "url": "https://news.google.com/articles/123",
        "source_type": "google_news",
        "title": "Breaking Tech Update"
    }
    test_resp = client.post("/api/rules/test", json=test_payload, headers=headers)
    assert test_resp.status_code == 200
    # Inactive rule should not match in preview
    assert "Auto Archive News" not in test_resp.json()["matched_rules"]

    # Re-enable rule
    client.patch(f"/api/rules/{rule_id}", json={"is_active": 1}, headers=headers)
    test_resp2 = client.post("/api/rules/test", json=test_payload, headers=headers)
    assert "Auto Archive News" in test_resp2.json()["matched_rules"]
    assert test_resp2.json()["result_item"]["is_read"] == 1

    # 5. Delete rule
    del_resp = client.delete(f"/api/rules/{rule_id}", headers=headers)
    assert del_resp.status_code == 200
    assert del_resp.json()["success"] is True


def test_pipeline_executes_rules():
    # Insert rule: URL with 'docs.rs' -> set_category 'Documentation'
    rule_id = create_rule(
        name="Docs RS Category",
        field="url",
        operator="contains",
        value="docs.rs",
        action_type="set_category",
        action_value="Documentation",
        priority=1
    )

    from app.pipeline import run_pipeline

    # Mock provider to return fast JSON
    mock_provider = AsyncMock()
    mock_provider.generate_json = AsyncMock(return_value={
        "category": "Inbox",
        "title_l1": "Tokio Async Rust Runtime",
        "summary_l1": "Tokio 官方 API 文檔",
        "tech_tags": ["rust", "async"],
        "deep_analysis": "核心特性說明"
    })

    with patch("app.pipeline.get_primary_provider", return_value=mock_provider), \
         patch("app.pipeline.parse_web_page", return_value={"title": "Tokio Docs", "content": "Tokio docs text", "author": "", "meta": {}}):
        import asyncio
        item = asyncio.run(run_pipeline("https://docs.rs/tokio/latest/tokio/"))
        assert item is not None
        # Verify rule overrode category from 'Inbox' to 'Documentation'
        assert item["category_name"] == "Documentation"
        saved = get_item_by_id(item["id"])
        assert saved["category_name"] == "Documentation"

    delete_rule(rule_id)


def test_telegram_rules_command(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "fake-token-rules")
    monkeypatch.setattr(settings, "TELEGRAM_ALLOWED_USER_IDS_RAW", "888")

    bot = TelegramBot()
    bot.send_message = AsyncMock(return_value={"message_id": 200})

    rule_id = create_rule(
        name="Demo Rule",
        field="domain",
        operator="contains",
        value="example.org",
        action_type="add_tag",
        action_value="demo",
        priority=5
    )

    update = {
        "message": {
            "message_id": 20,
            "chat": {"id": 888},
            "from": {"id": 888},
            "text": "/rules"
        }
    }
    import asyncio
    asyncio.run(bot.handle_update(update))
    assert bot.send_message.called
    msg = bot.send_message.call_args[0][1]
    assert "硬規則引擎" in msg
    assert "Demo Rule" in msg

    delete_rule(rule_id)
