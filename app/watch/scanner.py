"""Watch-target scanner — L0 filename risk scan + L1 project fingerprint.

Two permission axes from the watch_targets row govern everything:
  read_scope.filenames is the floor; without it the target is skipped entirely.
  outbound_consent decides which material may be sent to Agnes; anything sent
  passes through redact_text() first regardless of preset (the one hard rule).
"""
import hashlib
import json
import uuid
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.database import (
    save_item,
    update_watch_target,
    save_proposal,
    get_watch_target,
    proposal_seen,
)
from app.providers import get_primary_provider
from app.config import settings
from app.watch.redact import redact_text, find_risky_files, is_risky_filename
from app.watch.locks import target_lock

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build",
    "target", ".next", ".idea", ".vscode", ".cache", "site-packages",
    ".tmp", ".pytest_cache", ".ruff_cache",
}
README_NAMES = ["README.md", "README.rst", "README.txt", "readme.md", "README"]
DEP_MANIFESTS = [
    "requirements.txt", "pyproject.toml", "setup.py", "Pipfile",
    "package.json", "go.mod", "Cargo.toml", "pom.xml", "environment.yml",
    "composer.json", "Gemfile",
]

FINGERPRINT_SYSTEM_PROMPT = """你是一位資深技術架構偵察官。根據本地專案的「結構指紋」素材，產出專案認知卡。
嚴格規則：
1. 一律繁體中文，極簡高密度，禁止廢話。
2. 嚴格輸出 JSON：
{
  "title_l1": "專案一句話定位（20字內）",
  "summary_l1": "這專案做什麼、技術棧核心、目前階段（2句話）",
  "tech_tags": ["技術棧1", "核心依賴2"],
  "deep_analysis": "Markdown：架構觀察（目錄結構透露的設計）、依賴分析（用了什麼框架/庫、版本線索）、近期變化（git 訊號，若有）、可關注的演進方向"
}
素材中出現 [REDACTED:...] 標記代表機密已被遮蔽，請忽略該處內容，不要猜測。"""


def _walk_files(root: Path, max_files: int = 8000) -> List[str]:
    """Relative file paths, breadth-limited; directory names are visible too."""
    files: List[str] = []
    if not root.is_dir():
        return files
    stack = [(root, 0)]
    database = Path(settings.DATABASE_PATH).resolve()
    runtime_files = {database, *(Path(str(database) + suffix) for suffix in ("-wal", "-shm", ".worker.lock"))}
    backup_dir = Path(settings.BACKUP_DIR).resolve()
    while stack and len(files) < max_files:
        cur, depth = stack.pop()
        try:
            entries = sorted(cur.iterdir(), key=lambda p: (p.is_dir(), p.name))
        except (PermissionError, OSError):
            continue
        for entry in entries:
            if len(files) >= max_files:
                break
            if entry.is_symlink() or getattr(entry, "is_junction", lambda: False)():
                continue
            if not entry.resolve().is_relative_to(root.resolve()):
                continue
            if entry.resolve() in runtime_files or entry.resolve() == backup_dir:
                continue
            rel = str(entry.relative_to(root)).replace("\\", "/")
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and depth < 5:
                    stack.append((entry, depth + 1))
            else:
                files.append(rel)
    return files


def _read_chunk(path: Path, limit: int = 8000) -> str:
    try:
        if path.is_symlink() or is_risky_filename(path.name):
            return ""
        with path.open(encoding="utf-8", errors="replace") as handle:
            return handle.read(limit)
    except OSError:
        return ""


def _git_log(root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--oneline", "-15", "--no-decorate"],
            capture_output=True, text=True, timeout=15,
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _material_sections(root: Path, files: List[str], scope: Dict[str, bool]) -> Dict[str, str]:
    by_ext: Dict[str, int] = {}
    for f in files:
        ext = Path(f).suffix.lower() or "(noext)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
    sections = {"summary": f"檔案數：{len(files)}\n副檔名分布：{json.dumps(by_ext, ensure_ascii=False)}"}
    if scope.get("readme"):
        sections["docs"] = next((chunk for name in README_NAMES if name in files
                                  and (chunk := _read_chunk(root / name))), "")
    if scope.get("deps"):
        sections["deps"] = "\n\n".join(f"### {name}\n{_read_chunk(root / name, 4000)}"
                                              for name in DEP_MANIFESTS if name in files)
    if scope.get("code"):
        extensions = {".py", ".ts", ".js", ".vue", ".rs", ".go", ".java", ".cpp", ".c", ".cs"}
        samples = [name for name in files if Path(name).suffix.lower() in extensions and not is_risky_filename(name)][:12]
        sections["code"] = "\n\n".join(f"### {name}\n{_read_chunk(root / name, 2000)}" for name in samples)
    if scope.get("git") and (root / ".git").exists():
        sections["git"] = _git_log(root)
    return sections


def _build_material(root: Path, files: List[str], scope: Dict[str, bool]) -> str:
    return "\n\n".join(_material_sections(root, files, scope).values())


def _fingerprint_version(files, root, scope=None, consent=None, sections=None) -> str:
    h = hashlib.sha256()
    h.update(json.dumps({"scope": scope, "consent": consent, "sections": sections}, sort_keys=True).encode())
    for name in files:
        try:
            stat = (root / name).stat()
            h.update(f"{name}:{stat.st_size}:{stat.st_mtime_ns}".encode())
        except OSError:
            continue
    return "v2:" + h.hexdigest()[:24]


async def scan_target(target: Dict[str, Any]) -> Dict[str, Any]:
    async with target_lock(("scan", target["id"])):
        latest = get_watch_target(target["id"])
        if latest is None or not latest["is_active"]:
            return {"target_id": target["id"], "ok": False, "error": "target unavailable"}
        return await _scan_target(latest)


async def _scan_target(target: Dict[str, Any]) -> Dict[str, Any]:
    """Scan one watch target: risk check (always, filenames only) + fingerprint refresh."""
    tid = target["id"]
    root = Path(target["path"]).resolve()
    scope = target["read_scope"]
    consent = target["outbound_consent"]
    now_iso = datetime.now(timezone.utc).isoformat()
    result: Dict[str, Any] = {"target_id": tid, "ok": False, "risk_proposal": False,
                              "fingerprint_updated": False}

    if not root.is_dir():
        result["error"] = f"path not found: {root}"
        update_watch_target(tid, {"last_scan_at": now_iso})
        return result
    if not scope.get("filenames"):
        result["error"] = "read_scope.filenames is off — nothing OmniKeep may look at"
        return result

    files = _walk_files(root)

    # 1) L0 risk scan — filenames only, pure local, no LLM needed
    risky = find_risky_files(files)
    risk_hash = hashlib.sha256("\n".join(risky).encode()).hexdigest()[:16]
    risk_key = f"risk:{tid}:{risk_hash}"
    if risky and target["target_type"] in ("folder", "desktop_risk") and not proposal_seen(risk_key):
        shown = ", ".join(risky[:8]) + ("…" if len(risky) > 8 else "")
        risk_card = {
            "url": f"proposal://risk/{tid}/{risk_hash}/{uuid.uuid4().hex}",
            "source_type": "proposal",
            "origin": "proposal",
            "category_name": "提案",
            "title_l1": f"⚠️ 風險提案：{target['name']} 有 {len(risky)} 個疑似明文機密檔",
            "summary_l1": (f"偵測到 {len(risky)} 個高風險命名的明文檔（如 {risky[0]}）。"
                           "建議移入加密存放（密碼管理器／加密磁區），並確認這些金鑰未進過任何 git 儲存庫。"),
            "tech_tags": ["風險", "機密檔", "L0掃描"],
            "deep_analysis": (
                "### 命中清單\n" + "\n".join(f"- `{f}`" for f in risky[:30]) +
                "\n\n### 建議處置\n1. 移入加密存放（1Password / VeraCrypt / 加密 zip）\n"
                "2. 若曾同步過雲端或 git → 視為已外洩，直接輪換金鑰\n"
                "3. 純本機留存者至少改用加密容器\n\n_本提案僅讀取檔名，未開啟任何檔案內容。_"),
            "author": "OmniKeep 監看引擎",
        }
        saved = save_proposal({
            "target_id": tid, "proposal_type": "risk",
            "impact": 8.0, "confidence": 9.0, "effort": 2.0,
            "dedup_key": risk_key,
        }, item_data=risk_card)
        result["risk_proposal"] = saved is not None

    # 2) Fingerprint refresh — skip Agnes when nothing changed
    sections = _material_sections(root, files, scope)
    version = _fingerprint_version(files, root, scope, consent, sections)
    if version == target.get("fingerprint_version"):
        update_watch_target(tid, {"last_scan_at": now_iso, "fingerprint_version": version})
        result.update(ok=True, changed=False, file_count=len(files))
        return result

    material = redact_text("\n\n".join(sections.values()))
    # Each content category needs its own outbound grant; summary grants statistics only.
    outbound = "\n\n".join(f"### {kind}\n{value}" for kind, value in sections.items()
                                  if value and consent.get(kind))
    send_text = redact_text(f"專案名稱：{target['name']}\n\n{outbound}")[:12000] if outbound else ""

    fp: Dict[str, Any]
    if send_text:
        try:
            provider = get_primary_provider()
            fp = await provider.generate_json(
                send_text,
                FINGERPRINT_SYSTEM_PROMPT,
            )
        except Exception as e:  # LLM down → degrade to local-only fingerprint
            fp = {}
    else:
        fp = {}

    if fp.get("title_l1"):
        title = fp["title_l1"]
        summary = fp.get("summary_l1", "")
        tags = fp.get("tech_tags", [])
        deep = fp.get("deep_analysis", "")
        basis = "、".join(k for k in ("readme", "deps", "git") if scope.get(k)) or "檔名"
        deep = f"> 指紋依據：{basis}（外送同意：{'、'.join(k for k, v in consent.items() if v) or '僅本地'}，已遮蔽機密）\n\n{deep}"
    else:
        title = f"{target['name']} 專案指紋（本地統計）"
        summary = f"{len(files)} 個檔案的結構指紋；未啟用雲端分析或分析失敗。"
        tags = ["watch", target["target_type"]]
        deep = f"### 結構統計\n- 檔案數：{len(files)}\n- 頂層項目：{', '.join(sorted({f.split('/')[0] for f in files})[:20])}"

    # Consent/path may have changed while the provider was running. Discard stale output.
    latest = get_watch_target(tid)
    if not latest or any(latest.get(key) != target.get(key) for key in ("path", "read_scope", "outbound_consent", "is_active")):
        result["error"] = "target permissions changed during scan"
        return result
    item_id = save_item({
        "url": f"watch://{tid}",
        "source_type": "watch",
        "origin": "watch",
        "category_name": "監看",
        "title_l1": redact_text(str(title)),
        "summary_l1": redact_text(str(summary)),
        "tech_tags": [redact_text(str(tag)) for tag in (tags if isinstance(tags, list) else [tags])],
        "deep_analysis": redact_text(str(deep)),
        "content_raw": material[:20000],
        "author": "OmniKeep 監看引擎",
    })
    update_watch_target(tid, {
        "last_scan_at": now_iso,
        "fingerprint_item_id": item_id,
        "fingerprint_version": version,
    })
    result.update(ok=True, changed=True, fingerprint_updated=True,
                  file_count=len(files), fingerprint_item_id=item_id)
    return result


async def scan_target_by_id(target_id: str) -> Optional[Dict[str, Any]]:
    from app.database import get_watch_target
    target = get_watch_target(target_id)
    if not target or not target["is_active"]:
        return None
    return await scan_target(target)
