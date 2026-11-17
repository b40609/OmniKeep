"""The architecture diagram of a GitHub project's deep analysis (prompt rule "架構圖" in app/pipeline.py).

The model writes an ```arch block of plain lines, no quotes, so it survives being a JSON string;
frontend/src/lib/archchart.ts draws it. Before it is saved, this module:
- keeps only the file paths that exist in the repository (app/parsers/github_repo.py), so a link on
  a card never leads to a 404; with no file list at hand every path is dropped. A path may carry a
  line range (「app/main.py:10-40」) when the analysis saw those lines in the core-file excerpts;
  a range it could not have seen is cut back to the bare path;
- adds a 「專案：owner/repo@commit」 line, so the drawing knows where the files live and the links
  stay on the commit the analysis read;
- checks the block against the drawing's rules (check_arch). Like Archify's validator, the problems
  are named so the model can be asked once to fix them (app/pipeline.py); a block that still breaks
  them is left out rather than drawn wrong (drop_arch).
"""
from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

_BLOCK = re.compile(r"```arch[ \t]*\n(.*?)```", re.S)
_SEP = re.compile(r"\s*[｜|]\s*")
_FILE_SEP = re.compile(r"\s*[、,，;；]\s*")
_RANGE = re.compile(r"^(.*?)(?::|#L|\s*第\s*)(\d+)(?:\s*[-–~到]\s*L?(\d+))?\s*行?$")
# the field that holds the files, counted from the line's kind: 入口 and 元件 have 10 fields, 旁 has 11
_FILES_AT = {"入口": 9, "元件": 9, "旁": 10}
_ID = re.compile(r"^[A-Za-z][\w-]{0,15}$")
ICONS = {"user", "bot", "globe", "chart", "list", "check", "replay", "coins", "layers", "stamp", "cpu", "shield",
         "swap", "db", "box", "file", "code", "search", "cloud", "key", "bell", "chat", "image", "play", "gear",
         "link", "lock", "mail", "server", "terminal", "clock", "folder", "filter", "send", "download"}
_KINDS = {"一般", "重點", "關卡"}
MAX_INPUTS, MAX_LANES, MAX_PER_LANE, MAX_SIDES = 3, 3, 5, 2


def _known(paths: Iterable[str]):
    files = set(paths)
    dirs = {p.rsplit("/", i)[0] for p in files for i in range(1, p.count("/") + 1)}
    return files, dirs


def _clean_file(raw: str) -> str:
    return raw.strip().strip("`'\"").removeprefix("./").strip("/")


def _file_ref(raw: str, known_files, known_dirs, seen: Dict[str, int]) -> str:
    """A checked 「path」 or 「path:a-b」, or '' for a path the repository does not have."""
    ref = _clean_file(raw)
    m = _RANGE.match(ref)
    path, a, b = (_clean_file(m.group(1)), int(m.group(2)), int(m.group(3) or m.group(2))) if m else (ref, 0, 0)
    if not path or not (path in known_files or path in known_dirs):
        return ""
    if a and path in seen and 1 <= a <= b <= seen[path]:
        return f"{path}:{a}-{b}" if b != a else f"{path}:{a}"
    return path


def tidy_block(body: str, repo: str, files: List[str], seen: Optional[Dict[str, int]] = None) -> str:
    known_files, known_dirs = _known(files)
    seen = seen or {}
    out: List[str] = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith(("專案：", "專案:")):
            continue
        f = _SEP.split(line)
        # a 元件 line that skipped the 小標籤 column has the kind where the tag goes: put the column back
        # so the files land at their place (the reader does the same for blocks saved before this)
        if f[0] == "元件" and len(f) < 10 and len(f) > 6 and f[5] in _KINDS and f[6] not in _KINDS:
            f.insert(5, "")
            line = "｜".join(f)
        at = _FILES_AT.get(f[0])
        if at is not None and len(f) > at:
            keep: List[str] = []
            for p in (_file_ref(x, known_files, known_dirs, seen) for x in _FILE_SEP.split(f[at])):
                if p and p not in keep:
                    keep.append(p)
            f[at] = "、".join(keep[:3])
            line = "｜".join(f)
        out.append(line)
    if repo:
        head = [i for i, x in enumerate(out) if x.startswith(("總結：", "總結:"))]
        out.insert(head[0] + 1 if head else 0, f"專案：{repo}")
    return "\n".join(out) + "\n"


def tidy_arch(markdown: str, repo: Optional[str], files: List[str], sha: str = "",
              seen: Optional[Dict[str, int]] = None) -> str:
    """Every ```arch block of a deep analysis, with checked file paths and the 專案 line."""
    if not markdown or "```arch" not in markdown:
        return markdown
    if not repo:  # not a GitHub project: no files to point at; the diagram still draws
        return _BLOCK.sub(lambda m: "```arch\n" + tidy_block(m.group(1), "", []) + "```", markdown)
    where = f"{repo}@{sha}" if sha else repo
    return _BLOCK.sub(lambda m: "```arch\n" + tidy_block(m.group(1), where, files, seen if sha else None) + "```",
                      markdown)


def arch_body(markdown: str) -> Optional[str]:
    m = _BLOCK.search(markdown or "")
    return m.group(1) if m else None


def check_arch(body: str) -> List[str]:
    """The rule breaks that would make the drawing drop or misplace something, in words the model
    can act on; [] when the block draws as written. Small slips (an unknown icon, a second 重點) are
    not listed: the drawing already handles them."""
    problems: List[str] = []
    ids: Dict[str, str] = {}
    lanes: List[List[str]] = []
    inputs, sides = [], []
    gist = False
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(("總結：", "總結:")):
            gist = True
            continue
        if line.startswith(("附註", "專案")):
            continue
        f = _SEP.split(line)
        kind = f[0]
        if kind == "區":
            lanes.append([])
            continue
        if kind not in ("入口", "元件", "旁"):
            problems.append(f"「{line[:30]}」不是任何一種行（總結、附註、入口、區、元件、旁）")
            continue
        nid = f[1] if len(f) > 1 else ""
        if not _ID.match(nid):
            problems.append(f"{kind}「{line[:30]}」的 ID「{nid}」不合格式：英文字母開頭，最多 16 個英數字")
            continue
        if nid in ids:
            problems.append(f"ID「{nid}」重複了")
            continue
        if len(f) < 4 or not f[3]:
            problems.append(f"{kind}「{nid}」沒有名稱")
            continue
        ids[nid] = kind
        if kind == "入口":
            inputs.append((nid, f[5] if len(f) > 5 else ""))
        elif kind == "元件":
            if not lanes:
                lanes.append([])
            lanes[-1].append(nid)
        else:
            sides.append((nid, f[5] if len(f) > 5 else ""))
    if not gist:
        problems.append("第一行要寫「總結：」")
    split = [l[i:i + MAX_PER_LANE] for l in lanes if l for i in range(0, len(l), MAX_PER_LANE)]
    shown = [x for l in split[:MAX_LANES] for x in l]
    hidden = [x for l in split[MAX_LANES:] for x in l]
    if hidden:
        problems.append(f"區太多或元件太多：最多 {MAX_LANES} 區、每區 {MAX_PER_LANE} 個，"
                        f"{'、'.join(hidden)} 會畫不出來；合併相近的元件")
    if len(shown) + len(sides) < 4:
        problems.append("元件與旁合計要 4 個以上；不到 4 個就整個不要畫架構圖")
    if not inputs:
        problems.append("至少要 1 個入口")
    if len(inputs) > MAX_INPUTS:
        problems.append(f"入口最多 {MAX_INPUTS} 個，現在有 {len(inputs)} 個")
    first = split[0] if split else []
    for nid, to in inputs[:MAX_INPUTS]:
        if to not in first:
            problems.append(f"入口「{nid}」接到「{to}」，但接到只能填第一區的元件：{'、'.join(first) or '（沒有）'}")
    ends = {l[-1] for l in split[:MAX_LANES - 1][:len(split) - 1]} if len(split) > 1 else set()
    parents: List[str] = []
    for nid, parent in sides:
        if parent not in shown:
            problems.append(f"旁「{nid}」接在「{parent}」，但沒有這個元件")
        elif parent in ends:
            problems.append(f"旁「{nid}」接在「{parent}」，那是這一區最後一個元件，線要往下一區走，不能接旁；改接同區前面的元件")
        elif parent in parents:
            problems.append(f"旁「{nid}」和另一個旁都接在「{parent}」，每個元件最多接 1 個")
        parents.append(parent)
    if len(sides) > MAX_SIDES:
        problems.append(f"旁最多 {MAX_SIDES} 個，現在有 {len(sides)} 個")
    return problems


def replace_arch(markdown: str, body: str) -> str:
    return _BLOCK.sub(lambda m: "```arch\n" + body.strip("\n") + "\n```", markdown, count=1)


_DETAILS = re.compile(r"<details[^>]*>\s*<summary>[^<]*</summary>\s*```arch[ \t]*\n.*?```\s*</details>\s*", re.S)


def drop_arch(markdown: str) -> str:
    """The analysis without its architecture diagram (the whole 系統架構 section)."""
    out = _DETAILS.sub("", markdown)
    if "```arch" in out:  # not inside the usual <details>: drop the block alone
        out = re.sub(r"```arch[ \t]*\n.*?```\s*", "", out, flags=re.S)
    return out.rstrip() + "\n" if out.strip() else ""
