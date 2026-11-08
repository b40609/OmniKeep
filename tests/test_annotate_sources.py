"""scripts/annotate_sources.py: mark where each point of a deep analysis comes from."""
import asyncio
import importlib.util
from pathlib import Path

import pytest

from app import ai_connections
from app import database as db

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("annotate_sources", ROOT / "scripts" / "annotate_sources.py")
tool = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tool)

CONTENT = "RRF 把多份排序結果合併。每份清單中排名 r 的文件得分為 1/(k+r)，k 常取 60。它不需要校準分數尺度。"
DEEP = """## 系統架構與關鍵技術規格

- **合併方式**：每份清單中排名 r 的文件得分 1/(k+r)。
- **常數**：k 一般設成 60，降低前段名次的權重差距。
- **限制**：會忽略原始分數的差距大小。
- **延伸元件**：
  - 這一層才是內容，但原文沒提到，應該標無出處。

```
- 這行在程式碼裡，不算重點
```

### 💡 專屬決策評估與落地啟發

- **建議**：OmniKeep 可以沿用這個做法。"""


class FakeProvider:
    def __init__(self, answer):
        self.answer = answer
        self.prompts = []

    async def generate_json(self, prompt, system_prompt=None):
        self.prompts.append(prompt)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _item(item_id, deep=DEEP, content=CONTENT):
    db.save_item({"id": item_id, "url": f"https://example.com/{item_id}", "title_l1": "RRF", "summary_l1": "摘要",
                  "deep_analysis": deep, "category_name": "文章", "content_raw": content, "source_type": "web"})


def test_only_factual_bullets_outside_code_and_own_view_sections_are_points():
    texts = [t for _, t in tool.claims(DEEP)]
    assert texts == ["合併方式：每份清單中排名 r 的文件得分 1/(k+r)。", "常數：k 一般設成 60，降低前段名次的權重差距。",
                     "限制：會忽略原始分數的差距大小。", "這一層才是內容，但原文沒提到，應該標無出處。"]


def test_only_quotes_that_really_occur_in_the_original_are_kept():
    answer = {"evidence": [{"n": 1, "quote": "每份清單中排名 r 的文件得分為 1/(k+r)"},
                           {"n": 2, "quote": "k 常取６０"},                # full-width digits still match
                           {"n": 3, "quote": "原始分數差距會被忽略"}]}     # not in the original
    assert tool.verified_quotes(answer, CONTENT, 3) == {1: "每份清單中排名 r 的文件得分為 1/(k+r)", 2: "k 常取６０"}
    with pytest.raises(ValueError):
        tool.verified_quotes({"oops": []}, CONTENT, 3)


@pytest.fixture
def setup(isolated_runtime, monkeypatch):
    conn = ai_connections.create({"card": "kilo"})
    fake = FakeProvider({"evidence": [{"n": 1, "quote": "每份清單中排名 r 的文件得分為 1/(k+r)"},
                                      {"n": 2, "quote": "k 常取 60"}, {"n": 3, "quote": ""}]})
    monkeypatch.setattr(tool, "build_provider", lambda c: fake)
    return conn, fake, isolated_runtime / "sources"


def _run(conn, out, **kw):
    return asyncio.run(tool.run(conn.id, out, kw.get("limit"), 1, kw.get("stop_after", 3)))


def test_marks_points_appends_sources_and_can_run_again_or_restore(setup):
    conn, fake, out = setup
    _item("s1")
    stats = _run(conn, out)
    assert (stats["done"], stats["points"], stats["sourced"]) == (1, 4, 2)
    deep = db.get_item_by_id("s1")["deep_analysis"]
    assert "1/(k+r)。 〔原文 1〕" in deep and "權重差距。 〔原文 2〕" in deep and "差距大小。 〔無出處〕" in deep
    assert "沿用這個做法。 〔" not in deep  # own-view section untouched
    assert "延伸元件**： 〔" not in deep and "應該標無出處。 〔無出處〕" in deep  # labels are skipped
    assert tool.SECTION in deep and "〔原文 1〕「每份清單中排名 r 的文件得分為 1/(k+r)」" in deep

    # Running again from scratch replaces the marks instead of stacking them.
    (out / "done.jsonl").unlink()
    _run(conn, out)
    again = db.get_item_by_id("s1")["deep_analysis"]
    assert again.count(tool.SECTION) == 1 and again.count("〔原文 1〕") == 2  # one mark + one source line

    assert tool.restore(out) == 1
    assert db.get_item_by_id("s1")["deep_analysis"] == DEEP


def test_failures_change_nothing_and_stop_the_run(setup):
    conn, fake, out = setup
    for i in range(4):
        _item(f"f{i}")
    fake.answer = RuntimeError("spend cap reached")
    stats = _run(conn, out, stop_after=2)
    assert stats["stopped"] == 1 and stats["done"] == 0
    assert all(db.get_item_by_id(f"f{i}")["deep_analysis"] == DEEP for i in range(4))


def test_an_analysis_rewritten_while_waiting_is_left_alone(setup, monkeypatch):
    conn, fake, out = setup
    _item("r1")
    original = fake.generate_json

    async def rewrite_meanwhile(prompt, system_prompt=None):
        db.update_item_field("r1", {"deep_analysis": "## 新版\n\n- 另一個工作剛寫好的內容，夠長的一條重點"})
        return await original(prompt, system_prompt)

    monkeypatch.setattr(fake, "generate_json", rewrite_meanwhile)
    stats = _run(conn, out)
    assert stats["changed"] == 1
    assert db.get_item_by_id("r1")["deep_analysis"].startswith("## 新版")


def test_a_quote_over_two_lines_is_listed_on_one_line():
    found = [(0, "合併方式")]
    text, sourced = tool.annotate("- 合併方式", found, {1: "每份清單中排名 r\n的文件"})
    assert sourced == 1 and "「每份清單中排名 r 的文件」" in text
