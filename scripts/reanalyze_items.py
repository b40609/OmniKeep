"""Re-analyse stored items with one AI connection (e.g. a Vertex connection paid by Google Cloud credit).

Each item's stored content_raw is analysed again; nothing is fetched again. Before anything is
changed, every item's current analysis is written to <out>/before.jsonl (the run refuses to start
without it), and each finished item is appended to <out>/done.jsonl, so a run can stop and resume.

  python scripts/reanalyze_items.py --connection 15 --out backups/reanalysis-1 --backup-only
  python scripts/reanalyze_items.py --connection 15 --out backups/reanalysis-1 --limit 20
  python scripts/reanalyze_items.py --connection 15 --out backups/reanalysis-1          # the rest
  python scripts/reanalyze_items.py --out backups/reanalysis-1 --restore                # undo

Only the named connection is used (no fallback chain), so the spend lands where it was meant to.
A failed or empty answer never overwrites an item; after --stop-after failures in a row the run
stops (a spending cap paused the service, a key stopped working). Title, summary, tags and the deep
analysis are replaced; category, starred/read state and the stored content stay as they are.
Vectors are built from title, summary and tags: rebuild them afterwards with
scripts/rebuild_embeddings.py --reembed --all.
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

from app import ai_connections  # noqa: E402
from app.database import get_all_categories, get_db_connection, optimize_fts, update_item_field  # noqa: E402
from app.pipeline import METADATA_ONLY_TAG, analysis_system_prompt, interest_profile_block  # noqa: E402
from app.providers import build_provider  # noqa: E402
from app.schemas.intelligence import sanitize_and_validate_analysis  # noqa: E402

SKIP_SOURCES = ("proposal", "watch", "insight")  # made by OmniKeep itself, not collected content
FIELDS = ("id", "url", "source_type", "category_name", "title_l1", "summary_l1", "tech_tags",
          "deep_analysis", "author", "updated_at")
KIND = {"reel": "短影音（含畫面文字辨識與語音轉錄）", "youtube": "YouTube 影片資訊", "bilibili": "Bilibili 影片",
        "threads": "Threads 貼文與討論串", "github": "GitHub 專案", "rss": "文章", "web": "網頁／文章",
        "snippet": "使用者的筆記片段"}


def candidates(min_chars: int = 50) -> List[Dict[str, Any]]:
    marks = ",".join("?" * len(SKIP_SOURCES))
    with closing(get_db_connection()) as db:
        rows = db.execute(
            f"SELECT * FROM items WHERE source_type NOT IN ({marks}) "
            "AND COALESCE(analysis_status, 'done') != 'pending' AND length(COALESCE(content_raw, '')) >= ? "
            "ORDER BY created_at DESC", (*SKIP_SOURCES, min_chars)).fetchall()
    return [dict(r) for r in rows]


def write_backup(out: Path, items: List[Dict[str, Any]]) -> Path:
    path = out / "before.jsonl"
    if path.exists():
        return path  # never overwrite the first copy: it is the one taken before any change
    out.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps({k: item.get(k) for k in FIELDS}, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return path


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def build_prompt(item: Dict[str, Any], categories: str) -> str:
    kind = KIND.get(item.get("source_type") or "", "內容")
    prompt = f"""請深度分析以下{kind}：
網址：{item.get('url') or ''}
原始標題：{item.get('title_l1') or ''}
作者／發布者：{item.get('author') or ''}

候選分類清單：[{categories}]

=== 內容節錄 ===
{(item.get('content_raw') or '')[:15000]}
=== 內容結束 ===

請依據規範輸出結構化 JSON。若內容提及多個開源專案或工具，請將 is_composite 設為 true 並於 sub_entities 列出。"""
    return prompt + interest_profile_block()


async def analyse(provider, prompt: str, system_prompt: str, retries: int = 1) -> Dict[str, Any]:
    """A validated analysis, or an exception: an empty answer counts as a failure."""
    last: Optional[BaseException] = None
    for _ in range(retries + 1):
        try:
            result = sanitize_and_validate_analysis(await provider.generate_json(prompt, system_prompt)).model_dump()
        except Exception as exc:  # provider errors and invalid JSON alike
            last = exc
            continue
        if (result.get("summary_l1") or "").strip() and (result.get("deep_analysis") or "").strip():
            return result
        last = ValueError("empty analysis")
    raise last or ValueError("no answer")


def updates_for(item: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    summary = result["summary_l1"].strip()
    deep = result["deep_analysis"].strip()
    old_summary = item.get("summary_l1") or ""
    if old_summary.startswith(METADATA_ONLY_TAG):
        # The content is still only the title and description: keep saying so.
        summary = METADATA_ONLY_TAG + summary
        note = (item.get("deep_analysis") or "").split("\n", 1)[0]
        if note.startswith(">"):
            deep = f"{note}\n\n{deep}"
    tags = result.get("tech_tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    out = {"summary_l1": summary, "deep_analysis": deep, "tech_tags": json.dumps(tags, ensure_ascii=False)}
    if (result.get("title_l1") or "").strip():
        out["title_l1"] = result["title_l1"].strip()
    return out


async def run(connection_id: int, out: Path, limit: Optional[int], concurrency: int, stop_after: int) -> Dict[str, int]:
    conn = ai_connections.get_connection(connection_id)
    if conn is None:
        raise SystemExit(f"找不到連線 {connection_id}")
    if not (out / "before.jsonl").exists():
        raise SystemExit(f"{out / 'before.jsonl'} 不存在：先用 --backup-only 另存目前的分析")
    provider = build_provider(conn)
    system_prompt = analysis_system_prompt()
    categories = ", ".join(c["name"] for c in get_all_categories())
    done_ids = {row["id"] for row in read_jsonl(out / "done.jsonl")}
    # Only items in the backup: anything collected after it has no copy to restore.
    backed_up = {row["id"] for row in read_jsonl(out / "before.jsonl")}
    todo = [i for i in candidates() if i["id"] in backed_up and i["id"] not in done_ids]
    if limit is not None:
        todo = todo[:limit]
    stats = {"todo": len(todo), "done": 0, "failed": 0}
    in_a_row = 0
    stop = asyncio.Event()
    sem = asyncio.Semaphore(max(1, concurrency))
    log = (out / "done.jsonl").open("a", encoding="utf-8")
    fail_log = (out / "failed.jsonl").open("a", encoding="utf-8")

    async def one(item: Dict[str, Any]) -> None:
        nonlocal in_a_row
        async with sem:
            if stop.is_set():
                return
            started = time.monotonic()
            try:
                result = await analyse(provider, build_prompt(item, categories), system_prompt)
            except Exception as exc:
                stats["failed"] += 1
                in_a_row += 1
                fail_log.write(json.dumps({"id": item["id"], "error": f"{type(exc).__name__}: {exc}"[:300],
                                           "at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n")
                fail_log.flush()
                if in_a_row >= stop_after:
                    stop.set()
                return
            update_item_field(item["id"], updates_for(item, result))
            in_a_row = 0
            stats["done"] += 1
            log.write(json.dumps({"id": item["id"], "seconds": round(time.monotonic() - started, 1),
                                  "at": datetime.now(timezone.utc).isoformat()}) + "\n")
            log.flush()
            if stats["done"] % 10 == 0:
                print(f"已完成 {stats['done']} / {stats['todo']}，失敗 {stats['failed']}", flush=True)

    try:
        await asyncio.gather(*(one(i) for i in todo))
    finally:
        log.close()
        fail_log.close()
    stats["stopped"] = int(stop.is_set())
    return stats


def restore(out: Path) -> int:
    rows = read_jsonl(out / "before.jsonl")
    for row in rows:
        update_item_field(row["id"], {k: row[k] for k in ("title_l1", "summary_l1", "tech_tags", "deep_analysis")
                                      if k in row})
    return len(rows)


def tidy_index() -> None:
    """Rewriting many items leaves the full-text index in many pieces: merge them once at the end."""
    try:
        optimize_fts()
    except Exception as exc:
        print(f"全文索引整理失敗（{type(exc).__name__}: {exc}），不影響已寫入的結果")


def main(argv: Optional[List[str]] = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--connection", type=int, help="ai_connections id to analyse with")
    ap.add_argument("--out", type=Path, required=True, help="folder for before.jsonl / done.jsonl / failed.jsonl")
    ap.add_argument("--backup-only", action="store_true")
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--stop-after", type=int, default=5, help="stop after this many failures in a row")
    args = ap.parse_args(argv)
    if args.restore:
        print(f"已還原 {restore(args.out)} 筆")
        tidy_index()
        return 0
    if args.backup_only:
        items = candidates(min_chars=0)
        path = write_backup(args.out, items)
        print(f"已另存 {len(read_jsonl(path))} 筆目前的分析到 {path}")
        return 0
    if args.connection is None:
        ap.error("--connection is required")
    stats = asyncio.run(run(args.connection, args.out, args.limit, args.concurrency, args.stop_after))
    tidy_index()
    print(f"結束：要處理 {stats['todo']} 筆，完成 {stats['done']}，失敗 {stats['failed']}"
          + ("；連續失敗太多次，已停止" if stats["stopped"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
