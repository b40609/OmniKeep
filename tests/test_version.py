"""The repo-root VERSION file is the only place the version is written; everything else follows it."""
import json
import re
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import app as app_package
from app.main import app

REPO = Path(__file__).resolve().parents[1]
VERSION = (REPO / "VERSION").read_text(encoding="utf-8").strip()


def test_version_file_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", VERSION)


def test_backend_reports_the_version_file():
    assert app_package.__version__ == VERSION
    assert app.openapi()["info"]["version"] == VERSION
    with TestClient(app) as client:
        assert client.get("/health").json()["version"] == VERSION


def test_frontend_writes_no_second_version():
    # frontend/package.json is private; npm makes "version" optional for unpublished packages.
    package = json.loads((REPO / "frontend/package.json").read_text(encoding="utf-8"))
    lock = json.loads((REPO / "frontend/package-lock.json").read_text(encoding="utf-8"))
    assert "version" not in package
    assert "version" not in lock and "version" not in lock["packages"][""]


def test_settings_menu_shows_the_injected_version():
    # The version sits at the foot of the menu behind the avatar in the top bar.
    menu = (REPO / "frontend/src/components/layout/AccountMenu.vue").read_text(encoding="utf-8")
    config = (REPO / "frontend/vite.config.ts").read_text(encoding="utf-8")
    assert "__APP_VERSION__" in menu and not re.search(r"\bv?\d+\.\d+\.\d+", menu)
    assert "'../VERSION'" in config and "__APP_VERSION__" in config


@pytest.mark.skipif(not (REPO / "static/dist/index.html").is_file(), reason="frontend not built")
def test_current_build_carries_the_version_file():
    html = (REPO / "static/dist/index.html").read_text(encoding="utf-8")
    entry = re.search(r'/static/dist/(assets/index-[\w-]+\.js)', html).group(1)
    bundle = (REPO / "static/dist" / entry).read_text(encoding="utf-8")
    # The minifier may quote the injected string with ", ' or `.
    assert re.search(rf"[\"'`]{re.escape(VERSION)}[\"'`]", bundle), "rebuild the frontend after changing VERSION"
