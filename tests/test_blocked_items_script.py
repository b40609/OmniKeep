"""scripts/blocked_items.py: list items holding only an error page; mark or refetch them, restorably."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app import database as db
from app.config import settings
from app.pipeline import FETCH_FAILED_TAG

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("blocked_items", ROOT / "scripts" / "blocked_items.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

X_PAGE = ("We’ve detected that JavaScript is disabled in this browser. Please enable JavaScript or switch to a "
          "supported browser to continue using x.com. You can see a list of supported browsers in our Help Center.")
MADE_UP = "## X 平台客戶端渲染機制\n- 一整篇看似專業、其實是捏造的分析"
GOOD = {"category": "Inbox", "title_l1": "推文：免費 API 整理", "summary_l1": "整理了幾個免費 API 平台。",
        "tech_tags": ["API"], "deep_analysis": "## 重點\n- Cohere 試用金鑰", "is_composite": False,
        "sub_entities": []}


def _save(item_id, content, source_type="web", **extra):
    db.save_item({"id": item_id, "url": f"https://x.com/u/status/{item_id}", "source_type": source_type,
                  "title_l1": "X 平台存取限制分析", "summary_l1": "捏造的摘要", "tech_tags": ["X", "SPA"],
                  "deep_analysis": MADE_UP, "content_raw": content, "category_name": "Inbox", **extra})


@pytest.fixture
def items():
    _save("blocked1", X_PAGE)
    _save("normal1", "這是一篇關於混合搜尋的長文，內容完整。" * 20)
    _save("video1", X_PAGE, source_type="youtube")  # not scraped page text: never touched
    return settings.DATABASE_PATH


def test_listing_finds_only_error_pages_and_changes_nothing(items, isolated_runtime, capsys):
    before = {i: db.get_item_by_id(i) for i in ("blocked1", "normal1", "video1")}
    found = tool.scan(items)
    assert [(i["id"], i["reason"]) for i in found] == [("blocked1", "js_required")]
    report = isolated_runtime / "list.md"
    assert tool.main(["--db", items, "--report", str(report)]) == 0
    assert "blocked1" in report.read_text(encoding="utf-8") and "normal1" not in capsys.readouterr().out
    assert {i: db.get_item_by_id(i) for i in before} == before


def test_mark_keeps_a_copy_first_then_restore_puts_it_back(items, isolated_runtime):
    out = isolated_runtime / "run"
    assert tool.main(["--db", items, "--mark", "--out", str(out)]) == 0
    marked = db.get_item_by_id("blocked1")
    assert marked["summary_l1"].startswith(FETCH_FAILED_TAG)
    assert marked["deep_analysis"].startswith("> ⚠️ 擷取失敗") and MADE_UP not in marked["deep_analysis"]
    assert marked["tech_tags"] == [] and marked["title_l1"] == "x.com/u/status/blocked1"
    assert marked["content_raw"] == X_PAGE
    assert db.get_item_by_id("normal1")["deep_analysis"] == MADE_UP

    copies = tool.read_jsonl(out / "before.jsonl")
    assert [c["id"] for c in copies] == ["blocked1"] and copies[0]["deep_analysis"] == MADE_UP

    tool.main(["--db", items, "--mark", "--out", str(out)])  # already marked: nothing more
    assert len(tool.read_jsonl(out / "before.jsonl")) == 1
    assert tool.scan(items) == [] and len(tool.scan(items, include_marked=True)) == 1

    assert tool.main(["--db", items, "--restore", "--out", str(out)]) == 0
    restored = db.get_item_by_id("blocked1")
    assert restored["deep_analysis"] == MADE_UP and restored["summary_l1"] == "捏造的摘要"
    assert restored["tech_tags"] == ["X", "SPA"] and restored["title_l1"] == "X 平台存取限制分析"


def _page(content):
    return {"url": "", "title": "X", "content_raw": content, "cover_image": "", "author": "",
            "published_date": "", "raw_html": "", "http_status": 200}


def test_refetch_replaces_the_page_when_it_now_loads_and_restore_undoes_it(items, isolated_runtime):
    out = isolated_runtime / "run"
    provider = AsyncMock()
    provider.generate_json = AsyncMock(return_value=dict(GOOD))
    real = "續集來了，還有一些可以免費用的 API 平台：Cohere 提供試用金鑰，每月 1,000 次呼叫。" * 3
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(real))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        assert tool.main(["--db", items, "--ids", "blocked1", "--refetch", "--out", str(out)]) == 0
    item = db.get_item_by_id("blocked1")
    assert item["content_raw"] == real and item["deep_analysis"] == GOOD["deep_analysis"]

    tool.main(["--db", items, "--restore", "--out", str(out)])
    item = db.get_item_by_id("blocked1")
    assert item["content_raw"] == X_PAGE and item["deep_analysis"] == MADE_UP


def test_refetch_that_still_gets_the_error_page_marks_the_item(items, isolated_runtime):
    provider = AsyncMock()
    with patch("app.pipeline.parse_web_page", new=AsyncMock(return_value=_page(X_PAGE))), \
         patch("app.pipeline.get_primary_provider", return_value=provider):
        tool.main(["--db", items, "--refetch", "--out", str(isolated_runtime / "run")])
    provider.generate_json.assert_not_awaited()
    assert db.get_item_by_id("blocked1")["summary_l1"].startswith(FETCH_FAILED_TAG)


def test_writing_needs_a_backup_folder(items):
    with pytest.raises(SystemExit):
        tool.main(["--db", items, "--mark"])
    assert db.get_item_by_id("blocked1")["deep_analysis"] == MADE_UP
