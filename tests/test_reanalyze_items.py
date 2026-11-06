"""scripts/reanalyze_items.py: re-analyse stored items with one connection, after a backup."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from app import ai_connections
from app import database as db

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("reanalyze_items", ROOT / "scripts" / "reanalyze_items.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

GOOD = {"title_l1": "新標題", "summary_l1": "新摘要", "deep_analysis": "## 新的深度分析", "tech_tags": ["RRF"],
        "category": "工具", "is_composite": False, "sub_entities": []}


class FakeProvider:
    def __init__(self, answers):
        self.answers = list(answers)
        self.prompts = []

    async def generate_json(self, prompt, system_prompt=None):
        self.prompts.append(prompt)
        answer = self.answers.pop(0) if self.answers else GOOD
        if isinstance(answer, Exception):
            raise answer
        return dict(answer)


def _item(item_id, **extra):
    db.save_item({"id": item_id, "url": f"https://example.com/{item_id}", "title_l1": "舊標題",
                  "summary_l1": "舊摘要", "deep_analysis": "舊分析", "category_name": "文章",
                  "content_raw": "這是一篇關於混合搜尋的長文。" * 10, "source_type": "web", **extra})


@pytest.fixture
def setup(isolated_runtime, monkeypatch):
    conn = ai_connections.create({"card": "kilo"})
    fake = FakeProvider([])
    monkeypatch.setattr(tool, "build_provider", lambda c: fake)
    return conn, fake, isolated_runtime / "run"


def _run(conn, out, **kw):
    return asyncio.run(tool.run(conn.id, out, kw.get("limit"), 1, kw.get("stop_after", 3)))


def test_refuses_to_change_anything_before_the_backup(setup):
    conn, _, out = setup
    _item("a1")
    with pytest.raises(SystemExit):
        _run(conn, out)
    assert db.get_item_by_id("a1")["summary_l1"] == "舊摘要"


def test_backup_then_reanalyse_then_resume_then_restore(setup):
    conn, fake, out = setup
    _item("b1")
    _item("b2")
    _item("skip-proposal", source_type="proposal")
    tool.write_backup(out, tool.candidates(min_chars=0))
    first = (out / "before.jsonl").read_text(encoding="utf-8")
    assert '"b1"' in first and "skip-proposal" not in first

    stats = _run(conn, out)
    assert stats["done"] == 2 and stats["failed"] == 0
    item = db.get_item_by_id("b1")
    assert item["summary_l1"] == "新摘要" and item["deep_analysis"] == "## 新的深度分析"
    assert item["category_name"] == "文章"  # the category stays
    assert db.get_item_by_id("skip-proposal")["summary_l1"] == "舊摘要"

    # A second run skips what is done, and a second backup never replaces the first one.
    assert _run(conn, out)["todo"] == 0
    tool.write_backup(out, tool.candidates(min_chars=0))
    assert (out / "before.jsonl").read_text(encoding="utf-8") == first

    assert tool.restore(out) >= 2
    assert db.get_item_by_id("b1")["summary_l1"] == "舊摘要"


def test_failures_and_empty_answers_never_overwrite_and_stop_the_run(setup):
    conn, fake, out = setup
    for i in range(5):
        _item(f"c{i}")
    tool.write_backup(out, tool.candidates(min_chars=0))
    fake.answers = [RuntimeError("spend cap reached")] * 4 + [{}] * 10
    stats = _run(conn, out, stop_after=3)
    assert stats["stopped"] == 1 and stats["done"] == 0
    assert all(db.get_item_by_id(f"c{i}")["summary_l1"] == "舊摘要" for i in range(5))
    assert "spend cap reached" in (out / "failed.jsonl").read_text(encoding="utf-8")


def test_an_item_seen_from_its_title_only_keeps_saying_so(setup):
    conn, fake, out = setup
    tag = tool.METADATA_ONLY_TAG
    _item("d1", summary_l1=f"{tag}舊摘要", deep_analysis="> 只根據標題與說明分析\n\n舊分析", source_type="youtube")
    tool.write_backup(out, tool.candidates(min_chars=0))
    _run(conn, out)
    item = db.get_item_by_id("d1")
    assert item["summary_l1"] == f"{tag}新摘要"
    assert item["deep_analysis"].startswith("> 只根據標題與說明分析\n\n## 新的深度分析")
    tags = item["tech_tags"]
    assert (json.loads(tags) if isinstance(tags, str) else tags) == ["RRF"]
