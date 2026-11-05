"""scripts/register_agents.py：只寫暫存家目錄，不碰真正的 ~/.claude、~/.codex、~/.gemini。"""

import importlib.util
import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("register_agents", ROOT / "scripts" / "register_agents.py")
register_agents = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = register_agents  # dataclasses look the module up while building Context
_spec.loader.exec_module(register_agents)

PYTHON = str(ROOT / ".venv" / "python.exe")


@pytest.fixture
def home(isolated_runtime):
    # tests/.tmp per-case folder from conftest; pytest's own tmp_path is not writable on every machine.
    path = isolated_runtime / "home"
    path.mkdir()
    return path


def _ctx(home: Path, **kwargs) -> "register_agents.Context":
    kwargs.setdefault("use_cli", False)
    return register_agents.Context(project_dir=ROOT, python=PYTHON, home=home, **kwargs)


def _all(ctx):
    return register_agents.register(ctx, list(register_agents.AGENTS))


def test_dry_run_writes_nothing(home):
    results = _all(_ctx(home, dry_run=True))
    assert list(home.iterdir()) == []
    assert len(results) == 6
    assert all("會" in message for _, _, message in results)


def test_registers_mcp_and_skills_in_fresh_home(home):
    _all(_ctx(home))
    server = str(ROOT / "mcp_server.py")

    claude = json.loads((home / ".claude.json").read_text(encoding="utf-8"))
    assert claude["mcpServers"]["omnikeep"] == {"type": "stdio", "command": PYTHON, "args": [server], "env": {}}

    codex = tomllib.loads((home / ".codex" / "config.toml").read_text(encoding="utf-8"))
    assert codex["mcp_servers"]["omnikeep"] == {"command": PYTHON, "args": [server]}

    raw = (home / ".gemini" / "config" / "mcp_config.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert json.loads(raw)["mcpServers"]["omnikeep"] == {"command": PYTHON, "args": [server]}

    source = (ROOT / "skills" / "omnikeep-setup" / "SKILL.md").read_bytes()
    for parts in ((".claude", "skills"), (".agents", "skills"), (".gemini", "config", "skills")):
        assert home.joinpath(*parts, "omnikeep-setup", "SKILL.md").read_bytes() == source


def test_second_run_is_idempotent(home):
    _all(_ctx(home))
    before = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    results = _all(_ctx(home))
    after = {p: p.read_bytes() for p in home.rglob("*") if p.is_file()}
    assert before == after
    assert all("已註冊" in m or "已是最新" in m for _, _, m in results)


def test_keeps_other_servers_and_foreign_omnikeep_entry(home):
    config = home / ".gemini" / "config" / "mcp_config.json"
    config.parent.mkdir(parents=True)
    foreign = {"serverUrl": "http://example.invalid/mcp"}
    config.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}, "omnikeep": foreign}}),
                      encoding="utf-8-sig")
    ctx = _ctx(home)
    register_agents.register_antigravity_mcp(ctx)
    data = json.loads(config.read_text(encoding="utf-8-sig"))
    assert data["mcpServers"]["omnikeep"] == foreign
    assert "沒有覆蓋" in ctx.results[-1][2]

    forced = _ctx(home, force=True)
    register_agents.register_antigravity_mcp(forced)
    data = json.loads(config.read_text(encoding="utf-8"))
    assert data["mcpServers"]["other"] == {"command": "x"}
    assert data["mcpServers"]["omnikeep"]["args"] == [str(ROOT / "mcp_server.py")]
    assert (config.with_name("mcp_config.json.bak")).is_file()


def test_codex_appends_without_touching_existing_tables(home):
    config = home / ".codex" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "x"\n[mcp_servers.other]\ncommand = "y"', encoding="utf-8")
    register_agents.register_codex_mcp(_ctx(home))
    data = tomllib.loads(config.read_text(encoding="utf-8"))
    assert data["model"] == "x"
    assert data["mcp_servers"]["other"] == {"command": "y"}
    assert data["mcp_servers"]["omnikeep"]["command"] == PYTHON


def test_user_edited_skill_is_not_overwritten(home):
    register_agents.install_skill(_ctx(home), "claude")
    skill = home / ".claude" / "skills" / "omnikeep-setup" / "SKILL.md"
    skill.write_text("my own notes", encoding="utf-8")

    ctx = _ctx(home)
    register_agents.install_skill(ctx, "claude")
    assert skill.read_text(encoding="utf-8") == "my own notes"
    assert "沒有覆蓋" in ctx.results[-1][2]

    register_agents.install_skill(_ctx(home, force=True), "claude")
    assert skill.read_bytes() == (ROOT / "skills" / "omnikeep-setup" / "SKILL.md").read_bytes()
    assert (skill.parent.with_name("omnikeep-setup.bak") / "SKILL.md").read_text(encoding="utf-8") == "my own notes"


def test_cli_mode_uses_official_commands(home):
    calls = []

    def fake_run(command):
        calls.append(command)
        returncode = 1 if command[1:3] == ["mcp", "get"] else 0
        return subprocess.CompletedProcess(command, returncode, "", "")

    ctx = _ctx(home, use_cli=True, which=lambda name: f"/bin/{name}", run=fake_run)
    register_agents.register_claude_mcp(ctx)
    register_agents.register_codex_mcp(ctx)
    server = str(ROOT / "mcp_server.py")
    assert calls == [
        ["/bin/claude", "mcp", "get", "omnikeep"],
        ["/bin/claude", "mcp", "add", "-s", "user", "omnikeep", "--", PYTHON, server],
        ["/bin/codex", "mcp", "add", "omnikeep", "--", PYTHON, server],
    ]
    assert list(home.iterdir()) == []


def test_cli_dry_run_only_probes(home):
    calls = []

    def fake_run(command):
        calls.append(command)
        return subprocess.CompletedProcess(command, 1, "", "")

    ctx = _ctx(home, use_cli=True, dry_run=True, which=lambda name: f"/bin/{name}", run=fake_run)
    register_agents.register_claude_mcp(ctx)
    register_agents.register_codex_mcp(ctx)
    assert calls == [["/bin/claude", "mcp", "get", "omnikeep"]]


def test_main_rejects_unknown_agent(home, capsys):
    assert register_agents.main(["--home", str(home), "--agents", "cursor", "--dry-run"]) == 2


@pytest.mark.parametrize("name", ["plugin.json", "marketplace.json"])
def test_plugin_manifests_are_valid(name):
    data = json.loads((ROOT / ".claude-plugin" / name).read_text(encoding="utf-8"))
    assert data["name"] == "omnikeep"
    if name == "marketplace.json":
        assert data["owner"]["name"]
        assert data["plugins"][0]["source"] == "./"
        assert data["plugins"][0]["name"] == "omnikeep"


def test_install_ps1_has_bom_for_windows_powershell():
    # Windows PowerShell 5.1 reads BOM-less scripts as the ANSI code page and garbles Chinese text.
    assert (ROOT / "scripts" / "install.ps1").read_bytes().startswith(b"\xef\xbb\xbf")
