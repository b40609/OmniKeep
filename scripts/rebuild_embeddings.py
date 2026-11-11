"""Check, repair or rebuild OmniKeep's semantic-search vectors.

  python scripts/rebuild_embeddings.py                          report only; changes nothing
  python scripts/rebuild_embeddings.py --repair --yes           relabel rows proven to be local vectors (no API calls)
  python scripts/rebuild_embeddings.py --reembed --yes          re-embed rows not made by the current model
  python scripts/rebuild_embeddings.py --reembed --include-missing --yes
                                                                also embed analysed items that have no vector
  python scripts/rebuild_embeddings.py --reembed --all --yes    re-embed every vector with the current model
  python scripts/rebuild_embeddings.py --prune-orphans --yes    remove the vectors of items that no longer exist

--all is for labels that cannot be trusted: only local hashed vectors can be proven
(recomputed), so a row made by OpenAI but labelled as the Ollama model looks current.
With the local Ollama runner it costs nothing; with a cloud endpoint it is one paid
call per item.

Uses the server's .env plus the settings saved in the app. Without --yes it only prints
what it would change. With --yes it first saves BACKUP_DIR/omnikeep-prerebuild-<stamp>.zip
(restore with scripts/restore_backup.py). OmniKeep may keep running meanwhile.
"""
import argparse
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.app_settings import apply_overrides  # noqa: E402
from app.backup import snapshot_archive  # noqa: E402
from app.config import settings  # noqa: E402
from app.reindex import (audit_embeddings, delete_orphan_vectors, orphan_vector_ids, reembed,  # noqa: E402
                         relabel_proven_local)
from app.vector import ollama_embedding_enabled  # noqa: E402


def _counts(counter) -> str:
    return ", ".join(f"{model} x{n}" for model, n in counter.most_common()) or "(none)"


def _source() -> str:
    if ollama_embedding_enabled():
        return f"local Ollama at {settings.OLLAMA_BASE_URL}"
    return "OPENAI_API_KEY set" if settings.OPENAI_API_KEY else "no OPENAI_API_KEY, so local vectors"


def _print_report(report) -> None:
    print(f"Database        {settings.DATABASE_PATH}")
    print(f"Queries use     {report['target_model']} ({_source()}), dim {report['dim']}")
    vec = f", vec_items {report['vec_rows']}" if report["vec_rows"] is not None else ""
    print(f"Index           {report['items']} items, {report['rows']} vectors{vec}")
    print(f"Labelled as     {_counts(report['labels'])}")
    print(f"Actually from   {_counts(report['actual'])}")
    print(f"- local vectors labelled as another model: {len(report['mislabeled_local'])} (--repair, no API calls)")
    dims = f", {len(report['dim_mismatch'])} of them with another dim" if report["dim_mismatch"] else ""
    print(f"- not from {report['target_model']}, so queries cannot match them: {len(report['stale'])}{dims} (--reembed)")
    print(f"- analysed items without a vector: {len(report['missing'])} (--reembed --include-missing)")
    print(f"- every vector of an existing item: {len(report['indexed'])} (--reembed --all)")
    print(f"- vectors of deleted items: {len(orphan_vector_ids())} (--prune-orphans, no API calls)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repair", action="store_true", help="relabel rows proven to be local vectors")
    parser.add_argument("--reembed", action="store_true", help="re-embed rows not made by the current model")
    parser.add_argument("--include-missing", action="store_true", help="with --reembed: also items without a vector")
    parser.add_argument("--all", action="store_true",
                        help="with --reembed: every existing vector, not only the provably stale ones")
    parser.add_argument("--prune-orphans", action="store_true",
                        help="remove the vectors of items that no longer exist")
    parser.add_argument("--yes", action="store_true", help="apply the changes (default: only show them)")
    args = parser.parse_args(argv)
    if args.all and not args.reembed:
        parser.error("--all only works together with --reembed")

    apply_overrides()  # keys and addresses saved in the app's settings page win over .env
    report = audit_embeddings()
    _print_report(report)
    relabel = report["mislabeled_local"] if args.repair else []
    embed = []
    if args.reembed:
        embed = list(report["indexed"] if args.all else report["stale"])
        if args.include_missing:
            embed += report["missing"]
    orphans = orphan_vector_ids() if args.prune_orphans else []
    if not (args.repair or args.reembed or args.prune_orphans):
        return 0
    if ollama_embedding_enabled():
        calls = "local Ollama, no API cost"
    elif settings.OPENAI_API_KEY:
        calls = f"{len(embed)} embedding API calls"
    else:
        calls = "local, no API calls"
    prune = f"; remove the vectors of {len(orphans)} deleted items" if args.prune_orphans else ""
    print(f"\nPlan: relabel {len(relabel)} rows; re-embed {len(embed)} items with {report['target_model']} "
          f"({calls}){prune}.")
    if not relabel and not embed and not orphans:
        print("Nothing to change.")
        return 0
    if not args.yes:
        print("Dry run: nothing changed. Add --yes to apply.")
        return 0

    archive = snapshot_archive("prerebuild")
    print(f"Saved {archive} first (restore it with scripts/restore_backup.py).")
    if relabel:
        print(f"Relabelled {relabel_proven_local(relabel)} rows as local vectors.")
    if orphans:
        print(f"Removed the vectors of {delete_orphan_vectors()} deleted items.")
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
