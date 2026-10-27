"""Safe first-run setup, always exercised in isolated synthetic directories."""

from pathlib import Path

import pytest
from dotenv import dotenv_values

from scripts.bootstrap_env import bootstrap_env, main


def test_bootstrap_creates_strong_key_and_preserves_template(isolated_runtime, capsys):
    root = isolated_runtime / "new-checkout"
    root.mkdir()
    original = "HOST=0.0.0.0\nAPI_KEY=\nOPENAI_API_KEY=\nRADAR_ENABLED=false\n"
    (root / ".env.example").write_text(original, encoding="utf-8")

    created = bootstrap_env(root)
    values = dotenv_values(created)
    key = values["API_KEY"]
    assert len(key) >= 32
    assert len(set(key)) >= 12
    assert values["RADAR_ENABLED"] == "false"
    assert values["OPENAI_API_KEY"] == ""
    assert (root / ".env.example").read_text(encoding="utf-8") == original
    assert key not in capsys.readouterr().out


def test_bootstrap_never_overwrites_existing_env(isolated_runtime):
    root = isolated_runtime / "existing-checkout"
    root.mkdir()
    (root / ".env.example").write_text("API_KEY=\n", encoding="utf-8")
    existing = root / ".env"
    existing.write_text("API_KEY=original-synthetic-value\n", encoding="utf-8")

    with pytest.raises(FileExistsError):
        bootstrap_env(root)
    assert existing.read_text(encoding="utf-8") == "API_KEY=original-synthetic-value\n"


def test_bootstrap_rejects_ambiguous_template(isolated_runtime):
    root = isolated_runtime / "bad-checkout"
    root.mkdir()
    (root / ".env.example").write_text("API_KEY=\nAPI_KEY=\n", encoding="utf-8")
    with pytest.raises(ValueError, match="exactly one"):
        bootstrap_env(root)
    assert not (root / ".env").exists()
