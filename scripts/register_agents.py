"""把 OmniKeep 的 stdio MCP 與 omnikeep-setup Skill 註冊到這台電腦的 Claude Code、Codex、Antigravity。

- MCP 一律用 stdio：agent 自己啟動 `<python> <OmniKeep>/mcp_server.py`。存取金鑰由 OmniKeep 自己讀，
  agent 的設定檔裡不放任何金鑰。
- Claude Code：`claude mcp add -s user`；Codex：`codex mcp add`；
  Antigravity：寫 `~/.gemini/config/mcp_config.json`（官方的全域位置，App、CLI、IDE 都讀）。
  沒有 CLI、或用 `--home` 指定別的家目錄時，改成直接寫設定檔（`~/.claude.json`、`~/.codex/config.toml`）。
- Skill 複製到：`~/.claude/skills`、`~/.agents/skills`（Codex）、`~/.gemini/config/skills`（Antigravity）。
- 已經有別的 `omnikeep` 設定、或 Skill 被使用者改過：不覆蓋，除非加 `--force`（改之前會留 `.bak`）。

用法：
    python scripts/register_agents.py --dry-run     # 只列出會做的事
    python scripts/register_agents.py               # 偵測到的 agent 全部註冊
    python scripts/register_agents.py --agents codex,antigravity --skip-skills
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

SERVER_NAME = "omnikeep"
SKILL_NAME = "omnikeep-setup"
INSTALL_MARKER = ".omnikeep-installed.json"
AGENTS = ("claude", "codex", "antigravity")
AGENT_LABELS = {"claude": "Claude Code", "codex": "Codex", "antigravity": "Antigravity"}

Runner = Callable[[list[str]], subprocess.CompletedProcess]


def _default_runner(command: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=120)


@dataclass
class Context:
    project_dir: Path
    python: str
    home: Path
    dry_run: bool = False
    force: bool = False
    use_cli: bool = True
    which: Callable[[str], str | None] = shutil.which
    run: Runner = _default_runner
    results: list[tuple[str, str, str]] = field(default_factory=list)

    @property
    def server_script(self) -> str:
        return str(self.project_dir / "mcp_server.py")

    @property
    def skill_source(self) -> Path:
        return self.project_dir / "skills" / SKILL_NAME

    def report(self, agent: str, item: str, message: str) -> None:
        self.results.append((AGENT_LABELS.get(agent, agent), item, message))
        prefix = "[dry-run] " if self.dry_run else ""
        print(f"  {AGENT_LABELS.get(agent, agent)} {item}：{prefix}{message}")

    def cli(self, name: str) -> str | None:
        return self.which(name) if self.use_cli else None


def default_python(project_dir: Path) -> str:
    venv = project_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return str(venv) if venv.is_file() else sys.executable


def detect_agents(ctx: Context) -> list[str]:
    found = []
    if ctx.which("claude") or (ctx.home / ".claude").is_dir():
        found.append("claude")
    if ctx.which("codex") or (ctx.home / ".codex").is_dir():
        found.append("codex")
    if ctx.which("agy") or ctx.which("antigravity") or (ctx.home / ".gemini").is_dir():
        found.append("antigravity")
    return found


def _same_path(a: str, b: str) -> bool:
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


def _entry_matches(command: object, args: object, ctx: Context) -> bool:
    if not isinstance(command, str) or not isinstance(args, list) or not args:
        return False
    return _same_path(command, ctx.python) and isinstance(args[-1], str) and _same_path(args[-1], ctx.server_script)


def _backup(path: Path) -> None:
    shutil.copy2(path, path.with_name(path.name + ".bak"))


def _read_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8-sig") or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} 的最外層不是 JSON 物件")
    return data


def _write_json(path: Path, data: dict) -> None:
    if path.is_file():
        _backup(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    # No BOM: Antigravity and Claude Code both expect plain UTF-8 JSON.
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _upsert_json_server(ctx: Context, agent: str, path: Path, entry: dict) -> None:
    try:
        data = _read_json(path)
    except (OSError, ValueError) as exc:
        ctx.report(agent, "MCP", f"讀不到 {path}（{type(exc).__name__}），沒有改動")
        return
    servers = data.get("mcpServers")
    if servers is not None and not isinstance(servers, dict):
        ctx.report(agent, "MCP", f"{path} 的 mcpServers 不是物件，沒有改動")
        return
    existing = (servers or {}).get(SERVER_NAME)
    if isinstance(existing, dict) and _entry_matches(existing.get("command"), existing.get("args"), ctx):
        ctx.report(agent, "MCP", f"已註冊（{path}）")
        return
    if existing is not None and not ctx.force:
        ctx.report(agent, "MCP", f"{path} 已有別的 {SERVER_NAME} 設定，沒有覆蓋；要改成這次的安裝，加 --force")
        return
    action = "取代既有的" if existing is not None else "新增"
    if ctx.dry_run:
        ctx.report(agent, "MCP", f"會在 {path} {action} {SERVER_NAME}：{ctx.python} {ctx.server_script}")
        return
    data.setdefault("mcpServers", {})[SERVER_NAME] = entry
    _write_json(path, data)
    ctx.report(agent, "MCP", f"已{action} {SERVER_NAME}（{path}）")


def _cli_add(ctx: Context, agent: str, remove_cmd: list[str] | None, add_cmd: list[str]) -> None:
    shown = " ".join(add_cmd)
    if ctx.dry_run:
        prefix = f"{' '.join(remove_cmd)}；" if remove_cmd else ""
        ctx.report(agent, "MCP", f"會執行：{prefix}{shown}")
        return
    if remove_cmd:
        ctx.run(remove_cmd)
    result = ctx.run(add_cmd)
    if result.returncode == 0:
        ctx.report(agent, "MCP", f"已註冊（{shown}）")
    else:
        ctx.report(agent, "MCP", f"註冊失敗（exit {result.returncode}）：{shown}")


# ── Claude Code ────────────────────────────────────────────────────

def register_claude_mcp(ctx: Context) -> None:
    claude = ctx.cli("claude")
    if not claude:
        entry = {"type": "stdio", "command": ctx.python, "args": [ctx.server_script], "env": {}}
        _upsert_json_server(ctx, "claude", ctx.home / ".claude.json", entry)
        return
    probe = ctx.run([claude, "mcp", "get", SERVER_NAME])
    remove = None
    if probe.returncode == 0:
        # Only check for our script path; the output is never printed.
        output = (probe.stdout or "") + (probe.stderr or "")
        normalized = os.path.normcase(output.replace("\\\\", "\\"))
        if os.path.normcase(ctx.server_script) in normalized and os.path.normcase(ctx.python) in normalized:
            ctx.report("claude", "MCP", "已註冊（claude mcp get omnikeep）")
            return
        if not ctx.force:
            ctx.report("claude", "MCP", f"已有別的 {SERVER_NAME} 設定，沒有覆蓋；要改成這次的安裝，加 --force")
            return
        remove = [claude, "mcp", "remove", "-s", "user", SERVER_NAME]
    _cli_add(ctx, "claude", remove,
             [claude, "mcp", "add", "-s", "user", SERVER_NAME, "--", ctx.python, ctx.server_script])


# ── Codex ──────────────────────────────────────────────────────────

def _toml_string(value: str) -> str:
    # JSON string escapes are valid TOML basic-string escapes.
    return json.dumps(value)


def register_codex_mcp(ctx: Context) -> None:
    config = ctx.home / ".codex" / "config.toml"
    try:
        data = tomllib.loads(config.read_text(encoding="utf-8")) if config.is_file() else {}
    except (OSError, tomllib.TOMLDecodeError) as exc:
        ctx.report("codex", "MCP", f"讀不到 {config}（{type(exc).__name__}），沒有改動")
        return
    existing = (data.get("mcp_servers") or {}).get(SERVER_NAME)
    if isinstance(existing, dict) and _entry_matches(existing.get("command"), existing.get("args"), ctx):
        ctx.report("codex", "MCP", f"已註冊（{config}）")
        return
    if existing is not None and not ctx.force:
        ctx.report("codex", "MCP", f"{config} 已有別的 {SERVER_NAME} 設定，沒有覆蓋；要改成這次的安裝，加 --force")
        return

    codex = ctx.cli("codex")
    if codex:
        remove = [codex, "mcp", "remove", SERVER_NAME] if existing is not None else None
        _cli_add(ctx, "codex", remove, [codex, "mcp", "add", SERVER_NAME, "--", ctx.python, ctx.server_script])
        return
    if existing is not None:
        ctx.report("codex", "MCP", f"找不到 codex 指令，無法安全取代 {config} 裡既有的 {SERVER_NAME}；請手動修改")
        return
    block = (f"\n[mcp_servers.{SERVER_NAME}]\n"
             f"command = {_toml_string(ctx.python)}\n"
             f"args = [{_toml_string(ctx.server_script)}]\n")
    if ctx.dry_run:
        ctx.report("codex", "MCP", f"會在 {config} 加上 [mcp_servers.{SERVER_NAME}]")
        return
    config.parent.mkdir(parents=True, exist_ok=True)
    if config.is_file():
        _backup(config)
        text = config.read_text(encoding="utf-8")
        if text and not text.endswith("\n"):
            block = "\n" + block
    with config.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(block)
    ctx.report("codex", "MCP", f"已新增 [mcp_servers.{SERVER_NAME}]（{config}）")


# ── Antigravity ────────────────────────────────────────────────────

def register_antigravity_mcp(ctx: Context) -> None:
    config = ctx.home / ".gemini" / "config" / "mcp_config.json"
    entry = {"command": ctx.python, "args": [ctx.server_script]}
    _upsert_json_server(ctx, "antigravity", config, entry)
    legacy = ctx.home / ".gemini" / "antigravity" / "mcp_config.json"
    try:
        legacy_servers = _read_json(legacy).get("mcpServers") or {}
    except (OSError, ValueError):
        legacy_servers = {}
    if isinstance(legacy_servers, dict) and SERVER_NAME in legacy_servers:
        ctx.report("antigravity", "MCP",
                   f"舊位置 {legacy} 也有 {SERVER_NAME}，沒有改動；新版 Antigravity 讀 {config}")


# ── Skill ──────────────────────────────────────────────────────────

SKILL_DIRS = {
    "claude": (".claude", "skills"),
    "codex": (".agents", "skills"),
    "antigravity": (".gemini", "config", "skills"),
}


def _remove_tree(path: Path, attempts: int = 10) -> None:
    # Windows antivirus briefly locks freshly written files; retry instead of failing the install.
    for attempt in range(attempts):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(0.3)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_files(source: Path) -> dict[str, str]:
    return {p.relative_to(source).as_posix(): _sha256(p)
            for p in sorted(source.rglob("*")) if p.is_file()}


def install_skill(ctx: Context, agent: str) -> None:
    source = ctx.skill_source
    if not (source / "SKILL.md").is_file():
        ctx.report(agent, "Skill", f"找不到 {source / 'SKILL.md'}，略過")
        return
    target = ctx.home.joinpath(*SKILL_DIRS[agent]) / SKILL_NAME
    wanted = _source_files(source)
    marker = target / INSTALL_MARKER

    if target.exists():
        current = {p.relative_to(target).as_posix(): _sha256(p)
                   for p in target.rglob("*") if p.is_file() and p.name != INSTALL_MARKER}
        if current == wanted:
            ctx.report(agent, "Skill", f"已是最新（{target}）")
            return
        try:
            recorded = json.loads(marker.read_text(encoding="utf-8")).get("files")
        except (OSError, ValueError):
            recorded = None
        untouched = recorded is not None and current == recorded
        if not untouched and not ctx.force:
            ctx.report(agent, "Skill", f"{target} 被改過或不是這個腳本裝的，沒有覆蓋；要換成新版，加 --force")
            return
        action = "更新" if untouched else "取代（舊版留在 .bak）"
    else:
        action = "安裝"
        untouched = True

    if ctx.dry_run:
        ctx.report(agent, "Skill", f"會{action}到 {target}")
        return
    if target.exists():
        if untouched:
            _remove_tree(target)
        else:
            backup = target.with_name(target.name + ".bak")
            if backup.exists():
                _remove_tree(backup)
            target.rename(backup)
    shutil.copytree(source, target)
    marker.write_text(json.dumps({"source": str(source), "files": wanted}, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    ctx.report(agent, "Skill", f"已{action}到 {target}")


MCP_REGISTRARS = {
    "claude": register_claude_mcp,
    "codex": register_codex_mcp,
    "antigravity": register_antigravity_mcp,
}


def register(ctx: Context, agents: list[str], *, mcp: bool = True, skills: bool = True) -> list[tuple[str, str, str]]:
    for agent in agents:
        if mcp:
            MCP_REGISTRARS[agent](ctx)
        if skills:
            install_skill(ctx, agent)
    return ctx.results


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把 OmniKeep 的 MCP 與 Skill 註冊到 Claude Code、Codex、Antigravity。")
    parser.add_argument("--project-dir", type=Path, default=Path(__file__).resolve().parents[1],
                        help="OmniKeep 資料夾（預設：這個腳本所在的 repo）")
    parser.add_argument("--python", help="啟動 MCP 用的 Python（預設：專案 .venv，沒有就用目前的 Python）")
    parser.add_argument("--agents", help="逗號分隔：claude,codex,antigravity（預設：偵測到的全部）")
    parser.add_argument("--home", type=Path,
                        help="改用別的家目錄（測試用）；指定時不呼叫 claude、codex 指令，直接寫設定檔")
    parser.add_argument("--no-cli", action="store_true", help="不呼叫 claude、codex 指令，直接寫設定檔")
    parser.add_argument("--skip-mcp", action="store_true", help="只裝 Skill")
    parser.add_argument("--skip-skills", action="store_true", help="只註冊 MCP")
    parser.add_argument("--force", action="store_true", help="取代既有的 omnikeep 設定與被改過的 Skill（會留 .bak）")
    parser.add_argument("--dry-run", action="store_true", help="只列出會做的事，不改任何東西")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    args = parse_args(argv)
    project_dir = args.project_dir.resolve()
    if not (project_dir / "mcp_server.py").is_file():
        print(f"{project_dir} 不是 OmniKeep 資料夾（找不到 mcp_server.py）。")
        return 2
    ctx = Context(
        project_dir=project_dir,
        python=os.path.normpath(args.python) if args.python else default_python(project_dir),
        home=(args.home or Path.home()).resolve(),
        dry_run=args.dry_run,
        force=args.force,
        use_cli=not (args.no_cli or args.home),
    )
    if args.agents:
        agents = [a.strip().lower() for a in args.agents.split(",") if a.strip()]
        unknown = [a for a in agents if a not in AGENTS]
        if unknown:
            print(f"不認得的 agent：{', '.join(unknown)}（可用：{', '.join(AGENTS)}）")
            return 2
    else:
        agents = detect_agents(ctx)
    if not agents:
        print("沒有偵測到 Claude Code、Codex 或 Antigravity；裝好之後再執行一次。")
        return 1

    print(f"OmniKeep：{project_dir}")
    print(f"MCP 指令：{ctx.python} {ctx.server_script}")
    print(f"agent：{', '.join(AGENT_LABELS[a] for a in agents)}")
    register(ctx, agents, mcp=not args.skip_mcp, skills=not args.skip_skills)
    if args.dry_run:
        print("以上是 dry-run，沒有改動任何東西。")
    else:
        print("完成。開一個新的 agent session，說「幫我設定 OmniKeep」。")
    failed = any("失敗" in message or "讀不到" in message for _, _, message in ctx.results)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
