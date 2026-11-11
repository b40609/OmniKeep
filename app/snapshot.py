"""
OmniKeep Monolith HTML Snapshot Engine (Link-Rot Protection).
Preserves standalone offline HTML snapshots of web articles and high-value radar items.
Karakeep/Hoarder pattern: Ensures second-brain trust even when source pages vanish.

A saved page is untrusted content. It is cleaned before it is written, served with
headers that forbid scripts (SNAPSHOT_HEADERS), and the web app shows it only inside
a sandboxed frame, so nothing in it runs under OmniKeep's own address.
"""

import html
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from bs4.element import PreformattedString, Tag

from app.config import settings

logger = logging.getLogger("omnikeep.snapshot")

# The item id is the snapshot's file name, so it must not be able to name any other file.
_ITEM_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")

# Elements that run code, or load another document or a plug-in.
_REMOVED_TAGS = ("script", "noscript", "iframe", "frame", "frameset", "object", "embed",
                 "applet", "portal", "fencedframe")
# <meta http-equiv> values that act on the page. The source site's own policy goes too:
# it names that site's address, which a saved copy never has.
_REMOVED_HTTP_EQUIV = {"refresh", "set-cookie", "content-security-policy",
                       "content-security-policy-report-only"}
# SVG animation can point a link at a javascript: address after the page has loaded.
_ANIMATION_TAGS = ("animate", "set", "animatetransform", "animatemotion")
_URL_ATTRS = {"href", "src", "action", "xlink:href", "data", "poster", "background"}
# With the forms gone a button's own target has nothing to send; `ping` reports every click.
_DROPPED_ATTRS = {"srcdoc", "formaction", "ping"}
_SCRIPT_URL = ("javascript:", "vbscript:", "data:text/html", "data:application/xhtml+xml")
# A "<" that would open a tag, comment or declaration if the CSS were read as markup,
# which a browser does inside <svg> and <math>.
_MARKUP_IN_CSS = re.compile(r"<(?=[A-Za-z/!?])")

# Kept in the page itself, so it also holds when the file is opened from disk or a backup.
# A policy in <meta> cannot carry `sandbox`; SNAPSHOT_HEADERS and the app's frame do that.
_META_POLICY = "script-src 'none'; object-src 'none'; frame-src 'none'; form-action 'none'"

# For the API response: a unique origin with scripts off, and nothing loaded but
# images, styles, fonts and media.
SNAPSHOT_HEADERS = {
    "Content-Security-Policy": (
        "sandbox; default-src 'none'; img-src * data:; style-src * 'unsafe-inline'; "
        "font-src * data:; media-src *; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
}


def _get_snapshot_dir() -> Path:
    p = Path(settings.SNAPSHOT_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _snapshot_path(item_id: Any) -> Optional[Path]:
    """Where an item's snapshot is kept; None for an id that could name another file."""
    if not isinstance(item_id, (str, int)) or not _ITEM_ID.fullmatch(str(item_id)):
        return None
    return _get_snapshot_dir() / f"{item_id}.html"


def _http_url(url: str) -> str:
    """The address when it is a web address, else empty."""
    try:
        return url if urlsplit(url).scheme.lower() in ("http", "https") else ""
    except ValueError:
        return ""


def _runs_script(value: Any) -> bool:
    """True for an address a browser would run or open as a page of its own making."""
    text = value if isinstance(value, str) else " ".join(value or ())
    # Browsers skip leading control characters and spaces, and tabs and newlines anywhere.
    return re.sub(r"[\x00-\x20]+", "", text).lower().startswith(_SCRIPT_URL)


def _inert_css(css: str) -> str:
    """Style text with nothing left in it that a browser could read as markup."""
    # Wrappers older pages and SVG exports put around CSS; a browser skips them.
    for wrapper in ("<![CDATA[", "]]>", "<!--", "-->"):
        css = css.replace(wrapper, "")
    return _MARKUP_IN_CSS.sub(r"\\3c ", css)


def _leading_element(parent: Tag) -> Optional[Tag]:
    """The first element in `parent`; None when text comes before it or there is none."""
    for node in parent.contents:
        if isinstance(node, Tag):
            return node
        if str(node).strip("﻿ \t\r\n\f"):
            return None
    return None


def _document_head(soup: BeautifulSoup) -> Optional[Tag]:
    """The <head> a browser will use, added when the page has none.

    None when the page does not open with <html>: a browser has then already started the
    body, and a <head> found later is not one any more.
    """
    root = _leading_element(soup)
    if root is None or root.name != "html":
        return None
    first = _leading_element(root)
    if first is not None and first.name == "head":
        return first
    head = soup.new_tag("head")
    root.insert(0, head)
    return head


def _sanitize_and_inline_html(html_text: str, source_url: str) -> str:
    """Clean a fetched page for keeping and add the snapshot provenance banner.

    Nothing in the result runs code, loads another document or a plug-in, or sends what
    the reader types anywhere; text, images and styles stay.
    """
    if not html_text:
        return ""

    soup = BeautifulSoup(html_text, "html.parser")
    shown_url = html.escape((source_url or "")[:70])
    source_url = _http_url(source_url or "")  # only a web address becomes a link or the base

    # Comments, CDATA sections, declarations and the doctype are written back exactly as
    # read. A browser can end one earlier than this parser did and read the rest as markup.
    for node in [n for n in soup.descendants if isinstance(n, PreformattedString)]:
        node.extract()

    for tag in soup(_REMOVED_TAGS):
        tag.decompose()
    for tag in soup.find_all("meta"):
        if str(tag.get("http-equiv") or "").strip().lower() in _REMOVED_HTTP_EQUIV:
            tag.decompose()
    for tag in soup.find_all(_ANIMATION_TAGS):
        if str(tag.get("attributename") or "").strip().lower() in ("href", "xlink:href"):
            tag.decompose()
    # A form can send what the reader types to another site; its text and fields stay.
    for form in soup.find_all("form"):
        form.unwrap()
    # Style text is written back as it is, too.
    for style in soup.find_all("style"):
        style.string = _inert_css(style.get_text())

    # Remove inline event attributes (e.g. onclick, onload, onerror) and script addresses
    for element in soup.find_all(True):
        element.attrs = {
            k: v for k, v in element.attrs.items()
            if not k.lower().startswith("on")
            and k.lower() not in _DROPPED_ATTRS
            and not (k.lower() in _URL_ATTRS and _runs_script(v))
        }

    # One absolute <base>, so relative links and images lead to the source site and never
    # to the address the snapshot is shown under.
    page_base = next((b["href"] for b in soup.find_all("base") if b.get("href")), "")
    base_href = _http_url(urljoin(source_url, page_base)) if page_base else source_url
    for tag in soup.find_all("base") + soup.find_all("meta", attrs={"charset": True}):
        tag.decompose()

    head = _document_head(soup)
    if head is None:
        wrapper = BeautifulSoup("<html><head></head><body></body></html>", "html.parser")
        wrapper.body.append(soup)
        soup = wrapper
        head = soup.head

    # First in <head>: the policy and the base only cover what comes after them.
    lead = [
        soup.new_tag("meta", attrs={"charset": "utf-8"}),
        soup.new_tag("meta", attrs={"http-equiv": "Content-Security-Policy", "content": _META_POLICY}),
    ]
    if base_href:
        lead.append(soup.new_tag("base", attrs={"href": base_href}))
    for position, tag in enumerate(lead):
        head.insert(position, tag)

    # Provenance banner styling and element
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    source_link = (
        f'<a href="{html.escape(source_url)}" target="_blank" rel="noopener noreferrer" '
        f'style="color: #60a5fa; text-decoration: underline;">{shown_url}</a>'
        if source_url else shown_url
    )
    banner_html = f"""
    <div id="omnikeep-snapshot-banner" style="
        position: sticky; top: 0; left: 0; right: 0; z-index: 999999;
        background: #0f172a; color: #f8fafc; font-family: system-ui, -apple-system, sans-serif;
        font-size: 12px; padding: 8px 16px; display: flex; justify-content: space-between;
        align-items: center; border-bottom: 2px solid #3b82f6; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
    ">
        <div>
            <b>💾 OmniKeep 本地整頁快照存檔</b>
            <span style="margin-left: 10px; color: #94a3b8;">來源：{source_link}</span>
        </div>
        <div style="color: #94a3b8;">存檔時間：{now_str}</div>
    </div>
    """
    banner_soup = BeautifulSoup(banner_html, "html.parser")
    if soup.body:
        soup.body.insert(0, banner_soup)

    return "<!DOCTYPE html>\n" + str(soup)


def save_html_snapshot(item_id: str, raw_html: str, url: str) -> Optional[str]:
    """Saves a standalone sanitized HTML snapshot to the snapshot storage directory."""
    if not raw_html or not item_id:
        return None
    file_path = _snapshot_path(item_id)
    if file_path is None:
        logger.warning("[Snapshot] Refused an item id that is not a file name")
        return None

    clean_html = _sanitize_and_inline_html(raw_html, url)

    try:
        file_path.write_text(clean_html, encoding="utf-8")
        return str(file_path.resolve())
    except OSError as e:
        logger.warning(f"[Snapshot] Failed to write snapshot for {item_id}: {e}")
        return None


def get_html_snapshot(item_id: str) -> Optional[str]:
    """Reads the stored snapshot for an item."""
    file_path = _snapshot_path(item_id)
    if file_path is None or not file_path.is_file():
        return None
    try:
        return file_path.read_text(encoding="utf-8")
    except OSError:
        return None


def get_snapshot_for_response(item_id: str) -> Optional[Tuple[str, Dict[str, str]]]:
    """The stored snapshot with the headers it has to be served with; None when there is none.

    Snapshots saved before the cleaning above was tightened are still on disk, so the
    headers, not the stored HTML, are what keeps a response from running anything.
    """
    content = get_html_snapshot(item_id)
    if not content:
        return None
    return content, dict(SNAPSHOT_HEADERS)


def has_html_snapshot(item_id: str) -> bool:
    """Checks whether an item has a saved snapshot."""
    file_path = _snapshot_path(item_id)
    return file_path is not None and file_path.is_file()


def get_snapshot_info(item_id: str) -> Dict[str, Any]:
    """Returns metadata about the snapshot (never where it is on the server's disk)."""
    file_path = _snapshot_path(item_id)
    if file_path is None or not file_path.is_file():
        return {"has_snapshot": False, "size_bytes": 0}
    try:
        stat = file_path.stat()
        return {
            "has_snapshot": True,
            "size_bytes": stat.st_size,
            "mtime": stat.st_mtime
        }
    except OSError:
        return {"has_snapshot": False, "size_bytes": 0}
