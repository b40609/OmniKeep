"""Watch-target scanner — L0 filename risk scan + L1 project fingerprint.

Two permission axes from the watch_targets row govern everything:
  read_scope.filenames is the floor; without it the target is skipped entirely.
  outbound_consent decides which material may be sent to Agnes; anything sent
  passes through redact_text() first regardless of preset (the one hard rule).
"""
import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional

from app.database import (
    save_item,
    update_watch_target,
    save_proposal,
)
from app.providers import get_primary_provider
from app.watch.redact import redact_text, find_risky_files

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv", "dist", "build",
    "target", ".next", ".idea", ".vscode", ".cache", "site-packages",
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
    if not root.exists():
        return files
    stack = [(root, 0)]
    while stack and len(files) < max_files:
        cur, depth = stack.pop()
        try:
            entries = sorted(cur.iterdir(), key=lambda p: (p.is_dir(), p.name))
        except (PermissionError, OSError):
            continue
        for entry in entries:
            rel = str(entry.relative_to(root)).replace("\\", "/")
            if entry.is_dir():
                if entry.name not in SKIP_DIRS and depth < 5:
                    stack.append((entry, depth + 1))
            else:
                files.append(rel)
    return files


def _read_chunk(path: Path, limit: int = 8000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
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


def _build_material(root: Path, files: List[str], scope: Dict[str, bool]) -> str:
    parts: List[str] = []
    by_ext: Dict[str, int] = {}
    for f in files:
        ext = f.rsplit(".", 1)[-1].lower() if "." in f.rsplit("/", 1)[-1] else "(noext)"
        by_ext[ext] = by_ext.get(ext, 0) + 1
    ext_line = ", ".join(f"{k}:{v}" for k, v in sorted(by_ext.items(), key=lambda x: -x[1])[:12])
    parts.append(f"### 檔案結構（共 {len(files)} 檔）\n頂層：{', '.join(sorted({f.split('/')[0] for f in files}))[:300]}\n副檔名分布：{ext_line}")

    if scope.get("readme"):
        for name in README_NAMES:
            chunk = _read_chunk(root / name)
            if chunk:
                parts.append(f"### {name}\n{chunk}")
                break
    if scope.get("deps"):
        for name in DEP_MANIFESTS:
            chunk = _read_chunk(root / name, limit=4000)
            if chunk:
                parts.append(f"### {name}\n{chunk}")
    if scope.get("git") and (root / ".git").exists():
        log = _git_log(root)
        if log:
            parts.append(f"### git 近期提交\n{log}")
    return "\n\n".join(parts)


def _fingerprint_version(files: List[str], root: Path) -> str:
    h = hashlib.sha1()
    for f in files:
        h.update(f.encode("utf-8", errors="replace"))
    for name in DEP_MANIFESTS + README_NAMES:
        p = root / name
        if p.exists():
            h.update(f"{name}:{int(p.stat().st_mtime)}".encode())
    return h.hexdigest()[:16]


async def scan_target(target: Dict[str, Any]) -> Dict[str, Any]:
    """Scan one watch target: risk check (always, filenames only) + fingerprint refresh."""
    tid = target["id"]
    root = Path(target["path"])
    scope = target["read_scope"]
    consent = target["outbound_consent"]
    now_iso = datetime.now(timezone.utc).isoformat()
    result: Dict[str, Any] = {"target_id": tid, "ok": False, "risk_proposal": False,
                              "fingerprint_updated": False}

    if not root.exists():
        result["error"] = f"path not found: {root}"
        update_watch_target(tid, {"last_scan_at": now_iso})
        return result
    if not scope.get("filenames"):
        result["error"] = "read_scope.filenames is off — nothing OmniKeep may look at"
        return result

    files = _walk_files(root)

    # 1) L0 risk scan — filenames only, pure local, no LLM needed
    risky = find_risky_files(files)
    if risky and target["target_type"] in ("folder", "desktop_risk"):
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        shown = ", ".join(risky[:8]) + ("…" if len(risky) > 8 else "")
        item_id = save_item({
            "url": f"proposal://risk/{tid}/{day}",
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
        })
        saved = save_proposal({
            "item_id": item_id, "target_id": tid, "proposal_type": "risk",
            "impact": 8.0, "confidence": 9.0, "effort": 2.0,
            "dedup_key": f"risk:{tid}:{day}",
        })
        result["risk_proposal"] = saved is not None

    # 2) Fingerprint refresh — skip Agnes when nothing changed
    version = _fingerprint_version(files, root)
    if version == target.get("fingerprint_version"):
        update_watch_target(tid, {"last_scan_at": now_iso, "fingerprint_version": version})
        result.update(ok=True, changed=False, file_count=len(files))
        return result

    material = _build_material(root, files, scope)
    outbound_parts = []
    if consent.get("summary"):
        outbound_parts.append(material)  # assembled per read scope; redacted below
    send_text = redact_text("\n\n".join(outbound_parts))[:12000]

    fp: Dict[str, Any]
    if send_text:
        try:
            provider = get_primary_provider()
            fp = await provider.generate_json(
                f"專案名稱：{target['name']}\n路徑：{root.name}\n\n{send_text}",
                FINGERPRINT_SYSTEM_PROMPT,
            )
        except Exception as e:  # LLM down → degrade to local-only fingerprint
            fp = {"_fallback": str(e)}
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

    item_id = save_item({
        "url": f"watch://{tid}",
        "source_type": "watch",
        "origin": "watch",
        "category_name": "監看",
        "title_l1": title,
        "summary_l1": summary,
        "tech_tags": tags if isinstance(tags, list) else [tags],
        "deep_analysis": deep,
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
