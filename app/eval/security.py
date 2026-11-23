"""Three-state security badge classification for tool and skill evaluation."""
from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Dict, Iterable, List, Optional

BADGE_PASS = "skill_scan_pass"
BADGE_EXECUTABLE = "executable_needs_review"
BADGE_RISK = "risk_flagged"
VALID_BADGES = frozenset({BADGE_PASS, BADGE_EXECUTABLE, BADGE_RISK})

SECURITY_BADGE_META: Dict[str, Dict[str, str]] = {
    BADGE_PASS: {
        "code": BADGE_PASS,
        "tone": "green",
        "label": "Skill 靜態掃描通過",
        "detail": "已檢查靜態 Skill 規格，未發現高危規則或可執行安裝腳本。",
    },
    BADGE_EXECUTABLE: {
        "code": BADGE_EXECUTABLE,
        "tone": "amber",
        "label": "含可執行 CLI／MCP，需隔離檢視",
        "detail": "含可執行程式碼、套件設定或缺少 SKILL.md，靜態掃描無法涵蓋執行期行為，請於 L2 沙盒檢視。",
    },
    BADGE_RISK: {
        "code": BADGE_RISK,
        "tone": "red",
        "label": "掃出風險項目",
        "detail": "靜態檢查發現高風險指令或安全疑慮，建議先檢視風險明細再決定。",
    },
}

_EXECUTABLE_NAMES = {
    "package.json",
    "cargo.toml",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "go.mod",
    "dockerfile",
    "makefile",
    "mcp.json",
    ".mcp.json",
    "install.sh",
    "install.ps1",
}
_EXECUTABLE_EXTS = {".sh", ".ps1", ".bat", ".cmd", ".exe", ".dll", ".so", ".dylib"}


def detect_repo_artifacts(repo_files: Optional[Iterable[str]]) -> Dict[str, Any]:
    """Detect whether a repository contains SKILL.md definitions or executable build/MCP artifacts."""
    skills_count = 0
    executable_artifacts: List[str] = []
    for raw in repo_files or ():
        path = str(raw or "").strip()
        if not path:
            continue
        p = PurePosixPath(path)
        name_lower = p.name.lower()
        if name_lower == "skill.md":
            skills_count += 1
        elif name_lower in _EXECUTABLE_NAMES or p.suffix.lower() in _EXECUTABLE_EXTS:
            executable_artifacts.append(path)
        elif "mcp" in name_lower and name_lower.endswith(".json"):
            executable_artifacts.append(path)
    return {
        "skills_found": skills_count,
        "executable_artifacts": executable_artifacts[:20],
    }


def classify_security_badge(
    scan: Optional[Dict[str, Any]] = None,
    repo_files: Optional[Iterable[str]] = None,
    verdict: str = "",
) -> str:
    """Classify tool safety into a non-misleading three-state badge.

    Crucially, scanning 0 SKILL.md files or seeing executable CLI/MCP manifests never yields a
    green pass — those cases return ``executable_needs_review`` instead of a false green light.
    """
    scan_data = dict(scan or {})
    high_risk = scan_data.get("high_risk_findings") or scan_data.get("findings_high") or []
    if scan_data.get("risk_flagged") or high_risk or str(verdict or "").strip().lower() == "fail":
        return BADGE_RISK

    file_signals = detect_repo_artifacts(repo_files)
    exec_artifacts = list(scan_data.get("executable_artifacts") or []) + file_signals["executable_artifacts"]
    raw_skills = scan_data.get("skills_found")
    skills_found = int(raw_skills) if raw_skills is not None else file_signals["skills_found"]

    if exec_artifacts or skills_found <= 0:
        return BADGE_EXECUTABLE
    return BADGE_PASS


def badge_meta(code: str) -> Dict[str, str]:
    """Return UI metadata for a badge code, defaulting to the cautious amber badge."""
    return dict(SECURITY_BADGE_META.get(code) or SECURITY_BADGE_META[BADGE_EXECUTABLE])
