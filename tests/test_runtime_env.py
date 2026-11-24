"""Tests for persistent temp-directory sanitization on service startup."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from app.runtime_env import ensure_stable_tempdir


def test_replaces_missing_temp_directory(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "deleted_run_dir"
    persistent = tmp_path / "persistent_temp"
    persistent.mkdir()

    monkeypatch.setenv("TEMP", str(missing))
    monkeypatch.setenv("TMP", str(missing))
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", str(missing))
    monkeypatch.setattr("app.runtime_env._resolve_persistent_temp_dir", lambda: str(persistent))

    active = ensure_stable_tempdir()

    assert Path(active) == persistent
    assert Path(os.environ["TEMP"]) == persistent
    assert Path(os.environ["TMP"]) == persistent
    assert Path(tempfile.gettempdir()) == persistent

    created = tempfile.mkdtemp(prefix="omni_reel_")
    try:
        assert Path(created).parent == persistent
        assert Path(created).is_dir()
    finally:
        shutil.rmtree(created, ignore_errors=True)


def test_replaces_existing_ephemeral_antigravity_temp(monkeypatch, tmp_path: Path) -> None:
    ephemeral = tmp_path / ".t3" / "userdata" / "antigravity-tmp" / "fda30731acda" / "run-LovG9f"
    ephemeral.mkdir(parents=True)
    persistent = tmp_path / "persistent_temp"
    persistent.mkdir()

    monkeypatch.setenv("TEMP", str(ephemeral))
    monkeypatch.setenv("TMP", str(ephemeral))
    monkeypatch.setenv("TMPDIR", str(ephemeral))
    monkeypatch.setattr(tempfile, "tempdir", str(ephemeral))
    monkeypatch.setattr("app.runtime_env._resolve_persistent_temp_dir", lambda: str(persistent))

    active = ensure_stable_tempdir()

    assert Path(active) == persistent
    assert Path(os.environ["TEMP"]) == persistent
    assert Path(os.environ["TMP"]) == persistent
    assert Path(os.environ["TMPDIR"]) == persistent


def test_preserves_valid_non_ephemeral_temp(monkeypatch, tmp_path: Path) -> None:
    normal = tmp_path / "normal_temp"
    normal.mkdir()

    # Isolate from the outer test runner's own TEMP (e.g. if pytest itself runs
    # inside an antigravity-tmp sandbox, tmp_path would contain that marker).
    monkeypatch.setattr("app.runtime_env._EPHEMERAL_TEMP_MARKERS", ("synthetic-ephemeral-tmp",))
    monkeypatch.setenv("TEMP", str(normal))
    monkeypatch.setenv("TMP", str(normal))
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setattr(tempfile, "tempdir", None)

    active = ensure_stable_tempdir()

    assert Path(active) == normal
    assert Path(os.environ["TEMP"]) == normal
    assert Path(os.environ["TMP"]) == normal
