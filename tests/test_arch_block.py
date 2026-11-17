"""The GitHub project architecture diagram: file list, path checks and the prompt rule."""
import asyncio

import pytest

from app import pipeline
from app.arch_block import tidy_arch
from app.parsers import github_repo
from app.parsers.github_repo import files_in, files_section, keep_path, repo_from_url

BLOCK = """> 值得看。

<details open>
<summary>系統架構：兩段</summary>

```arch
總結：資料從網頁進來，處理後存起來。
附註：只開本機埠
入口｜you｜user｜你｜網頁｜api｜請求｜｜｜web/
區｜收｜先收｜
元件｜api｜server｜API｜收請求｜｜一般｜｜｜app/main.py、app/nope.py、./app/routers
元件｜db｜db｜資料庫｜存起來｜SQLite｜重點｜｜重點一；重點二｜app/db.py
旁｜emb｜cpu｜向量｜算向量｜db｜文字｜向量｜｜｜`app/vector.py`
```

</details>"""

FILES = ["app/main.py", "app/db.py", "app/vector.py", "app/routers/items.py", "web/index.html"]


@pytest.mark.parametrize("url, repo", [
    ("https://github.com/acme/Widget", ("acme", "Widget")),
    ("https://github.com/owner/repo.git", ("owner", "repo")),
    ("https://github.com/owner/repo/tree/main/src", ("owner", "repo")),
    ("https://github.com/owner/repo#snippet-1", ("owner", "repo")),
    ("https://github.com/owner/repo/issues/3", None),
    ("https://github.com/topics/python", None),
    ("https://github.com/owner", None),
    ("https://gitlab.com/owner/repo", None),
])
def test_repo_from_url(url, repo):
    assert repo_from_url(url) == repo


def test_build_output_media_and_locks_are_left_out():
    assert keep_path("app/main.py")
    assert not keep_path("node_modules/x/index.js")
    assert not keep_path("docs/shot.png")
    assert not keep_path("package-lock.json")
    assert not keep_path("static/app.min.js")


def test_file_list_round_trips_through_the_page_text():
    text = "README 內文\n\n" + files_section(FILES)
    assert files_in(text) == sorted(FILES, key=str.lower)
    assert files_section([]) == ""
    assert files_in("沒有清單") == []


def test_only_existing_paths_stay_and_the_repo_line_is_added():
    out = tidy_arch(BLOCK, "owner/repo", FILES)
    lines = out.split("```arch\n", 1)[1].split("```", 1)[0].splitlines()
    assert lines[0].startswith("總結：") and lines[1] == "專案：owner/repo"
    api = next(x for x in lines if x.startswith("元件｜api"))
    assert api.endswith("｜app/main.py、app/routers")  # made-up path dropped, folder kept, ./ removed
    assert next(x for x in lines if x.startswith("旁｜emb")).endswith("｜app/vector.py")
    assert next(x for x in lines if x.startswith("入口｜you")).endswith("｜web")
    assert "<details open>" in out and out.endswith("</details>")


def test_a_line_that_skipped_the_tag_column_gets_it_back_and_its_files_checked():
    from app.arch_block import tidy_block
    NL = chr(10)
    body = "元件｜api｜server｜服務｜收請求｜重點｜細節｜事實｜app/main.py、made/up.py" + NL + "元件｜db｜db｜儲存｜寫入｜重點｜一般｜｜｜app/main.py"
    out = tidy_block(body, "", FILES).splitlines()
    assert out[0] == "元件｜api｜server｜服務｜收請求｜｜重點｜細節｜事實｜app/main.py"
    assert out[1].split("｜")[5:7] == ["重點", "一般"]  # a full line whose tag reads like a kind is left alone


def test_without_a_file_list_no_path_is_kept():
    out = tidy_arch(BLOCK, "owner/repo", [])
    assert "app/main.py" not in out and "專案：owner/repo" in out


def test_not_a_github_project_gets_no_repo_line():
    out = tidy_arch(BLOCK, None, [])
    assert "專案" not in out and "app/db.py" not in out
    assert tidy_arch("沒有架構圖", None, []) == "沒有架構圖"


def test_the_prompt_cut_keeps_the_file_list_whole():
    text = "x" * 20000 + "\n\n" + files_section(FILES)
    cut = pipeline.keep_files_section(text, 12000)
    assert len(cut) == 12000 and files_in(cut) == sorted(FILES, key=str.lower)
    assert pipeline.keep_files_section("短", 12000) == "短"


def test_prompt_has_the_architecture_rule():
    prompt = pipeline.analysis_system_prompt()
    assert "架構圖：只有 GitHub 專案" in prompt and "```arch" in prompt
    assert "<details open>" in prompt


def test_file_list_fetch_failure_is_empty(monkeypatch):
    class Boom:
        async def __aenter__(self):
            raise OSError("offline")

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(github_repo, "public_http_client", lambda **kw: Boom())
    assert asyncio.run(github_repo.fetch_repo_files("owner", "repo")) == []


def test_repo_lookup_refused_is_empty_not_a_crash(monkeypatch):
    # GitHub's 403 (rate limit) used to return a bare list, and every caller then failed on ["paths"].
    class Reply:
        status_code = 403

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **kw):
            return Reply()

    monkeypatch.setattr(github_repo, "public_http_client", lambda **kw: Client())
    assert asyncio.run(github_repo.fetch_repo("owner", "repo")) == {"paths": [], "sha": "", "sizes": {}}
    assert asyncio.run(github_repo.fetch_repo_files("owner", "repo")) == []


# ── checks before delivery (Archify-style), line ranges and the commit ──────────

from app.arch_block import arch_body, check_arch, drop_arch  # noqa: E402
from app.parsers.github_repo import core_files, excerpts_in, excerpts_section  # noqa: E402

GOOD = """總結：資料從網頁進來，處理後存起來。
入口｜you｜user｜你｜網頁｜api｜請求｜｜｜
區｜收｜先收｜
元件｜api｜server｜API｜收請求｜｜一般｜｜｜
元件｜parse｜file｜解析｜抽重點｜｜一般｜｜｜
區｜存｜存起來｜結果
元件｜db｜db｜資料庫｜存起來｜｜重點｜｜｜
元件｜idx｜search｜索引｜找得到｜｜一般｜｜｜
旁｜emb｜cpu｜向量｜算向量｜db｜文字｜向量｜｜｜
"""


def test_a_good_block_passes_the_checks():
    assert check_arch(GOOD) == []


def test_the_checks_name_what_the_drawing_would_drop():
    bad = GOOD.replace("｜api｜請求", "｜db｜請求").replace("｜db｜文字", "｜parse｜文字")
    problems = check_arch(bad.replace("總結：資料從網頁進來，處理後存起來。\n", ""))
    text = "\n".join(problems)
    assert "總結" in text and "第一區" in text and "最後一個元件" in text


def test_too_few_cards_is_a_problem():
    assert any("4 個以上" in p for p in check_arch("總結：x\n入口｜u｜user｜你｜｜a｜｜｜｜\n元件｜a｜box｜甲｜｜｜一般｜｜｜\n元件｜b｜box｜乙｜｜｜一般｜｜｜\n"))


def test_drop_removes_the_whole_section_only():
    md = "> 值得看。\n\n" + BLOCK + "\n\n## 限制\n- 只有英文"
    out = drop_arch(md)
    assert "```arch" not in out and "系統架構" not in out and "## 限制" in out and out.startswith("> 值得看。")


SHA = "a" * 40


def test_line_ranges_stay_only_for_lines_the_analysis_saw():
    block = BLOCK.replace("app/main.py、app/nope.py、./app/routers", "app/main.py:10-40、app/db.py:5-9、app/routers")
    out = tidy_arch(block, "owner/repo", FILES, sha=SHA, seen={"app/main.py": 120})
    body = arch_body(out)
    assert f"專案：owner/repo@{SHA}" in body
    api = next(x for x in body.splitlines() if x.startswith("元件｜api"))
    assert api.endswith("｜app/main.py:10-40、app/db.py、app/routers")  # db.py was not in the excerpts
    out = tidy_arch(block.replace("10-40", "100-200"), "owner/repo", FILES, sha=SHA, seen={"app/main.py": 120})
    assert "app/main.py:100" not in out and "app/main.py、" in out


def test_core_files_pick_entry_points_not_tests():
    paths = ["README.md", "app/main.py", "app/db.py", "tests/test_x.py", "docs/conf.py", "app/__init__.py", "setup.py"]
    picks = core_files(paths, {"app/main.py": 3000, "app/db.py": 20000, "app/__init__.py": 10, "setup.py": 900})
    assert picks[0] == "app/main.py" and "tests/test_x.py" not in picks and "setup.py" not in picks


def test_excerpts_round_trip_with_line_numbers():
    text = excerpts_section(SHA, [("app/main.py", "import os\n\nprint(1)\n")])
    assert "1| import os" in text and "3| print(1)" in text
    assert excerpts_in("README\n\n" + text) == (SHA, {"app/main.py": 3})
    assert excerpts_section(SHA, []) == ""


def test_the_prompt_cut_keeps_the_page_when_the_tail_is_long():
    tail = files_section(FILES) + "\n\n" + excerpts_section(SHA, [("app/main.py", ("y" * 100 + "\n") * 2000)])
    text = "R" * 20000 + "\n\n" + tail
    cut = pipeline.keep_files_section(text, 12000)
    assert cut.count("R") == 8000 and cut.endswith(tail)


def _run_settle(monkeypatch, reply):
    class P:
        calls = 0

        async def generate_text(self, prompt, system_prompt=None):
            P.calls += 1
            assert "第一行要寫「總結：」" in prompt
            return reply

    monkeypatch.setattr(pipeline, "get_primary_provider", lambda: P())
    md = "<details open>\n<summary>系統架構：兩段</summary>\n\n```arch\n" + GOOD.split("\n", 1)[1] + "```\n\n</details>"
    return asyncio.run(pipeline.settle_arch(md, "https://github.com/owner/repo", "")), P.calls


def test_a_broken_diagram_is_sent_back_once_and_fixed(monkeypatch):
    out, calls = _run_settle(monkeypatch, "```arch\n" + GOOD + "```")
    assert calls == 1 and "總結：資料從網頁進來" in out and "專案：owner/repo" in out


def test_a_diagram_still_broken_after_the_fix_is_left_out(monkeypatch):
    out, calls = _run_settle(monkeypatch, "```arch\n" + GOOD.split("\n", 1)[1] + "```")
    assert calls == 1 and "```arch" not in out
