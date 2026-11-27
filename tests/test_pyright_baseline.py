"""Regression tests for scripts/pyright_baseline.py (2026-11-26 review A-10, B-05).

Confirms the gate actually turns red when a new pyright error appears, stays green on the
recorded baseline, and reports fixed errors without failing.
"""
from collections import Counter
import json
import sys
from pathlib import Path

from scripts import pyright_baseline


def test_recorded_baseline_file_is_valid_json_counter():
    data = json.loads(pyright_baseline.BASELINE.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert sum(data.values()) > 0
    assert all(isinstance(k, str) and isinstance(v, int) and v > 0 for k, v in data.items())


def test_new_error_beyond_baseline_fails_with_exit_1(monkeypatch, tmp_path, capsys):
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(json.dumps({"app/a.py | reportGeneralTypeIssues | old err": 1}), encoding="utf-8")
    monkeypatch.setattr(pyright_baseline, "BASELINE", baseline_file)
    monkeypatch.setattr(
        pyright_baseline,
        "run_pyright",
        lambda: Counter({
            "app/a.py | reportGeneralTypeIssues | old err": 1,
            "app/new.py | reportArgumentType | brand new type error": 1,
        }),
    )
    monkeypatch.setattr(sys, "argv", ["pyright_baseline.py"])

    assert pyright_baseline.main() == 1
    out = capsys.readouterr().out
    assert "NEW (1): app/new.py | reportArgumentType | brand new type error" in out
    assert "FAIL: 1 new pyright error(s)" in out


def test_matching_or_fewer_errors_passes_with_exit_0(monkeypatch, tmp_path, capsys):
    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(
        json.dumps({
            "app/a.py | reportGeneralTypeIssues | old err": 2,
            "app/b.py | reportOptionalMemberAccess | fixed err": 1,
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(pyright_baseline, "BASELINE", baseline_file)
    monkeypatch.setattr(
        pyright_baseline,
        "run_pyright",
        lambda: Counter({"app/a.py | reportGeneralTypeIssues | old err": 2}),
    )
    monkeypatch.setattr(sys, "argv", ["pyright_baseline.py"])

    assert pyright_baseline.main() == 0
    out = capsys.readouterr().out
    assert "OK: no new pyright errors" in out
    assert "fixed since 1" in out


def test_key_normalizes_paths_without_line_numbers():
    diag = {
        "file": str(Path(pyright_baseline.REPO) / "app" / "foo.py"),
        "rule": "reportArgumentType",
        "message": "First line\n  Second detail line",
    }
    assert pyright_baseline._key(diag) == "app/foo.py | reportArgumentType | First line"
