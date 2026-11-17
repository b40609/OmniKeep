"""Collect GitHub projects again so they get the system architecture diagram (```arch, app/arch_block.py).

scripts/reanalyze_items.py analyses the stored text only, which for an older GitHub item has no file
list and no numbered core-file excerpts, and it skips the diagram check (pipeline.settle_arch). This
runs the normal pipeline on the link instead, the same as collecting it again: the repository is
fetched again (file list, excerpts pinned to a commit), analysed, checked, and the item is rewritten
in place. Category, starred and read state stay; no sub-projects are spawned (is_sub_task).

Before anything is changed every candidate's current fields are written to <out>/before.jsonl (never
overwritten), each finished item goes to <out>/done.jsonl, so a run can stop and resume.

  python scripts/redo_github_arch.py --out backups/github-arch-1 --backup-only
  python scripts/redo_github_arch.py --out backups/github-arch-1 --limit 10
  python scripts/redo_github_arch.py --out backups/github-arch-1            # the rest
  python scripts/redo_github_arch.py --out backups/github-arch-1 --restore  # undo
"""
import argparse
import asyncio
import json
import sys
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import get_db_connection, get_item_by_id, update_item_field  # noqa: E402
from app.parsers.github_repo import repo_from_url  # noqa: E402

FIELDS = ("id", "url", "category_name", "title_l1", "summary_l1", "tech_tags", "deep_analysis",
          "content_raw", "analysis_status", "origin", "updated_at")
# analysis_status is not put back: every candidate is "done", and a rerun only saves a finished one.
RESTORED = ("title_l1", "summary_l1", "tech_tags", "deep_analysis", "content_raw", "category_name")


def candidates() -> List[Dict[str, Any]]:
    """GitHub repositories (not release or issue pages) without a diagram yet, newest first."""
    with closing(get_db_connection()) as db:
        rows = db.execute(
            "SELECT * FROM items WHERE url LIKE 'https://github.com/%' "
            "AND COALESCE(deep_analysis, '') NOT LIKE '%```arch%' "
            "AND COALESCE(analysis_status, 'done') = 'done' ORDER BY created_at DESC").fetchall()
    out = []
    for r in rows:
        item = dict(r)
        repo = repo_from_url(item["url"])
        if (item.get("summary_l1") or "").startswith("（擷取失敗）"):
            continue  # app/refetch.py retries those on its own
        if repo and item["url"].rstrip("/").lower().endswith("/".join(repo).lower()):
            out.append(item)
    return out


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_backup(out: Path, items: List[Dict[str, Any]]) -> Path:
    path = out / "before.jsonl"
    if path.exists():
        return path  # the first copy is the one taken before any change
    out.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps({k: item.get(k) for k in FIELDS}, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return path


async def run(out: Path, limit: Optional[int], stop_after: int) -> Dict[str, int]:
    from app import app_settings
    from app.pipeline import run_pipeline
    app_settings.apply_overrides()  # 設定頁存的值（例如 GitHub Token），伺服器啟動時才會載入
    if not (out / "before.jsonl").exists():
        raise SystemExit(f"{out / 'before.jsonl'} 不存在：先用 --backup-only 備份")
    done_ids = {row["id"] for row in read_jsonl(out / "done.jsonl")}
    backed_up = {row["id"] for row in read_jsonl(out / "before.jsonl")}
    todo = [i for i in candidates() if i["id"] in backed_up and i["id"] not in done_ids]
    if limit is not None:
        todo = todo[:limit]
    stats = {"todo": len(todo), "done": 0, "with_diagram": 0, "failed": 0}
    in_a_row = 0
    with (out / "done.jsonl").open("a", encoding="utf-8") as log, \
            (out / "failed.jsonl").open("a", encoding="utf-8") as fail_log:
        for item in todo:  # one at a time: each one fetches from GitHub and calls the AI
            started = time.monotonic()
            category = item.get("category_name")
            try:
                await run_pipeline(item["url"], manual_category=category if category and category != "Inbox" else None,
                                   is_sub_task=True, origin=item.get("origin") or "manual")
                after = get_item_by_id(item["id"]) or {}
                if (after.get("analysis_status") or "done") != "done" or not (after.get("deep_analysis") or "").strip():
                    raise RuntimeError("分析沒有完成")
            except Exception as exc:
                stats["failed"] += 1
                in_a_row += 1
                fail_log.write(json.dumps({"id": item["id"], "url": item["url"],
                                           "error": f"{type(exc).__name__}: {exc}"[:300],
                                           "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
                fail_log.flush()
                print(f"失敗 {item['url']}：{type(exc).__name__}: {exc}"[:200], flush=True)
                if in_a_row >= stop_after:
                    print(f"連續 {in_a_row} 篇失敗，停止", flush=True)
                    break
                continue
            in_a_row = 0
            has = "```arch" in (after.get("deep_analysis") or "")
            stats["done"] += 1
            stats["with_diagram"] += int(has)
            log.write(json.dumps({"id": item["id"], "url": item["url"], "arch": has,
                                  "seconds": round(time.monotonic() - started, 1),
                                  "at": datetime.now(timezone.utc).isoformat()}) + "\n")
            log.flush()
            print(f"[{stats['done'] + stats['failed']}/{stats['todo']}] {'有圖' if has else '無圖'} {item['url']}", flush=True)
    return stats


def restore(out: Path, only_done: bool) -> int:
    rows = read_jsonl(out / "before.jsonl")
    if only_done:
        done = {r["id"] for r in read_jsonl(out / "done.jsonl")}
        rows = [r for r in rows if r["id"] in done]
    for row in rows:
        update_item_field(row["id"], {k: row[k] for k in RESTORED if k in row and row[k] is not None})
    return len(rows)


def main(argv: Optional[List[str]] = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--backup-only", action="store_true")
    ap.add_argument("--restore", action="store_true", help="put back the fields saved in before.jsonl")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--stop-after", type=int, default=3, help="stop after this many failures in a row")
    args = ap.parse_args(argv)
    if args.restore:
        print(f"已還原 {restore(args.out, only_done=True)} 篇")
        return 0
    path = write_backup(args.out, candidates())
    print(f"備份：{path}（{len(read_jsonl(path))} 篇）")
    if args.backup_only:
        return 0
    print(json.dumps(asyncio.run(run(args.out, args.limit, args.stop_after)), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
