"""Check, repair or rebuild OmniKeep's semantic-search vectors.

  python scripts/rebuild_embeddings.py                          report only; changes nothing
  python scripts/rebuild_embeddings.py --repair --yes           relabel rows proven to be local vectors (no API calls)
  python scripts/rebuild_embeddings.py --reembed --yes          re-embed rows not made by the current model
  python scripts/rebuild_embeddings.py --reembed --include-missing --yes
                                                                also embed analysed items that have no vector

Uses the server's .env. Without --yes it only prints what it would change. With --yes it
first saves BACKUP_DIR/omnikeep-prerebuild-<stamp>.zip (restore with scripts/restore_backup.py).
OmniKeep may keep running meanwhile.
"""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.backup import snapshot_archive  # noqa: E402
from app.config import settings  # noqa: E402
from app.reindex import audit_embeddings, reembed, relabel_proven_local  # noqa: E402


def _counts(counter) -> str:
    return ", ".join(f"{model} x{n}" for model, n in counter.most_common()) or "(none)"


def _print_report(report) -> None:
    source = "OPENAI_API_KEY set" if settings.OPENAI_API_KEY else "no OPENAI_API_KEY, so local vectors"
    print(f"Database        {settings.DATABASE_PATH}")
    print(f"Queries use     {report['target_model']} ({source}), dim {report['dim']}")
    vec = f", vec_items {report['vec_rows']}" if report["vec_rows"] is not None else ""
    print(f"Index           {report['items']} items, {report['rows']} vectors{vec}")
    print(f"Labelled as     {_counts(report['labels'])}")
    print(f"Actually from   {_counts(report['actual'])}")
    print(f"- local vectors labelled as another model: {len(report['mislabeled_local'])} (--repair, no API calls)")
    dims = f", {len(report['dim_mismatch'])} of them with another dim" if report["dim_mismatch"] else ""
    print(f"- not from {report['target_model']}, so queries cannot match them: {len(report['stale'])}{dims} (--reembed)")
    print(f"- analysed items without a vector: {len(report['missing'])} (--reembed --include-missing)")
    print(f"- vectors of deleted items: {len(report['orphans'])} (harmless, left alone)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repair", action="store_true", help="relabel rows proven to be local vectors")
    parser.add_argument("--reembed", action="store_true", help="re-embed rows not made by the current model")
    parser.add_argument("--include-missing", action="store_true", help="with --reembed: also items without a vector")
    parser.add_argument("--yes", action="store_true", help="apply the changes (default: only show them)")
    args = parser.parse_args(argv)

    report = audit_embeddings()
    _print_report(report)
    relabel = report["mislabeled_local"] if args.repair else []
    embed = report["stale"] + (report["missing"] if args.include_missing else []) if args.reembed else []
    if not (args.repair or args.reembed):
        return 0
    calls = f"{len(embed)} embedding API calls" if settings.OPENAI_API_KEY else "local, no API calls"
    print(f"\nPlan: relabel {len(relabel)} rows; re-embed {len(embed)} items with {report['target_model']} ({calls}).")
    if not relabel and not embed:
        print("Nothing to change.")
        return 0
    if not args.yes:
        print("Dry run: nothing changed. Add --yes to apply.")
        return 0

    archive = snapshot_archive("prerebuild")
    print(f"Saved {archive} first (restore it with scripts/restore_backup.py).")
    if relabel:
        print(f"Relabelled {relabel_proven_local(relabel)} rows as local vectors.")
    stopped = None
    if embed:
        def progress(done, total):
            if done % 25 == 0 or done == total:
                print(f"  re-embedded {done}/{total}")
        result = asyncio.run(reembed(embed, progress=progress))
        stopped = result["stopped"]
        print(f"Re-embedded {result['reembedded']} items; {result['fell_back']} fell back and were left unchanged.")
        if stopped:
            print(f"Stopped early: {stopped}")

    after = audit_embeddings()
    print(f"\nNow: {len(after['mislabeled_local'])} mislabelled, {len(after['stale'])} not from "
          f"{after['target_model']}, {len(after['missing'])} without a vector.")
    return 1 if stopped else 0


if __name__ == "__main__":
    raise SystemExit(main())
