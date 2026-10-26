"""
OmniKeep Monolith HTML Snapshot Engine (Link-Rot Protection).
Preserves standalone offline HTML snapshots of web articles and high-value radar items.
Karakeep/Hoarder pattern: Ensures second-brain trust even when source pages vanish.
"""

import html
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any
from bs4 import BeautifulSoup

from app.config import settings


def _get_snapshot_dir() -> Path:
    p = Path(settings.SNAPSHOT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _sanitize_and_inline_html(html_text: str, source_url: str) -> str:
    """Sanitize scripts and inject snapshot provenance banner."""
    if not html_text:
        return ""

    soup = BeautifulSoup(html_text, "html.parser")

    # Remove dangerous or tracking scripts and external script tags
    for tag in soup(["script", "noscript"]):
        tag.decompose()

    # Remove inline event attributes (e.g. onclick, onload, onerror)
    for element in soup.find_all(True):
        element.attrs = {
            k: v for k, v in element.attrs.items()
            if not k.lower().startswith("on")
        }

    # Ensure <head> and base href for asset resolution
    if not soup.head:
        if soup.html:
            head = soup.new_tag("head")
            soup.html.insert(0, head)
        else:
            wrapper = BeautifulSoup("<!DOCTYPE html><html><head></head><body></body></html>", "html.parser")
            wrapper.body.append(soup)
            soup = wrapper

    # Ensure UTF-8 meta
    if not soup.find("meta", attrs={"charset": True}):
        meta = soup.new_tag("meta", attrs={"charset": "utf-8"})
        soup.head.insert(0, meta)

    # Inset base href if not already present
    if not soup.find("base"):
        base_tag = soup.new_tag("base", attrs={"href": source_url})
        soup.head.append(base_tag)

    # Provenance banner styling and element
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    banner_html = f"""
    <div id="omnikeep-snapshot-banner" style="
        position: sticky; top: 0; left: 0; right: 0; z-index: 999999;
        background: #0f172a; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif;
        font-size: 12px; padding: 8px 16px; display: flex; justify-content: space-between;
        align-items: center; border-bottom: 2px solid #3b82f6; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    ">
        <div>
            <b>💾 OmniKeep 本地整頁快照存檔</b>
            <span style="margin-left: 10px; color: #94a3b8;">來源：<a href="{html.escape(source_url)}" target="_blank" style="color: #60a5fa; text-decoration: underline;">{html.escape(source_url[:70])}</a></span>
        </div>
        <div style="color: #94a3b8;">存檔時間：{now_str}</div>
    </div>
    """
    banner_soup = BeautifulSoup(banner_html, "html.parser")
    if soup.body:
        soup.body.insert(0, banner_soup)

    return str(soup)


def save_html_snapshot(item_id: str, raw_html: str, url: str) -> Optional[str]:
    """Saves a standalone sanitized HTML snapshot to the snapshot storage directory."""
    if not raw_html or not item_id:
        return None

    clean_html = _sanitize_and_inline_html(raw_html, url)
    snap_dir = _get_snapshot_dir()
    file_path = snap_dir / f"{item_id}.html"

    try:
        file_path.write_text(clean_html, encoding="utf-8")
        return str(file_path.resolve())
    except OSError as e:
        print(f"[Snapshot] Failed to write snapshot for {item_id}: {e}")
        return None


def get_html_snapshot(item_id: str) -> Optional[str]:
    """Reads the stored snapshot for an item."""
    snap_dir = _get_snapshot_dir()
    file_path = snap_dir / f"{item_id}.html"
    if not file_path.is_file():
        return None
    try:
        return file_path.read_text(encoding="utf-8")
    except OSError:
        return None


def has_html_snapshot(item_id: str) -> bool:
    """Checks whether an item has a saved snapshot."""
    snap_dir = _get_snapshot_dir()
    return (snap_dir / f"{item_id}.html").is_file()


def get_snapshot_info(item_id: str) -> Dict[str, Any]:
    """Returns metadata about the snapshot."""
    snap_dir = _get_snapshot_dir()
    file_path = snap_dir / f"{item_id}.html"
    if not file_path.is_file():
        return {"has_snapshot": False, "size_bytes": 0, "path": ""}
    try:
        stat = file_path.stat()
        return {
            "has_snapshot": True,
            "size_bytes": stat.st_size,
            "path": str(file_path.resolve()),
            "mtime": stat.st_mtime
        }
    except OSError:
        return {"has_snapshot": False, "size_bytes": 0, "path": ""}
