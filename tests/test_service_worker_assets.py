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


@pytest.mark.skipif(not (REPO_STATIC / "dist/sw.js").is_file(), reason="frontend not built")
def test_current_build_serves_every_file_its_worker_precaches():
    # One 404 in the precache list and the service worker never installs.
    worker = (REPO_STATIC / "dist/sw.js").read_text(encoding="utf-8")
    urls = set(re.findall(r'url:"([^"]+)"', worker))
    assert "index.html" in urls
    with _serve(REPO_STATIC) as client:
        for url in sorted(urls):
            assert client.get(f"/static/dist/{url}").status_code == 200, url


def test_chunks_the_entry_imports_later_are_served(isolated_runtime):
    # Vite splits mermaid (deep analysis flowcharts) into chunks the entry loads with import().
    root = isolated_runtime / "static"
    (root / "dist/assets").mkdir(parents=True)
    (root / "dist/index.html").write_text('<script type="module" src="/static/dist/assets/index-AbCd1234.js"></script>')
    (root / "dist/assets/index-AbCd1234.js").write_text('const m=()=>import("./mermaid.core-Xy_z9876.js")')
    (root / "dist/assets/mermaid.core-Xy_z9876.js").write_text('import{a}from"./chunk-Q1RSTUVW-Ab3dE-9x.js"')
    (root / "dist/assets/chunk-Q1RSTUVW-Ab3dE-9x.js").write_text("export const a=1")
    (root / "dist/assets/old-Zz999999.js").write_text("// left by an older build")
    with _serve(root) as client:
        assert client.get("/static/dist/assets/mermaid.core-Xy_z9876.js").status_code == 200
        assert client.get("/static/dist/assets/chunk-Q1RSTUVW-Ab3dE-9x.js").status_code == 200
        assert client.get("/static/dist/assets/old-Zz999999.js").status_code == 404
