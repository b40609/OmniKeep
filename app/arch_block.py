"""The architecture diagram of a GitHub project's deep analysis (prompt rule "架構圖" in app/pipeline.py).

The model writes an ```arch block of plain lines, no quotes, so it survives being a JSON string;
frontend/src/lib/archchart.ts draws it. Before it is saved, this module:
- keeps only the file paths that exist in the repository (app/parsers/github_repo.py), so a link on
  a card never leads to a 404; with no file list at hand every path is dropped;
- adds a 「專案：owner/repo」 line, so the drawing knows where the files live.
Everything else is left for the drawing, which shows a plain list when the block does not parse.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Optional

_BLOCK = re.compile(r"```arch[ \t]*\n(.*?)```", re.S)
_SEP = re.compile(r"\s*[｜|]\s*")
_FILE_SEP = re.compile(r"\s*[、,，;；]\s*")
# the field that holds the files, counted from the line's kind: 入口 and 元件 have 10 fields, 旁 has 11
_FILES_AT = {"入口": 9, "元件": 9, "旁": 10}


def _known(paths: Iterable[str]):
    files = set(paths)
    dirs = {p.rsplit("/", i)[0] for p in files for i in range(1, p.count("/") + 1)}
    return files, dirs


def _clean_file(raw: str) -> str:
    return raw.strip().strip("`'\"").removeprefix("./").strip("/")


def tidy_block(body: str, repo: str, files: List[str]) -> str:
    known_files, known_dirs = _known(files)
    out: List[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("專案：", "專案:")):
            continue
        f = _SEP.split(line)
        at = _FILES_AT.get(f[0])
        if at is not None and len(f) > at:
            keep = []
            for p in (_clean_file(x) for x in _FILE_SEP.split(f[at])):
                if p and p not in keep and (p in known_files or p in known_dirs):
                    keep.append(p)
            f[at] = "、".join(keep[:3])
            line = "｜".join(f)
        out.append(line)
    head = [i for i, x in enumerate(out) if x.startswith(("總結：", "總結:"))]
    out.insert(head[0] + 1 if head else 0, f"專案：{repo}")
    return "\n".join(out) + "\n"


def tidy_arch(markdown: str, repo: Optional[str], files: List[str]) -> str:
    """Every ```arch block of a deep analysis, with checked file paths and the 專案 line."""
    if not markdown or "```arch" not in markdown:
        return markdown
    if not repo:
        # not a GitHub project: no files to point at; the diagram still draws
        return _BLOCK.sub(lambda m: "```arch\n" + tidy_block(m.group(1), "", []).replace("專案：\n", "") + "```", markdown)
    return _BLOCK.sub(lambda m: "```arch\n" + tidy_block(m.group(1), repo, files) + "```", markdown)
