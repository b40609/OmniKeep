"""A deeper architecture diagram drawn by the user's own coding agent (Archify), kept with the item.

The deep analysis draws its own diagram from the README, the file list and a few core files
(app/arch_block.py). For a project the user wants to study, the reader offers a prompt for their
agent (Claude Code, Codex, Antigravity): clone the repository, run the Archify skill
(github.com/tt-a1i/archify, Apache-2.0), which reads the code and checks every component against it,
then hand the HTML back through the MCP tool attach_item_diagram or PUT /api/items/{id}/diagram.

The page is the agent's output, so it is treated like a saved web page (app/snapshot.py): it is
kept as a file, and the web app shows it only in a sandboxed frame with scripts allowed but no
same-origin access, so it cannot read OmniKeep's access key or call the API. A policy written into
the page also blocks every network request, so the page runs on what it carries and nothing leaves.
"""
from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any, Dict, Optional

from app.config import settings

MAX_BYTES = 8 * 1024 * 1024
_ITEM_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
# Inline scripts and styles only; no fetch, no outside script, image, font or frame.
PAGE_POLICY = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
               "img-src data: blob:; font-src data:; media-src data: blob:; connect-src 'none'; "
               "frame-src 'none'; form-action 'none'; base-uri 'none'")
_META = f'<meta http-equiv="Content-Security-Policy" content="{PAGE_POLICY}">'
# The frame's sandbox (frontend DeepDiagram.vue uses the same list). Popups, so a card's source link
# (a file and lines on GitHub, opened in a new tab) works; the new tab is an ordinary page with no
# opener, and the frame itself still has a unique origin and no network.
SANDBOX = "allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox"
# Served on its own (opened in a tab), the same rules come as a header with a unique origin.
DIAGRAM_HEADERS = {
    "Content-Security-Policy": f"sandbox {SANDBOX}; {PAGE_POLICY}",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}


class DiagramError(ValueError):
    """A page that cannot be kept; the message says why, in the user's words."""


def _dir() -> Path:
    p = Path(settings.SNAPSHOT_DIR) / "diagrams"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _path(item_id: Any) -> Optional[Path]:
    if not isinstance(item_id, (str, int)) or not _ITEM_ID.fullmatch(str(item_id)):
        return None
    return _dir() / f"{item_id}.html"


def with_policy(html: str) -> str:
    """The page with PAGE_POLICY as the first thing in its <head> (a policy only tightens, so one
    the page already has still holds too)."""
    m = re.search(r"<head\b[^>]*>", html, re.I)
    if m:
        return html[:m.end()] + _META + html[m.end():]
    m = re.search(r"<html\b[^>]*>", html, re.I)
    if m:
        return html[:m.end()] + f"<head>{_META}</head>" + html[m.end():]
    return f"<!doctype html><html><head>{_META}</head><body>{html}</body></html>"


def save_diagram(item_id: Any, html: str) -> Dict[str, Any]:
    from app.database import get_item_by_id
    path = _path(item_id)
    if not path or not get_item_by_id(str(item_id)):
        raise DiagramError("找不到這則收藏。")
    if not isinstance(html, str) or not html.strip():
        raise DiagramError("沒有收到架構圖的 HTML。")
    data = html.encode("utf-8")
    if len(data) > MAX_BYTES:
        raise DiagramError(f"架構圖太大（{len(data) // 1024 // 1024} MB），上限 {MAX_BYTES // 1024 // 1024} MB。")
    if not re.search(r"<(!doctype html|html|svg)\b", html[:4000], re.I):
        raise DiagramError("收到的內容不是 HTML 頁面。")
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return diagram_info(item_id)


def save_diagram_file(item_id: Any, file_path: str) -> Dict[str, Any]:
    """Keep the HTML file an agent wrote on this computer (MCP tool attach_item_diagram)."""
    p = Path(file_path or "").expanduser()
    if p.suffix.lower() not in (".html", ".htm"):
        raise DiagramError("只收 .html 檔。")
    if not p.is_file():
        raise DiagramError(f"找不到檔案：{file_path}")
    if p.stat().st_size > MAX_BYTES:
        raise DiagramError(f"架構圖太大，上限 {MAX_BYTES // 1024 // 1024} MB。")
    return save_diagram(item_id, p.read_text(encoding="utf-8", errors="replace"))


def diagram_info(item_id: Any) -> Dict[str, Any]:
    path = _path(item_id)
    if not path or not path.is_file():
        return {"has_diagram": False, "size_bytes": 0}
    st = path.stat()
    return {"has_diagram": True, "size_bytes": st.st_size, "mtime": int(st.st_mtime)}


def load_diagram(item_id: Any) -> Optional[str]:
    path = _path(item_id)
    if not path or not path.is_file():
        return None
    return with_policy(path.read_text(encoding="utf-8", errors="replace"))


def delete_diagram(item_id: Any) -> bool:
    path = _path(item_id)
    if not path or not path.is_file():
        return False
    path.unlink()
    return True


def agent_prompt(item: Dict[str, Any], base_url: str = "") -> str:
    """What the reader copies into the user's coding agent."""
    url = item.get("url") or ""
    item_id = item.get("id")
    stamp = time.strftime("%Y%m%d")
    api = f"{base_url.rstrip('/')}/api/items/{item_id}/diagram" if base_url else f"/api/items/{item_id}/diagram"
    return (
        f"請用 Archify 替這個 GitHub 專案畫一張讀過程式碼的系統架構圖，畫好存回 OmniKeep。\n\n"
        f"專案：{url}\n"
        f"OmniKeep 收藏 ID：{item_id}\n\n"
        "1. 還沒裝 Archify skill 就先裝：npx skills add tt-a1i/archify -g\n"
        f"2. 在系統暫存目錄（例如 Windows 的 %TEMP%、macOS／Linux 的 /tmp）開一個 archify-{item_id}-{stamp} 資料夾，"
        f"把專案淺複製進去（git clone --depth 1 {url} repo），只讀程式碼，不要執行專案裡的任何腳本或安裝它的套件。"
        "不要放在桌面、文件或 OneDrive／Dropbox 這類同步資料夾：同步程式會讓 Archify 的 finalize 以「檔案是硬連結」拒絕交付。\n"
        "3. 照 Archify 的 Repository authoring 說明畫 architecture 圖：主流程、主要元件與分支，每個元件附 repo 證據，"
        "candidate.json 與輸出的 HTML 也放在同一個暫存資料夾、從那裡執行 finalize，"
        "加上 --repo-root 指到剛剛的 repo 資料夾、--quality showcase，直到通過。"
        "meta.repository 加上 provider: \"github\"，來源連結才會指到 GitHub 網頁。說明文字用繁體中文（台灣用語）。\n"
        f"4. 把通過的 HTML 存回 OmniKeep：若這個 session 有 attach_item_diagram MCP 工具就直接呼叫 attach_item_diagram(item_id=\"{item_id}\", path=\"<HTML 的絕對路徑>\")；"
        f"本機為預設 core 精簡 MCP 時，改用專案 .venv 的 Python 執行 scripts/setup_cli.py attach-diagram \"{item_id}\" --path \"<HTML 的絕對路徑>\"（不需讀取金鑰）；"
        f"僅在遠端裝置無法存取本機目錄時，才請使用者自行以存取金鑰 PUT 到 {api}（Content-Type: text/html，agent 不可讀取 .env）。\n"
        "5. 完成後刪掉暫存的專案資料夾，回報元件數、有附證據的元件數，以及 finalize 的結果。"
    )
