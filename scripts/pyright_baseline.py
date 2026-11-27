"""pyright with a baseline: the existing errors are recorded, only new ones fail (2026-11-26 review A-10, B-05).

`pyright app` had 212 errors when the gate was introduced, so "0 errors" could not be enforced
and the check ran nowhere. The baseline (scripts/pyright_baseline.json) counts errors per file,
rule and message — no line numbers, so editing a file does not move its old errors into "new".

  python scripts/pyright_baseline.py            # check: exit 1 if any (file, rule, message) count grew
  python scripts/pyright_baseline.py --update   # rewrite the baseline (only after fixing errors)
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BASELINE = REPO / "scripts" / "pyright_baseline.json"
TARGETS = ["app"]
# Whether an optional package (faster-whisper, playwright, OCR) is installed differs between this
# machine and CI; deptry (tests/test_optional_dependencies.py) already checks that imports are declared.
ENVIRONMENT_RULES = {"reportMissingImports", "reportMissingModuleSource"}


def _key(diag: dict) -> str:
    file = Path(diag["file"]).resolve()
    try:
        rel = file.relative_to(REPO).as_posix()
    except ValueError:
        rel = file.as_posix()
    message = diag.get("message", "").splitlines()[0].strip()
    return f"{rel} | {diag.get('rule', '-')} | {message}"


def run_pyright() -> Counter:
    exe = shutil.which("pyright")
    cmd = [exe] if exe else [sys.executable, "-m", "pyright"]
    result = subprocess.run([*cmd, "--outputjson", *TARGETS], cwd=REPO, capture_output=True,
                            text=True, encoding="utf-8")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        sys.stderr.write(result.stdout[-2000:] + result.stderr[-2000:])
        raise SystemExit("pyright did not produce JSON output") from None
    print(f"pyright {data.get('version')}: {data['summary']['errorCount']} errors in "
          f"{data['summary']['filesAnalyzed']} files")
    return Counter(_key(d) for d in data["generalDiagnostics"]
                   if d.get("severity") == "error" and d.get("rule") not in ENVIRONMENT_RULES)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    current = run_pyright()
    if args.update:
        BASELINE.write_text(json.dumps(dict(sorted(current.items())), ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
        print(f"baseline written: {sum(current.values())} errors, {len(current)} keys")
        return 0
    baseline = Counter(json.loads(BASELINE.read_text(encoding="utf-8")))
    new = {k: current[k] - baseline.get(k, 0) for k in current if current[k] > baseline.get(k, 0)}
    fixed = sum(max(0, baseline[k] - current.get(k, 0)) for k in baseline)
    for key, extra in sorted(new.items()):
        print(f"NEW ({extra}): {key}")
    if new:
        print(f"FAIL: {sum(new.values())} new pyright error(s) beyond the baseline")
        return 1
    print(f"OK: no new pyright errors (baseline {sum(baseline.values())}, fixed since {fixed}"
          f"{'; run --update to lock the fixes in' if fixed else ''})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
