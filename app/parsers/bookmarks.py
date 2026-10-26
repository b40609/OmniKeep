"""Bookmark and Archive Importer (Netscape HTML, Chrome/Pocket JSON, CSV).

Supports:
- Netscape Bookmark HTML format (Chrome, Edge, Firefox, Safari, Arc, Pocket, Raindrop, Karakeep)
- Chrome / Edge Bookmark JSON format & Raindrop / Hoarder export JSON
- Universal CSV Bookmark format
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from app.network import is_safe_url


class NetscapeBookmarkParser(HTMLParser):
    """Zero-dependency streaming parser for Netscape Bookmark HTML files."""

    def __init__(self) -> None:
        super().__init__()
        self.folder_stack: List[str] = []
        self.bookmarks: List[Dict[str, Any]] = []
        self._in_h3 = False
        self._current_h3_text: List[str] = []
        self._current_a_attrs: Optional[Dict[str, str]] = None
        self._current_a_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        tag_lower = tag.lower()
        attr_dict = {k.lower(): (v or "") for k, v in attrs}

        if tag_lower == "h3":
            self._in_h3 = True
            self._current_h3_text = []
        elif tag_lower == "a":
            self._current_a_attrs = attr_dict
            self._current_a_text = []
        elif tag_lower == "dl":
            # If we recently passed an H3 folder name, push it to stack
            if self._current_h3_text:
                folder_name = "".join(self._current_h3_text).strip()
                if folder_name:
                    self.folder_stack.append(folder_name)
                self._current_h3_text = []

    def handle_endtag(self, tag: str) -> None:
        tag_lower = tag.lower()
        if tag_lower == "h3":
            self._in_h3 = False
        elif tag_lower == "dl":
            if self.folder_stack:
                self.folder_stack.pop()
        elif tag_lower == "a":
            if self._current_a_attrs:
                href = self._current_a_attrs.get("href", "").strip()
                title = "".join(self._current_a_text).strip()
                tags_attr = self._current_a_attrs.get("tags", "")
                add_date_attr = self._current_a_attrs.get("add_date", "")

                tags: List[str] = []
                if tags_attr:
                    tags.extend([t.strip() for t in tags_attr.split(",") if t.strip()])
                if self.folder_stack:
                    # Inherit folder path as tags
                    tags.extend([f.strip() for f in self.folder_stack if f.strip()])

                # Deduplicate tags preserving order
                unique_tags = list(dict.fromkeys(tags))

                created_at = None
                if add_date_attr:
                    try:
                        ts = float(add_date_attr)
                        # Detect microseconds/nanoseconds timestamp
                        if ts > 10_000_000_000:
                            ts = ts / 1_000_000
                        created_at = datetime.fromtimestamp(ts, timezone.utc).isoformat()
                    except (ValueError, OSError, OverflowError):
                        created_at = None

                if href and href.lower().startswith(("http://", "https://")):
                    self.bookmarks.append({
                        "url": href,
                        "title": title or href,
                        "tags": unique_tags,
                        "folder": " / ".join(self.folder_stack) if self.folder_stack else "Bookmarks",
                        "created_at": created_at,
                    })

                self._current_a_attrs = None
                self._current_a_text = []

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._current_h3_text.append(data)
        elif self._current_a_attrs is not None:
            self._current_a_text.append(data)


def parse_netscape_html(html_text: str) -> List[Dict[str, Any]]:
    parser = NetscapeBookmarkParser()
    try:
        parser.feed(html_text)
    except Exception:
        pass
    return parser.bookmarks


def _traverse_chrome_node(node: Dict[str, Any], folder_path: List[str], results: List[Dict[str, Any]]) -> None:
    node_type = node.get("type")
    name = (node.get("name") or "").strip()
    if node_type == "folder":
        new_path = folder_path + ([name] if name else [])
        for child in node.get("children", []):
            if isinstance(child, dict):
                _traverse_chrome_node(child, new_path, results)
    elif node_type == "url":
        url = (node.get("url") or "").strip()
        if url.lower().startswith(("http://", "https://")):
            date_added = node.get("date_added")
            created_at = None
            if date_added:
                try:
                    # Chrome stores time in microseconds since 1601-01-01
                    ts_us = int(date_added)
                    epoch_start = 11644473600  # seconds between 1601 and 1970
                    unix_ts = (ts_us / 1_000_000) - epoch_start
                    if 0 < unix_ts < 4_000_000_000:
                        created_at = datetime.fromtimestamp(unix_ts, timezone.utc).isoformat()
                except Exception:
                    created_at = None
            results.append({
                "url": url,
                "title": name or url,
                "tags": list(folder_path),
                "folder": " / ".join(folder_path) if folder_path else "Bookmarks",
                "created_at": created_at,
            })


def parse_json_bookmarks(raw_json: str | bytes | Dict[str, Any] | List[Any]) -> List[Dict[str, Any]]:
    if isinstance(raw_json, (str, bytes)):
        data = json.loads(raw_json)
    else:
        data = raw_json

    results: List[Dict[str, Any]] = []

    # 1. Chrome / Edge Bookmarks JSON structure
    if isinstance(data, dict) and "roots" in data:
        roots = data.get("roots", {})
        for root_key in ("bookmark_bar", "other", "synced"):
            root_node = roots.get(root_key)
            if isinstance(root_node, dict):
                _traverse_chrome_node(root_node, [root_node.get("name") or root_key], results)
        return results

    # 2. List of objects (Raindrop / Pocket / Hoarder / generic)
    items_list = []
    if isinstance(data, list):
        items_list = data
    elif isinstance(data, dict):
        for candidate_key in ("bookmarks", "items", "links", "data"):
            if isinstance(data.get(candidate_key), list):
                items_list = data[candidate_key]
                break

    for item in items_list:
        if not isinstance(item, dict):
            continue
        url = (item.get("url") or item.get("link") or item.get("href") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue

        title = (item.get("title") or item.get("name") or url).strip()
        tags_raw = item.get("tags") or item.get("labels") or []
        if isinstance(tags_raw, str):
            tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        elif isinstance(tags_raw, list):
            tags = [str(t).strip() for t in tags_raw if str(t).strip()]
        else:
            tags = []

        folder = (item.get("folder") or item.get("collection") or item.get("category") or "Bookmarks").strip()
        if folder and folder not in tags:
            tags.append(folder)

        created_at = item.get("created_at") or item.get("date") or item.get("time_added")
        if isinstance(created_at, (int, float)):
            try:
                created_at = datetime.fromtimestamp(created_at, timezone.utc).isoformat()
            except Exception:
                created_at = None

        results.append({
            "url": url,
            "title": title,
            "tags": list(dict.fromkeys(tags)),
            "folder": folder,
            "created_at": str(created_at) if created_at else None,
        })

    return results


def parse_csv_bookmarks(csv_text: str) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    reader = csv.DictReader(io.StringIO(csv_text.strip()))
    for row in reader:
        # Normalize keys to lower
        normalized = {k.lower().strip(): v for k, v in row.items() if k}
        url = (
            normalized.get("url")
            or normalized.get("link")
            or normalized.get("href")
            or normalized.get("address")
            or ""
        ).strip()
        if not url.lower().startswith(("http://", "https://")):
            continue

        title = (
            normalized.get("title")
            or normalized.get("name")
            or normalized.get("label")
            or url
        ).strip()

        tags_raw = normalized.get("tags") or normalized.get("labels") or ""
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]

        folder = (
            normalized.get("folder")
            or normalized.get("category")
            or normalized.get("collection")
            or "Bookmarks"
        ).strip()
        if folder and folder not in tags:
            tags.append(folder)

        created_at = normalized.get("created_at") or normalized.get("date") or None

        results.append({
            "url": url,
            "title": title,
            "tags": list(dict.fromkeys(tags)),
            "folder": folder,
            "created_at": created_at,
        })

    return results


def parse_bookmarks(content: str | bytes, filename: str = "") -> List[Dict[str, Any]]:
    """Automatically detect format (Netscape HTML, Chrome/Raindrop JSON, CSV) and parse bookmarks."""
    if isinstance(content, bytes):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            text = content.decode("latin-1", errors="replace")
    else:
        text = content

    text_stripped = text.strip()
    fn_lower = filename.lower()

    # 1. JSON
    if fn_lower.endswith(".json") or text_stripped.startswith(("{", "[")):
        try:
            return parse_json_bookmarks(text_stripped)
        except Exception:
            pass

    # 2. Netscape HTML
    if (
        "<!DOCTYPE NETSCAPE-Bookmark-file-1>" in text.upper()
        or "<DL>" in text.upper()
        or "<H3" in text.upper()
        or fn_lower.endswith((".html", ".htm"))
    ):
        parsed = parse_netscape_html(text)
        if parsed:
            return parsed

    # 3. CSV
    if fn_lower.endswith(".csv") or ("url" in text.split("\n", 1)[0].lower() and "," in text):
        try:
            parsed = parse_csv_bookmarks(text)
            if parsed:
                return parsed
        except Exception:
            pass

    # Fallback to Netscape parser in case of partial HTML snippet
    return parse_netscape_html(text)
