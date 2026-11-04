"""The Docker image must hold every file the app reads at run time. No Docker needed:
the Dockerfile's WORKDIR/COPY lines are replayed against the repo."""
import shlex
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]


def _stages():
    """For each build stage: its final WORKDIR and (repo source, container destination, is_dir) per COPY."""
    stages = []
    for raw in (REPO / "Dockerfile").read_text(encoding="utf-8").splitlines():
        if raw.split(" ", 1)[0] not in ("FROM", "WORKDIR", "COPY"):
            continue  # also skips continuation lines of ENV/RUN
        words = shlex.split(raw, comments=True)
        if words[0] == "FROM":
            stages.append({"workdir": PurePosixPath("/"), "copies": []})
        elif words[0] == "WORKDIR":
            stages[-1]["workdir"] = stages[-1]["workdir"] / words[1]
        elif words[0] == "COPY" and not any(w.startswith("--from") for w in words):
            *sources, dest = words[1:]
            target = stages[-1]["workdir"] / dest
            for pattern in sources:
                for src in sorted(REPO.glob(pattern.rstrip("/"))):
                    if src.is_dir():
                        stages[-1]["copies"].append((src, target, True))
                    else:
                        into_dir = dest.endswith("/") or dest in (".", "./") or len(sources) > 1
                        stages[-1]["copies"].append((src, target / src.name if into_dir else target, False))
    return stages


def _holds(stage, container_path):
    path = PurePosixPath(container_path)
    for src, dest, is_dir in stage["copies"]:
        if not is_dir and path == dest:
            return True
        if is_dir and path.is_relative_to(dest) and (src / path.relative_to(dest)).exists():
            return True
    return False


def test_frontend_stage_has_the_version_file_vite_reads():
    builder = _stages()[0]
    assert _holds(builder, "/build/frontend/vite.config.ts")
    assert "'../VERSION'" in (REPO / "frontend/vite.config.ts").read_text(encoding="utf-8")
    assert _holds(builder, "/build/VERSION")


def test_runtime_stage_imports_the_app_and_reports_the_version(isolated_runtime):
    runtime = _stages()[-1]
    assert runtime["workdir"] == PurePosixPath("/app")
    image = isolated_runtime / "image"
    for src, dest, is_dir in runtime["copies"]:
        if src.name in ("static", "requirements.txt"):
            continue  # not needed to import the app; static/dist is a build output
        target = image / dest.relative_to("/app")
        if is_dir:
            shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    res = subprocess.run([sys.executable, "-c", "import app; print(app.__version__)"], cwd=image,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    assert res.stdout.strip() == (REPO / "VERSION").read_text(encoding="utf-8").strip()
