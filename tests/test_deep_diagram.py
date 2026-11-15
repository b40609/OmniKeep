"""The architecture diagram drawn by the user's own agent (Archify): kept, served sandboxed, offline."""
import asyncio

from fastapi.testclient import TestClient

from app import database as db
from app.config import settings
from app.deep_diagram import PAGE_POLICY, agent_prompt, with_policy
from app.main import app
from app.mcp_server import attach_item_diagram

PAGE = "<!doctype html><html><head><title>x</title></head><body><script>1</script></body></html>"


def headers():
    return {"Authorization": f"Bearer {settings.API_KEY}"}


def item():
    return db.save_item({"url": "https://github.com/acme/Widget", "title_l1": "Widget", "origin": "manual"})


def test_the_page_gets_the_offline_policy_first_in_head():
    out = with_policy(PAGE)
    assert out.index(PAGE_POLICY) < out.index("<title>") and "connect-src 'none'" in out
    assert PAGE_POLICY in with_policy("<svg></svg>")


def test_put_get_delete_through_the_api():
    card = item()
    with TestClient(app) as client:
        assert client.get(f"/api/items/{card}/diagram").status_code == 401
        status = client.get(f"/api/items/{card}/diagram/status", headers=headers()).json()
        assert status["has_diagram"] is False and "tt-a1i/archify" in status["prompt"] and str(card) in status["prompt"]
        assert client.put(f"/api/items/{card}/diagram", content="not html", headers=headers()).status_code == 400
        assert client.put(f"/api/items/{card}/diagram", content=PAGE, headers=headers()).status_code == 200
        got = client.get(f"/api/items/{card}/diagram", headers=headers())
        assert got.status_code == 200 and "sandbox allow-scripts" in got.headers["content-security-policy"]
        assert "connect-src 'none'" in got.text and "<script>1</script>" in got.text
        assert client.delete(f"/api/items/{card}/diagram", headers=headers()).status_code == 200
        assert client.get(f"/api/items/{card}/diagram", headers=headers()).status_code == 404
        assert client.put("/api/items/nope/diagram", content=PAGE, headers=headers()).status_code == 404


def test_the_mcp_tool_keeps_a_file_and_refuses_other_kinds():
    from pathlib import Path
    card = item()
    tmp_path = Path(settings.DATABASE_PATH).parent
    page = tmp_path / "widget.html"
    page.write_text(PAGE, encoding="utf-8")
    assert asyncio.run(attach_item_diagram(str(card), path=str(page))).startswith("✅")
    other = tmp_path / "notes.txt"
    other.write_text(PAGE, encoding="utf-8")
    assert "只收 .html" in asyncio.run(attach_item_diagram(str(card), path=str(other)))
    assert "找不到這則收藏" in asyncio.run(attach_item_diagram("../x", html=PAGE))


def test_deleting_the_item_deletes_its_diagram():
    card = item()
    with TestClient(app) as client:
        client.put(f"/api/items/{card}/diagram", content=PAGE, headers=headers())
        assert client.delete(f"/api/items/{card}", headers=headers()).status_code == 200
    from app.deep_diagram import diagram_info
    assert diagram_info(card)["has_diagram"] is False


def test_the_prompt_says_not_to_run_the_project():
    text = agent_prompt({"id": "abc", "url": "https://github.com/acme/Widget"}, "http://127.0.0.1:5000/")
    assert "不要執行專案裡的任何腳本" in text and "http://127.0.0.1:5000/api/items/abc/diagram" in text
