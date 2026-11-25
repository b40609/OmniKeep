"""Evaluator adapters decoupling OmniKeep from optional local OmniKit installation."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.eval.security import BADGE_EXECUTABLE, VALID_BADGES, classify_security_badge
from app.network import public_http_client
from app.parsers.github_repo import fetch_repo, repo_from_url
from app.providers import get_primary_provider
from app.providers.base import UnconfiguredProvider

logger = logging.getLogger("omnikeep.eval.adapter")

_SKILL_NAME = "omnikit-eval"
_AGENT_HOME_DIRS = (".claude", ".codex", ".agents")


def _legacy_skill_config_candidates(home: Path) -> List[Path]:
    """Legacy (pre-sync.py) marker files written next to installed skills."""
    return [home / agent / "skills" / _SKILL_NAME / ".omnikit.json" for agent in _AGENT_HOME_DIRS]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _omnikit_state_dir(home: Optional[Path] = None) -> Path:
    raw = (os.environ.get("OMNIKIT_STATE_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return (home or Path.home()) / ".omnikit"


def _looks_like_omnikit_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    if (path / "data" / "omnikit.yaml").is_file():
        return True
    return _find_cli_script(path, "eval_single.py") is not None


def _read_repo_field(cfg_path: Path) -> Optional[Path]:
    if not cfg_path.is_file():
        return None
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    repo_val = str(data.get("repo") or "").strip()
    return Path(repo_val).expanduser() if repo_val else None


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def _state_dev_repo(state_dir: Path) -> Optional[Path]:
    """Development repo recorded by OmniKit sync.py in <state>/config.json (never the current/ copy)."""
    repo = _read_repo_field(state_dir / "config.json")
    if repo is None or not _looks_like_omnikit_repo(repo):
        return None
    if _is_within(repo, state_dir / "current"):
        return None
    return repo


def _prefer_dev_repo(candidate: Path, state_dir: Path) -> Path:
    """Redirect paths inside <state>/current back to the real git workspace when known.

    record_decision.py writes into the repo, so it must land in the development
    checkout rather than the clean copy that sync.py may overwrite.
    """
    if _is_within(candidate, state_dir / "current"):
        dev = _state_dev_repo(state_dir)
        if dev is not None:
            return dev
    return candidate


def _repo_from_skill_link(home: Path) -> Optional[Path]:
    """Resolve ~/.claude|.codex/skills/omnikit-eval junctions to <repo>/engine/skills/omnikit-eval."""
    for agent in _AGENT_HOME_DIRS:
        link = home / agent / "skills" / _SKILL_NAME
        if not link.exists():
            continue
        try:
            target = link.resolve()
        except OSError:
            continue
        if len(target.parents) < 3:
            continue
        repo = target.parents[2]
        if (repo / "data" / "omnikit.yaml").is_file():
            return repo
    return None


def _discover_omnikit_repo(home: Path, state_dir: Path) -> Optional[Path]:
    """Probe OmniKit install locations (sync.py layout first, legacy markers last)."""
    # a. <state>/config.json written by OmniKit sync.py
    dev = _state_dev_repo(state_dir)
    if dev is not None:
        return dev

    # b. Skill junctions installed by sync.py
    linked = _repo_from_skill_link(home)
    if linked is not None:
        return _prefer_dev_repo(linked, state_dir)

    # c. Legacy .omnikit.json markers (pre-sync.py installs)
    for cfg_path in _legacy_skill_config_candidates(home):
        repo = _read_repo_field(cfg_path)
        if repo is not None and repo.is_dir():
            return _prefer_dev_repo(repo, state_dir)

    # d. Clean copy as the very last resort
    current = state_dir / "current"
    if _looks_like_omnikit_repo(current):
        return current
    return None


def resolve_omnikit_repo() -> Optional[Path]:
    """Locate the local OmniKit repository if configured or installed on this host."""
    raw = (getattr(settings, "OMNIKIT_REPO_PATH", "") or os.environ.get("OMNIKIT_REPO_PATH") or "").strip()
    if raw:
        candidate = Path(raw).expanduser()
        if not candidate.is_dir():
            return None
        return _prefer_dev_repo(candidate, _omnikit_state_dir())

    # Never probe host skill folders during isolated automated tests.
    if os.environ.get("OMNIKEEP_TESTING") == "1":
        return None

    home = Path.home()
    return _discover_omnikit_repo(home, _omnikit_state_dir(home))


def _find_cli_script(repo_path: Path, filename: str) -> Optional[Path]:
    for rel in (
        Path("scripts") / filename,
        Path("engine") / "skills" / _SKILL_NAME / "scripts" / filename,
        Path("skills") / _SKILL_NAME / "scripts" / filename,
    ):
        candidate = repo_path / rel
        if candidate.is_file():
            return candidate
    return None


def build_layer2_request(
    evaluation: Dict[str, Any],
    item: Optional[Dict[str, Any]] = None,
    note: str = "",
) -> Dict[str, Any]:
    """Build a structured Layer 2 evaluation request matching OmniKit's contract."""
    l1 = evaluation.get("l1") or {}
    claims = l1.get("claims") or []
    return {
        "schema_version": "1.0",
        "source": "omnikeep_mobile_approval",
        "eval_id": evaluation.get("id"),
        "item_id": evaluation.get("item_id"),
        "tool_id": l1.get("tool_id") or evaluation.get("target_repo") or evaluation.get("item_id"),
        "name": l1.get("name") or (item or {}).get("title_l1") or evaluation.get("item_title") or "",
        "target_repo": evaluation.get("target_repo") or "",
        "target_url": evaluation.get("target_url") or (item or {}).get("url") or "",
        "security_badge": evaluation.get("security_badge") or BADGE_EXECUTABLE,
        "slots": l1.get("slots") or [],
        "claims_to_verify": claims,
        "community_counterpoints": evaluation.get("community_counterpoints") or [],
        "user_note": (item or {}).get("user_note") or evaluation.get("user_note") or "",
        "approval_note": note.strip(),
        "approved_at": _now_iso(),
        "interactive": False,
    }


class EvaluatorAdapter(ABC):
    name: str = "base"

    @abstractmethod
    async def evaluate(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Run up to Layer 1 read-only evaluation and return normalized JSON payload."""

    @abstractmethod
    async def record_decision(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Write back user/agent decision when supported by the adapter."""


class OmniKitAdapter(EvaluatorAdapter):
    """Subprocess adapter to local OmniKit single-item L0+L1 CLI scripts."""

    name = "omnikit"

    def __init__(self, repo_path: Path, eval_script: Path, decision_script: Optional[Path] = None, timeout: float = 120.0):
        self.repo_path = repo_path
        self.eval_script = eval_script
        self.decision_script = decision_script
        self.timeout = timeout

    async def _run_cli(self, script: Path, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            str(script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(self.repo_path),
            env=env,
        )
        raw_in = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(raw_in), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"OmniKit 評估逾時（超過 {int(timeout)} 秒）")

        stdout_s = stdout_b.decode("utf-8", errors="replace").strip()
        stderr_s = stderr_b.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            raise RuntimeError(f"OmniKit CLI 結束碼 {proc.returncode}: {(stderr_s or stdout_s)[:300]}")
        try:
            parsed = json.loads(stdout_s)
        except Exception as exc:
            raise RuntimeError(f"OmniKit CLI 未回傳合法 JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("OmniKit CLI 回傳格式不是 JSON 物件")
        return parsed

    async def evaluate(self, request: Dict[str, Any]) -> Dict[str, Any]:
        # Hard safety cap: background evaluation must never exceed Layer 1.
        safe_req = {**request, "max_layer": 1}
        result = await self._run_cli(self.eval_script, safe_req, self.timeout)
        if result.get("status") == "error":
            raise RuntimeError(result.get("error") or "OmniKit 回報評估失敗")

        l0 = result.get("layer0") or {}
        badge = str(result.get("security_badge") or "").strip()
        if badge not in VALID_BADGES:
            badge = classify_security_badge(l0.get("scan"), verdict=str(l0.get("verdict") or ""))
            result["security_badge"] = badge
        return result

    async def record_decision(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.decision_script:
            return {"synced": False, "adapter": self.name, "reason": "decision_script_missing"}
        try:
            res = await self._run_cli(self.decision_script, payload, min(self.timeout, 30.0))
            return {"synced": True, "adapter": self.name, "response": res}
        except Exception as exc:
            logger.warning("[Eval:OmniKit] Decision writeback failed: %s", exc)
            return {"synced": False, "adapter": self.name, "reason": str(exc)}


class LocalLiteAdapter(EvaluatorAdapter):
    """Standalone read-only fallback evaluator when OmniKit is not installed locally."""

    name = "local_lite"

    async def _fetch_github_meta(self, owner: str, repo: str) -> Dict[str, Any]:
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "OmniKeep"}
        token = (getattr(settings, "GITHUB_TOKEN", "") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with public_http_client(timeout=12.0, follow_redirects=True) as client:
                res = await client.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
                if res.status_code != 200:
                    return {}
                data = res.json()
                return {
                    "stars": int(data.get("stargazers_count") or 0),
                    "forks": int(data.get("forks_count") or 0),
                    "license": ((data.get("license") or {}).get("spdx_id") or ""),
                    "archived": bool(data.get("archived")),
                    "pushed_at": data.get("pushed_at") or "",
                    "description": data.get("description") or "",
                    "language": data.get("language") or "",
                }
        except Exception as exc:
            logger.info("[Eval:LocalLite] GitHub metadata fetch failed for %s/%s: %s", owner, repo, exc)
            return {}

    async def evaluate(self, request: Dict[str, Any]) -> Dict[str, Any]:
        target_url = str(request.get("target_url") or "")
        target_repo = str(request.get("target_repo") or "")
        repo_tuple = repo_from_url(target_url) or (
            tuple(target_repo.split("/", 1)) if "/" in target_repo else None  # type: ignore[assignment]
        )
        gh_meta: Dict[str, Any] = {}
        repo_files: List[str] = []
        if repo_tuple and len(repo_tuple) == 2:
            owner, repo = repo_tuple[0], repo_tuple[1]
            target_repo = f"{owner}/{repo}"
            gh_meta, repo_info = await asyncio.gather(
                self._fetch_github_meta(owner, repo),
                fetch_repo(owner, repo),
            )
            repo_files = list((repo_info or {}).get("paths") or [])

        badge = classify_security_badge(scan={}, repo_files=repo_files)
        verdict = "warn" if badge != "skill_scan_pass" else "pass"
        l0 = {
            "layer": 0,
            "repo": target_repo,
            "url": target_url,
            "checked_at": _now_iso(),
            "github": gh_meta,
            "roster": {"matches": [], "similar_rejected": []},
            "scan": {
                "scanner": "omnikeep-local-lite",
                "skills_found": sum(1 for p in repo_files if p.lower().endswith("skill.md")),
                "files_checked": len(repo_files),
            },
            "verdict": verdict,
            "next": "layer1",
        }

        l1, slot_cmp, suggested = await self._build_l1_assessment(request, target_repo, target_url, gh_meta, repo_files)
        return {
            "schema_version": "1.0",
            "status": "ok",
            "security_badge": badge,
            "layer0": l0,
            "layer1": l1,
            "slot_comparison": slot_cmp,
            "suggested_action": suggested,
            "error": "",
        }

    async def _build_l1_assessment(
        self,
        request: Dict[str, Any],
        target_repo: str,
        target_url: str,
        gh_meta: Dict[str, Any],
        repo_files: List[str],
    ) -> tuple:
        tool_name = target_repo.split("/")[-1] if "/" in target_repo else (target_repo or "candidate-tool")
        user_note = str(request.get("user_note") or "").strip()
        summary = str(request.get("source_summary") or gh_meta.get("description") or "").strip()
        counterpoints = request.get("community_counterpoints") or []

        provider = get_primary_provider()
        if not isinstance(provider, UnconfiguredProvider):
            try:
                cp_text = "\n".join(f"- [{c.get('category', 'limitation')}] {c.get('point', '')}" for c in counterpoints[:5])
                files_preview = ", ".join(repo_files[:35]) if repo_files else "（未取得檔案清單）"
                prompt = (
                    "請對以下候選工具進行純唯讀 Layer 1 初步評估，直接輸出合法 JSON。\n"
                    f"工具名稱：{tool_name}\n倉庫：{target_repo or target_url}\n"
                    f"GitHub 資訊：{json.dumps(gh_meta, ensure_ascii=False)}\n"
                    f"主要檔案：{files_preview}\n"
                    f"來源摘要：{summary}\n"
                    f"使用者提問／備註：{user_note or '（無）'}\n"
                    f"社群實測與反例：\n{cp_text or '（無）'}\n\n"
                    "輸出 JSON 格式：\n"
                    '{"slots":["領域槽位"],"scenarios":["適用情境"],'
                    '"summary":"2句台灣繁中精煉判讀，回應使用者提問",'
                    '"differences":"與一般現成做法的差異及導入維護成本",'
                    '"claims":[{"claim":"關鍵宣稱","kind":"performance|capability|compatibility","how_to_verify":"L2 驗證方式"}],'
                    '"recommendation":"deep_eval|keep_pending|reject",'
                    '"delta_summary":"一句話總結建議進 L2 實測或收為情境備案"}'
                )
                ai = await provider.generate_json(
                    prompt,
                    "你是嚴謹的工具架構評估員，全程使用繁體中文（台灣用語），不得編造未見於資料的數據。只輸出 JSON。",
                )
                if isinstance(ai, dict) and (ai.get("summary") or ai.get("delta_summary")):
                    rec = str(ai.get("recommendation") or "deep_eval").strip().lower()
                    if rec not in ("reject", "keep_pending", "deep_eval"):
                        rec = "deep_eval"
                    suggested = "reject" if rec == "reject" else ("on_demand" if rec == "keep_pending" else "approve_l2")
                    l1 = {
                        "layer": 1,
                        "tool_id": tool_name,
                        "name": tool_name,
                        "url": target_url,
                        "slots": list(ai.get("slots") or ["general_agent_tool"]),
                        "scenarios": list(ai.get("scenarios") or []),
                        "summary": str(ai.get("summary") or summary),
                        "differences": str(ai.get("differences") or ""),
                        "claims": list(ai.get("claims") or []),
                        "native_coverage": {
                            "covered": "none",
                            "by": [],
                            "note": "目前以 OmniKeep 輕量模式評估（本機未連接 OmniKit 名冊）。",
                        },
                        "recommendation": rec,
                        "needs_user": True,
                    }
                    slot_cmp = {
                        "matched_slots": l1["slots"],
                        "incumbent_tools": [],
                        "delta_summary": str(ai.get("delta_summary") or l1["summary"]),
                    }
                    return l1, slot_cmp, suggested
            except Exception as exc:
                logger.info("[Eval:LocalLite] LLM L1 fallback to deterministic summary: %s", exc)

        claims = []
        if summary:
            claims.append({
                "claim": summary[:160],
                "kind": "capability",
                "how_to_verify": "核准進 Layer 2 後，於隔離環境比對實際輸入輸出與現有流程耗時。",
            })
        l1 = {
            "layer": 1,
            "tool_id": tool_name,
            "name": tool_name,
            "url": target_url,
            "slots": ["general_agent_tool"],
            "scenarios": [user_note] if user_note else [],
            "summary": summary or f"已收錄候選工具 {tool_name}，待桌機檢視確認是否導入。",
            "differences": "目前以輕量模式評估（未連接 OmniKit 個人工具名冊，略過現任工具自動比對）。",
            "claims": claims,
            "native_coverage": {
                "covered": "none",
                "by": [],
                "note": "未偵測到本機 OmniKit 名冊。",
            },
            "recommendation": "deep_eval",
            "needs_user": True,
        }
        slot_cmp = {
            "matched_slots": l1["slots"],
            "incumbent_tools": [],
            "delta_summary": l1["summary"],
        }
        return l1, slot_cmp, "approve_l2"

    async def record_decision(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {"synced": False, "adapter": self.name, "reason": "local_only"}


def get_evaluator_adapter() -> EvaluatorAdapter:
    """Select OmniKitAdapter when local OmniKit CLI scripts exist, else LocalLiteAdapter."""
    repo = resolve_omnikit_repo()
    if repo:
        eval_script = _find_cli_script(repo, "eval_single.py")
        if eval_script:
            decision_script = _find_cli_script(repo, "record_decision.py")
            return OmniKitAdapter(repo, eval_script, decision_script)
    return LocalLiteAdapter()
