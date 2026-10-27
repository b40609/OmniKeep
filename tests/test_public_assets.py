"""Public source assets must not distribute the developer's old credentials."""

import re
from pathlib import Path


def test_archived_mobile_test_requires_user_supplied_key():
    project = Path(__file__).resolve().parents[1]
    html = (project / "static/mobile_test.html").read_text(encoding="utf-8")
    assert 'id="api-key"' in html
    assert "function apiKey()" in html
    assert "?token=" not in html
    assert not re.search(r"const\s+API_KEY\s*=", html)
    assert not re.search(r"X-API-Key:\s*[a-zA-Z0-9_-]{8,}", html)

