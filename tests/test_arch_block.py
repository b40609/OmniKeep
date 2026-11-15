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
