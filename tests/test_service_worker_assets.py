"""The Workbox runtime that sw.js loads must pass the static allowlist, or the service worker never installs."""
from pathlib import Path
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.static_assets import CurrentBuildFiles

REPO_STATIC = Path(__file__).resolve().parents[1] / "static"


def _serve(root):
    test_app = FastAPI()
    test_app.mount("/static", CurrentBuildFiles(directory=root))
    return TestClient(test_app)


def test_runtime_referenced_without_extension_is_served(isolated_runtime):
    root = isolated_runtime / "static"
    (root / "dist").mkdir(parents=True)
    (root / "dist/index.html").write_text("<html></html>")
    # Shape of vite-plugin-pwa generateSW output: the runtime is named without ".js".
    (root / "dist/sw.js").write_text(
        'if(!self.define){/* loader appends ".js" */}define(["./workbox-f51bf729"],function(e){})')
    (root / "dist/workbox-f51bf729.js").write_text("// synthetic runtime")
    (root / "dist/workbox-0ld0ld00.js").write_text("// stale runtime from an older build")
    with _serve(root) as client:
        assert client.get("/static/dist/workbox-f51bf729.js").status_code == 200
        assert client.get("/static/dist/workbox-0ld0ld00.js").status_code == 404


def test_runtime_referenced_with_extension_is_still_served(isolated_runtime):
    root = isolated_runtime / "static"
    (root / "dist").mkdir(parents=True)
    (root / "dist/sw.js").write_text('importScripts("workbox-abc123.js")')
    (root / "dist/workbox-abc123.js").write_text("// synthetic runtime")
    with _serve(root) as client:
        assert client.get("/static/dist/workbox-abc123.js").status_code == 200


@pytest.mark.skipif(not (REPO_STATIC / "dist/sw.js").is_file(), reason="frontend not built")
def test_current_build_serves_every_runtime_its_worker_loads():
    worker = (REPO_STATIC / "dist/sw.js").read_text(encoding="utf-8")
    runtimes = set(re.findall(r'workbox-[\w-]+', worker))
    assert runtimes
    with _serve(REPO_STATIC) as client:
        for name in runtimes:
            assert client.get(f"/static/dist/{name}.js").status_code == 200, name
