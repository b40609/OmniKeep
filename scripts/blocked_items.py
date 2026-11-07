"""List saved items whose stored content is only a site's error or anti-bot page; optionally fix them.

The fetch of X, a Cloudflare-protected site or a removed page can come back as "enable JavaScript",
"verifying you are human" or "404". Before app/parsers/blocked.py those pages were analysed as if
they were the article, and the AI wrote a confident analysis that was all made up. This finds them
with the same check the pipeline now uses.

  python scripts/blocked_items.py --db omnikeep.db                                  # list (read-only)
  python scripts/blocked_items.py --db omnikeep.db --report backups/blocked/list.md # list to a file too
  python scripts/blocked_items.py --db omnikeep.db --reasons js_required,bot_check --mark --out backups/blocked-1
  python scripts/blocked_items.py --db omnikeep.db --ids 4fb95102d71a --refetch --out backups/blocked-1
  python scripts/blocked_items.py --db omnikeep.db --restore --out backups/blocked-1

Listing opens the database read-only. --mark and --refetch first append each item's current
fields to <out>/before.jsonl (flushed to disk before the item is changed); --restore writes back
the first copy kept for each item.
  --mark     keeps the item but replaces the made-up analysis: title from the URL, summary
             "（擷取失敗）…", the deep analysis says why, tags emptied. No AI call.
  --refetch  fetches the page again and runs the normal pipeline on it (with the error-page check,
             so a page that is still blocked ends up marked as above). Follow-ups (tool resolution,
             sub-project fan-out, alternatives) are skipped; restore does not undo a new vector or
             snapshot, so rebuild vectors afterwards (scripts/rebuild_embeddings.py --reembed --all).
Do not run --mark / --refetch while another job is rewriting deep_analysis (e.g. the source
annotation run): the two would overwrite each other.
"""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.parsers.blocked import REASONS, detect_blocked_page, reason_text  # noqa: E402

# Content that is not text scraped from a page (made by OmniKeep, typed by the user, or a video).
SKIP_SOURCES = ("proposal", "watch", "insight", "snippet", "youtube", "reel", "bilibili")
FIELDS = ("id", "url", "source_type", "category_name", "title_l1", "summary_l1", "tech_tags",
          "deep_analysis", "content_raw", "cover_image", "updated_at")
RESTORE_FIELDS = ("category_name", "title_l1", "summary_l1", "tech_tags", "deep_analysis", "content_raw",
                  "cover_image")


def _marked(item: Dict[str, Any]) -> bool:
    from app.pipeline import FETCH_FAILED_TAG
    return (item.get("summary_l1") or "").startswith(FETCH_FAILED_TAG)


def scan(db_path: str, reasons: Optional[Iterable[str]] = None, ids: Optional[Iterable[str]] = None,
         include_marked: bool = False) -> List[Dict[str, Any]]:
    """Blocked items, newest first, each with its "reason". Opens the database read-only."""
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    marks = ",".join("?" * len(SKIP_SOURCES))
    with closing(sqlite3.connect(uri, uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            f"SELECT * FROM items WHERE source_type NOT IN ({marks}) "
            "AND COALESCE(analysis_status, 'done') != 'pending' ORDER BY created_at DESC",
            SKIP_SOURCES).fetchall()
    wanted_reasons = set(reasons) if reasons else None
    wanted_ids = set(ids) if ids else None
    found = []
    for row in rows:
        item = dict(row)
        if wanted_ids is not None and item["id"] not in wanted_ids:
            continue
        reason = detect_blocked_page(item.get("content_raw") or "")
        if not reason or (wanted_reasons is not None and reason not in wanted_reasons):
            continue
        if _marked(item) and not include_marked:
            continue
        item["reason"] = reason
        found.append(item)
    return found


def report_markdown(items: List[Dict[str, Any]]) -> str:
    counts: Dict[str, int] = {}
    for item in items:
        counts[item["reason"]] = counts.get(item["reason"], 0) + 1
    lines = ["# 內容只是錯誤頁或擋爬頁的收藏", "",
             f"共 {len(items)} 筆。" + "、".join(f"{key}（{REASONS[key]}）{n} 筆" for key, n in counts.items()), "",
             "| id | 原因 | 來源 | 內文長度 | 分析長度 | 目前標題 | 網址 |", "|---|---|---|---|---|---|---|"]
    for item in items:
        title = (item.get("title_l1") or "").replace("|", "／")
        lines.append(f"| {item['id']} | {item['reason']} | {item.get('source_type') or ''} | "
                     f"{len(item.get('content_raw') or '')} | {len(item.get('deep_analysis') or '')} | "
                     f"{title} | {item.get('url') or ''} |")
    return "\n".join(lines) + "\n"


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _keep_copy(out: Path, item: Dict[str, Any], action: str) -> None:
    """Append the item's current fields to before.jsonl and make sure they are on disk."""
    from datetime import datetime, timezone
    out.mkdir(parents=True, exist_ok=True)
    row = {k: item.get(k) for k in FIELDS}
    if isinstance(row["tech_tags"], list):  # get_item_by_id parses it; keep it as stored
        row["tech_tags"] = json.dumps(row["tech_tags"], ensure_ascii=False)
    row.update(action=action, saved_at=datetime.now(timezone.utc).isoformat())
    with (out / "before.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
        f.flush()
        os.fsync(f.fileno())


def _current(item_id: str) -> Optional[Dict[str, Any]]:
    """The item as stored right now (another job may have changed it since the scan)."""
    from app.database import get_item_by_id
    return get_item_by_id(item_id)


def mark(out: Path, items: List[Dict[str, Any]]) -> int:
    from app.database import update_item_field
    from app.pipeline import fetch_failed_fields
    changed = 0
    for found in items:
        item = _current(found["id"])
        if not item or _marked(item):
            continue
        reason = detect_blocked_page(item.get("content_raw") or "")
        if not reason:
            continue
        _keep_copy(out, item, "mark")
        fields = fetch_failed_fields(item["url"], reason_text(reason))
        fields["tech_tags"] = json.dumps(fields["tech_tags"], ensure_ascii=False)
        update_item_field(item["id"], fields)
        changed += 1
    return changed


async def refetch(out: Path, items: List[Dict[str, Any]]) -> Dict[str, int]:
    from app.pipeline import run_pipeline
    stats = {"fixed": 0, "still_blocked": 0, "failed": 0}
    for found in items:
        item = _current(found["id"])
        if not item:
            continue
        _keep_copy(out, item, "refetch")
        try:
            # is_sub_task: no tool resolution, fan-out or alternatives, so restore leaves nothing behind.
            await run_pipeline(item["url"], is_sub_task=True, origin=item.get("origin") or "manual")
        except Exception as exc:
            stats["failed"] += 1
            print(f"  {item['id']} 失敗：{type(exc).__name__}: {str(exc)[:200]}", flush=True)
            continue
        after = _current(item["id"]) or {}
        if detect_blocked_page(after.get("content_raw") or ""):
            stats["still_blocked"] += 1
            print(f"  {item['id']} 還是錯誤頁，已標成擷取失敗", flush=True)
        else:
            stats["fixed"] += 1
            print(f"  {item['id']} 已重新擷取並分析：{after.get('title_l1')}", flush=True)
    return stats


def restore(out: Path) -> int:
    from app.database import update_item_field
    seen = set()
    for row in read_jsonl(out / "before.jsonl"):
        if row["id"] in seen:
            continue  # the first copy is the one from before any change
        seen.add(row["id"])
        update_item_field(row["id"], {k: row[k] for k in RESTORE_FIELDS if k in row and row[k] is not None})
    return len(seen)


def main(argv: Optional[List[str]] = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=settings.DATABASE_PATH, help="OmniKeep database (default: DATABASE_PATH)")
    ap.add_argument("--reasons", help="comma-separated: " + ", ".join(REASONS))
    ap.add_argument("--ids", help="comma-separated item ids")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--report", type=Path, help="also write the list as Markdown here")
    ap.add_argument("--include-marked", action="store_true", help="list items already marked too")
    action = ap.add_mutually_exclusive_group()
    action.add_argument("--mark", action="store_true")
    action.add_argument("--refetch", action="store_true")
    action.add_argument("--restore", action="store_true")
    ap.add_argument("--out", type=Path, help="folder for before.jsonl (needed by --mark/--refetch/--restore)")
    args = ap.parse_args(argv)

    if not Path(args.db).exists():
        ap.error(f"找不到資料庫 {args.db}（用 --db 指定）")
    if (args.mark or args.refetch or args.restore) and not args.out:
        ap.error("--mark / --refetch / --restore 需要 --out")
    settings.DATABASE_PATH = str(Path(args.db).resolve())  # writes go to the database that was listed

    if args.restore:
        print(f"已還原 {restore(args.out)} 筆")
        return 0

    reasons = [r.strip() for r in args.reasons.split(",") if r.strip()] if args.reasons else None
    unknown = set(reasons or ()) - set(REASONS)
    if unknown:
        ap.error(f"不認得的原因：{', '.join(sorted(unknown))}")
    ids = [i.strip() for i in args.ids.split(",") if i.strip()] if args.ids else None
    items = scan(args.db, reasons, ids, include_marked=args.include_marked)
    if args.limit is not None:
        items = items[:args.limit]

    text = report_markdown(items)
    print(text)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(text, encoding="utf-8")
        print(f"清單另存到 {args.report}")
    if args.mark:
        print(f"已標成擷取失敗 {mark(args.out, items)} 筆；原值在 {args.out / 'before.jsonl'}")
    elif args.refetch:
        stats = asyncio.run(refetch(args.out, items))
        print(f"重新擷取：成功 {stats['fixed']}，還是錯誤頁 {stats['still_blocked']}，失敗 {stats['failed']}；"
              f"原值在 {args.out / 'before.jsonl'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
