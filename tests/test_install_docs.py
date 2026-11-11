"""The install one-liner, the setup Skill's example answers and the docs that must follow the code.

Docs drift without anyone noticing: these read the Markdown and the install script and
check them against what the code accepts.
"""
import json
import re
import unicodedata
from pathlib import Path

import pytest

from app import setup_flow

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
INSTALL_PS1 = ROOT / "scripts" / "install.ps1"
SKILL = ROOT / "skills" / "omnikeep-setup" / "SKILL.md"
MCP_DOC = ROOT / "docs" / "mcp_integration.md"
RAW_URL = "https://raw.githubusercontent.com/b40609/OmniKeep/main/scripts/install.ps1"


# ── Windows one-line install ────────────────────────────────────

def _one_liners(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8-sig")
    return [line.strip() for line in text.splitlines()
            if "[scriptblock]::Create" in line and "irm " in line]


@pytest.mark.parametrize("path", [README, INSTALL_PS1], ids=["README.md", "install.ps1"])
def test_windows_one_liner_strips_the_bom(path):
    # install.ps1 starts with a UTF-8 BOM (test_register_agents.py); irm returns it as the
    # first character and [scriptblock]::Create then fails to parse the script.
    lines = _one_liners(path)
    assert lines, f"{path.name} no longer shows the one-line install"
    for line in lines:
        assert RAW_URL in line
        assert ".TrimStart([char]0xFEFF)" in line, f"one-liner in {path.name} does not strip the BOM: {line}"


def test_readme_and_script_show_the_same_one_liner():
    assert set(_one_liners(README)) == set(_one_liners(INSTALL_PS1))


def test_install_ps1_never_exits_and_calls_npm_cmd():
    script = INSTALL_PS1.read_text(encoding="utf-8-sig")
    # exit inside a scriptblock (the one-line install) closes the user's PowerShell window.
    assert not re.search(r"^\s*exit\b", script, flags=re.MULTILINE)
    # A bare npm resolves to npm.ps1, which the Restricted execution policy refuses to run.
    assert "Invoke-Native 'npm'" not in script
    assert "'npm.cmd'" in script


# ── Setup Skill: the example answers must pass the server's schema ──

def _json_blocks(text: str) -> list[str]:
    return re.findall(r"```json\s*\n(.*?)```", text, flags=re.DOTALL)


_SKILL_ANSWERS = [block for block in _json_blocks(SKILL.read_text(encoding="utf-8")) if '"stage"' in block]


def test_skill_has_an_example_for_both_stages():
    stages = [json.loads(block).get("stage") for block in _SKILL_ANSWERS]
    assert stages == ["first", "followup"]


@pytest.mark.parametrize("block", _SKILL_ANSWERS, ids=lambda b: json.loads(b).get("stage", "?"))
def test_skill_example_answers_pass_parse_answers(block):
    parsed = setup_flow.parse_answers(json.loads(block))
    if parsed.stage == "first":
        assert parsed.about_you and parsed.topics and parsed.seed_links and parsed.sources
        assert parsed.ai_order and all(isinstance(i, int) for i in parsed.ai_order)
    else:
        assert parsed.analysis_depth and parsed.notifications and parsed.notifications.channels


# ── docs/mcp_integration.md lists every MCP tool ────────────────

def test_mcp_doc_lists_every_tool_and_the_right_count():
    source = (ROOT / "app" / "mcp_server.py").read_text(encoding="utf-8")
    tools = re.findall(r"@mcp\.tool\(\)\s+async def (\w+)", source)
    doc = MCP_DOC.read_text(encoding="utf-8")
    assert tools and [name for name in tools if f"`{name}`" not in doc] == []
    assert f"工具清單（{len(tools)} 個）" in doc


# ── README: internal links ──────────────────────────────────────

def _github_slug(heading: str) -> str:
    """GitHub's heading anchor: lower-case; keep letters, marks, numbers, "_", "-" and
    spaces; spaces become "-". An emoji is dropped, but its variation selector (U+FE0F, a
    mark) stays, which is why headings here use emoji without one."""
    kept = [ch for ch in heading.strip().lower()
            if ch in "-_ " or unicodedata.category(ch)[0] in "LMN"]
    return "".join(kept).replace(" ", "-")


def _readme_anchors(text: str) -> set[str]:
    anchors, seen = set(), {}
    in_code = False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_code = not in_code
        match = None if in_code else re.match(r"#{1,6}\s+(.*)", line)
        if match:
            slug = _github_slug(re.sub(r"`", "", match.group(1)))
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def test_readme_internal_links_resolve():
    text = README.read_text(encoding="utf-8")
    anchors = _readme_anchors(text)
    broken = []
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        path, _, fragment = target.partition("#")
        if path and not (ROOT / path).exists():
            broken.append(target)
        elif not path and fragment not in anchors:
            broken.append(target)
    assert broken == []
