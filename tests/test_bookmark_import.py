import os
import json
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.config import settings
from app.parsers.bookmarks import (
    parse_netscape_html,
    parse_json_bookmarks,
    parse_csv_bookmarks,
    parse_bookmarks,
)
from app.database import get_item_by_id, get_db_connection


SAMPLE_NETSCAPE_HTML = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file. -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1609459200">AI Research</H3>
    <DL><p>
        <DT><A HREF="https://arxiv.org/abs/2301.00001" ADD_DATE="1672531200" TAGS="deep-learning,llm">Attention Is All You Need Revisited</A>
        <DT><A HREF="https://huggingface.co/papers" ADD_DATE="1672531300">Daily Papers - Hugging Face</A>
    </DL><p>
    <DT><H3 ADD_DATE="1609459200">System Architecture</H3>
    <DL><p>
        <DT><A HREF="https://github.com/rust-lang/rust" TAGS="rust,systems">Rust Programming Language</A>
    </DL><p>
    <DT><A HREF="javascript:alert(1)">Invalid Link</A>
    <DT><A HREF="https://127.0.0.1/admin">Private Network SSRF Link</A>
</DL><p>
"""

SAMPLE_CHROME_JSON = {
    "roots": {
        "bookmark_bar": {
            "name": "書籤列",
            "type": "folder",
            "children": [
                {
                    "name": "FastAPI Framework",
                    "type": "url",
                    "url": "https://fastapi.tiangolo.com/",
                    "date_added": "13253760000000000",
                },
                {
                    "name": "Dev Tools",
                    "type": "folder",
                    "children": [
                        {
                            "name": "Docker Docs",
                            "type": "url",
                            "url": "https://docs.docker.com/",
                        }
                    ],
                },
            ],
        }
    }
}

SAMPLE_CSV = """url,title,tags,folder
https://news.ycombinator.com,Hacker News,tech;news,Tech News
https://github.com/trending,GitHub Trending,dev;open-source,Developer
"""


def test_parse_netscape_html():
    results = parse_netscape_html(SAMPLE_NETSCAPE_HTML)
    assert len(results) == 4
    
    arxiv = next(r for r in results if "arxiv.org" in r["url"])
    assert arxiv["title"] == "Attention Is All You Need Revisited"
    assert "deep-learning" in arxiv["tags"]
    assert "AI Research" in arxiv["tags"]
    assert arxiv["folder"] == "AI Research"
    assert arxiv["created_at"] is not None

    rust = next(r for r in results if "github.com/rust-lang" in r["url"])
    assert "rust" in rust["tags"]
    assert "System Architecture" in rust["tags"]


def test_parse_json_bookmarks():
    results = parse_json_bookmarks(SAMPLE_CHROME_JSON)
    assert len(results) == 2
    
    fastapi = next(r for r in results if "fastapi.tiangolo.com" in r["url"])
    assert fastapi["title"] == "FastAPI Framework"
    assert "書籤列" in fastapi["tags"]

    docker = next(r for r in results if "docs.docker.com" in r["url"])
    assert "Dev Tools" in docker["folder"]
    assert "Dev Tools" in docker["tags"]


def test_parse_csv_bookmarks():
    results = parse_csv_bookmarks(SAMPLE_CSV)
    assert len(results) == 2
    hn = results[0]
    assert hn["url"] == "https://news.ycombinator.com"
    assert hn["title"] == "Hacker News"
    assert "Tech News" in hn["tags"]


def test_auto_detect_format():
    # Detect HTML
    assert len(parse_bookmarks(SAMPLE_NETSCAPE_HTML)) == 4
    # Detect JSON
    assert len(parse_bookmarks(json.dumps(SAMPLE_CHROME_JSON))) == 2
    # Detect CSV
    assert len(parse_bookmarks(SAMPLE_CSV, filename="bookmarks.csv")) == 2


def test_import_bookmarks_api_endpoint():
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.API_KEY}"}

    # Test fast import (0 LLM cost) with SSRF filtering
    resp = client.post(
        "/api/items/import/bookmarks",
        headers=headers,
        json={"content": SAMPLE_NETSCAPE_HTML, "filename": "bookmarks.html", "enqueue_ai": False},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["total_parsed"] == 4
    # Note: https://127.0.0.1/admin should be blocked by is_safe_url
    assert data["imported_count"] == 3
    assert data["skipped_count"] == 1
    assert len(data["sample_ids"]) == 3

    # Verify item was correctly stored in database
    first_id = data["sample_ids"][0]
    item = get_item_by_id(first_id)
    assert item is not None
    assert item["origin"] == "import"


def test_import_bookmarks_enqueue_ai():
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {settings.API_KEY}"}

    # Test enqueueing to persistent SQLite queue
    resp = client.post(
        "/api/items/import/bookmarks",
        headers=headers,
        json={"content": json.dumps(SAMPLE_CHROME_JSON), "filename": "bookmarks.json", "enqueue_ai": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["total_parsed"] == 2
    assert data["queued_count"] == 2
    assert data["imported_count"] == 0

