"""Mark where each point of an item's deep analysis comes from in the original text.

For every factual bullet of `deep_analysis`, one AI connection is asked for a verbatim sentence
of the stored `content_raw` that supports it. A quote is kept only when it really occurs in the
original (compared after Unicode normalisation, ignoring spaces and case); anything else counts as
"no source". The bullet then ends with 〔原文 n〕 or 〔無出處〕, and a 「📎 原文出處」 section listing
the quotes is appended. Bullets in the model's own sections (💡 decisions, takeaways, local view,
hardware estimates) are left alone: they are not meant to come from the original.

  python scripts/annotate_sources.py --connection 15 --out backups/sources-1 --limit 10
  python scripts/annotate_sources.py --connection 15 --out backups/sources-1             # the rest
  python scripts/annotate_sources.py --out backups/sources-1 --restore                    # undo

Each item's deep analysis is appended to <out>/before.jsonl right before it is changed (so the copy
is the version that was replaced, even while another job is still rewriting analyses); --restore
puts back the first copy of each item. Finished items go to <out>/done.jsonl so a run can resume, a
failed answer changes nothing, and the run stops after --stop-after failures in a row. Only the named
connection is used. --only-ids takes a .jsonl file of {"id": ...} rows to limit the run.
"""
import argparse
import asyncio
import json
import re
import sys
import time
import unicodedata
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import ai_connections  # noqa: E402
from app.database import get_db_connection, optimize_fts, update_item_field  # noqa: E402
from app.providers import build_provider  # noqa: E402

SECTION = "### 📎 原文出處"
NOTE = "（每條重點對照原文；標「無出處」的多半是模型的延伸或推論，閱讀時請保留判斷。）"
SKIP_SOURCES = ("proposal", "watch", "insight")
# Headings of sections the model writes from its own view rather than from the original.
OWN_VIEW = ("💡", "啟發", "建議", "在地視角", "延伸", "顯存", "驗證代碼", "硬體", "決策")
BULLET = re.compile(r"^(\s*)([-*+]|\d+\.)\s+(.*\S)\s*$")
MARK = re.compile(r" ?〔(?:原文 \d+|無出處)〕")
MAX_BULLETS = 40
MAX_QUOTE = 200

SYSTEM = ("你是逐字查核助手。只根據使用者提供的原文找出處，不要推論、不要改寫。"
          "只輸出一個 JSON 物件，不要有其他文字。")


def normalise(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text or "")).lower()


def strip_annotations(deep: str) -> str:
    """The analysis without a previous run's marks and section, so a run can be repeated."""
    head = deep.split(SECTION, 1)[0].rstrip()
    return MARK.sub("", head)


def claims(deep: str) -> List[Tuple[int, str]]:
    """(line index, bullet text) for the factual bullets, outside code blocks and own-view sections."""
    out: List[Tuple[int, str]] = []
    fenced = False
    own_view = False
    for i, line in enumerate(deep.splitlines()):
        if line.strip().startswith("```"):
            fenced = not fenced
            continue
        if fenced:
            continue
        if line.lstrip().startswith("#"):
            own_view = any(word in line for word in OWN_VIEW)
            continue
        m = BULLET.match(line)
        if m and not own_view:
            text = re.sub(r"[*_`]", "", m.group(3)).strip()
            if len(text) >= 8 and not text.endswith(("：", ":")):  # a label whose points sit one level down
                out.append((i, text))
    return out[:MAX_BULLETS]


def build_prompt(content: str, bullets: List[str]) -> str:
    listed = "\n".join(f"{n}. {b}" for n, b in enumerate(bullets, 1))
    return f"""下面是一篇原文，以及根據它寫成的分析重點。請替每一條重點，從原文中找出最能支持它的一句話，逐字照抄。

規則：
- quote 必須是原文裡連續出現的文字，一字不改，最多 80 個字；可以只抄一句中的一段。
- 原文沒有支持這條重點（是延伸、推論或外部知識）就填空字串 ""，不要硬找。
- 輸出格式：{{"evidence": [{{"n": 1, "quote": "..."}}, {{"n": 2, "quote": ""}}]}}，每條重點都要有一筆。

=== 原文 ===
{content[:15000]}
=== 原文結束 ===

=== 分析重點 ===
{listed}
=== 重點結束 ==="""


def verified_quotes(answer: Any, content: str, count: int) -> Dict[int, str]:
    """n -> quote for the quotes that really occur in the original."""
    rows = answer.get("evidence") if isinstance(answer, dict) else None
    if not isinstance(rows, list):
        raise ValueError("answer has no evidence list")
    haystack = normalise(content)
    out: Dict[int, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            n = int(row.get("n"))
        except (TypeError, ValueError):
            continue
        quote = str(row.get("quote") or "").strip().strip("「」\"'")
        if 1 <= n <= count and quote and len(quote) <= MAX_QUOTE and len(normalise(quote)) >= 4 \
                and normalise(quote) in haystack:
            out[n] = quote
    return out


def annotate(deep: str, found: List[Tuple[int, str]], quotes: Dict[int, str]) -> Tuple[str, int]:
    """The analysis with marks and the source section; also how many points have a source."""
    lines = deep.splitlines()
    listed: List[str] = []
    for n, (index, _text) in enumerate(found, 1):
        if n in quotes:
            shown = re.sub(r"\s+", " ", quotes[n]).strip()  # one line, so the list item does not break
            listed.append(f"- 〔原文 {len(listed) + 1}〕「{shown}」")
            lines[index] = f"{lines[index]} 〔原文 {len(listed)}〕"
        else:
            lines[index] = f"{lines[index]} 〔無出處〕"
    body = "\n".join(lines).rstrip()
    section = [SECTION, "", NOTE, ""]
    section += listed or ["- 原文裡找不到這些重點的出處。"]
    return f"{body}\n\n" + "\n".join(section) + "\n", len(listed)


def candidates(min_chars: int = 50) -> List[Dict[str, Any]]:
    marks = ",".join("?" * len(SKIP_SOURCES))
    with closing(get_db_connection()) as db:
        rows = db.execute(
            f"SELECT id, url, source_type, deep_analysis, content_raw FROM items WHERE source_type NOT IN ({marks}) "
            "AND COALESCE(analysis_status, 'done') != 'pending' AND length(COALESCE(content_raw, '')) >= ? "
            "AND length(COALESCE(deep_analysis, '')) > 0 ORDER BY created_at DESC", (*SKIP_SOURCES, min_chars)).fetchall()
    return [dict(r) for r in rows]


def _current(item_id: str) -> Optional[Dict[str, Any]]:
    with closing(get_db_connection()) as db:
        row = db.execute("SELECT deep_analysis, content_raw FROM items WHERE id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def run(connection_id: int, out: Path, limit: Optional[int], concurrency: int, stop_after: int,
              only_ids: Optional[Path] = None) -> Dict[str, int]:
    conn = ai_connections.get_connection(connection_id)
    if conn is None:
        raise SystemExit(f"找不到連線 {connection_id}")
    out.mkdir(parents=True, exist_ok=True)
    provider = build_provider(conn)
    done_ids = {row["id"] for row in read_jsonl(out / "done.jsonl")}
    todo = [i for i in candidates() if i["id"] not in done_ids]
    if only_ids:
        wanted = {row["id"] for row in read_jsonl(only_ids)}
        todo = [i for i in todo if i["id"] in wanted]
    if limit is not None:
        todo = todo[:limit]
    stats = {"todo": len(todo), "done": 0, "failed": 0, "points": 0, "sourced": 0, "changed": 0}
    in_a_row = 0
    stop = asyncio.Event()
    sem = asyncio.Semaphore(max(1, concurrency))
    log = (out / "done.jsonl").open("a", encoding="utf-8")
    fail_log = (out / "failed.jsonl").open("a", encoding="utf-8")
    before = (out / "before.jsonl").open("a", encoding="utf-8")

    async def one(item: Dict[str, Any]) -> None:
        nonlocal in_a_row
        async with sem:
            if stop.is_set():
                return
            started = time.monotonic()
            current = _current(item["id"])  # the latest text: another job may have rewritten it since the list
            if current is None:
                return
            item = {**item, **current}
            deep = strip_annotations(item["deep_analysis"] or "")
            found = claims(deep)
            content = item.get("content_raw") or ""
            quotes: Dict[int, str] = {}
            if found:
                try:
                    answer = await provider.generate_json(build_prompt(content, [t for _, t in found]), SYSTEM)
                    quotes = verified_quotes(answer, content, len(found))
                except Exception as exc:
                    stats["failed"] += 1
                    in_a_row += 1
                    fail_log.write(json.dumps({"id": item["id"], "error": f"{type(exc).__name__}: {exc}"[:300],
                                               "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
                    fail_log.flush()
                    if in_a_row >= stop_after:
                        stop.set()
                    return
                new_deep, sourced = annotate(deep, found, quotes)
                latest = _current(item["id"])
                if latest is None or latest["deep_analysis"] != item["deep_analysis"]:
                    stats["changed"] += 1  # rewritten while we waited: leave it for a later run
                    return
                before.write(json.dumps({"id": item["id"], "deep_analysis": item["deep_analysis"]},
                                        ensure_ascii=False) + "\n")
                before.flush()
                update_item_field(item["id"], {"deep_analysis": new_deep})
            else:
                sourced = 0
            in_a_row = 0
            stats["done"] += 1
            stats["points"] += len(found)
            stats["sourced"] += sourced
            log.write(json.dumps({"id": item["id"], "points": len(found), "sourced": sourced,
                                  "seconds": round(time.monotonic() - started, 1),
                                  "at": datetime.now(timezone.utc).isoformat()}) + "\n")
            log.flush()
            if stats["done"] % 10 == 0:
                print(f"已完成 {stats['done']} / {stats['todo']}，失敗 {stats['failed']}，"
                      f"有出處 {stats['sourced']} / {stats['points']} 條", flush=True)

    try:
        await asyncio.gather(*(one(i) for i in todo))
    finally:
        log.close()
        fail_log.close()
        before.close()
    stats["stopped"] = int(stop.is_set())
    return stats


def restore(out: Path) -> int:
    first: Dict[str, str] = {}
    for row in read_jsonl(out / "before.jsonl"):
        if row.get("deep_analysis") is not None:
            first.setdefault(row["id"], row["deep_analysis"])  # the version before the first run
    for item_id, deep in first.items():
        update_item_field(item_id, {"deep_analysis": deep})
    return len(first)


def tidy_index() -> None:
    """Rewriting many items leaves the full-text index in many pieces: merge them once at the end."""
    try:
        optimize_fts()
    except Exception as exc:
        print(f"全文索引整理失敗（{type(exc).__name__}: {exc}），不影響已寫入的結果")


def main(argv: Optional[List[str]] = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--connection", type=int)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--only-ids", type=Path)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--stop-after", type=int, default=5)
    args = ap.parse_args(argv)
    if args.restore:
        print(f"已還原 {restore(args.out)} 筆")
        tidy_index()
        return 0
    if args.connection is None:
        ap.error("--connection is required")
    s = asyncio.run(run(args.connection, args.out, args.limit, args.concurrency, args.stop_after, args.only_ids))
    tidy_index()
    print(f"結束：要處理 {s['todo']} 筆，完成 {s['done']}，失敗 {s['failed']}；"
          f"有出處 {s['sourced']} / {s['points']} 條；等待中被改寫而跳過 {s['changed']} 筆"
          + ("；連續失敗太多次，已停止" if s["stopped"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
