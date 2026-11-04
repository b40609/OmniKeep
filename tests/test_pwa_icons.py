"""The manifest and home-screen icons ship from this repo instead of a third-party host."""
import json
import re
import shutil
import struct
import zlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.static_assets import CurrentBuildFiles

REPO = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((REPO / "static/manifest.json").read_text(encoding="utf-8"))
SOURCE_HTML = (REPO / "frontend/index.html").read_text(encoding="utf-8")
BRAND_BLUE = (0x00, 0x7A, 0xFF, 0xFF)


def _chunks(png: bytes):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos = 8
    while pos < len(png):
        length, kind = struct.unpack(">I4s", png[pos:pos + 8])
        yield kind, png[pos + 8:pos + 8 + length]
        pos += 12 + length


def _png_size(png: bytes):
    return struct.unpack(">II", next(data for kind, data in _chunks(png) if kind == b"IHDR")[:8])


def _corner_rgba(png: bytes):
    """Top-left pixel. Every PNG row filter predicts 0 for it, so no unfiltering is needed."""
    chunks = list(_chunks(png))
    _, _, depth, color = struct.unpack(">IIBB", dict(chunks)[b"IHDR"][:10])
    raw = zlib.decompress(b"".join(data for kind, data in chunks if kind == b"IDAT"))[1:]
    if color == 6:
        return tuple(raw[:4])
    if color == 2:
        return (*raw[:3], 255)
    assert color == 3, f"unexpected PNG colour type {color}"
    index = raw[0] >> (8 - depth)
    palette, alpha = dict(chunks)[b"PLTE"], dict(chunks).get(b"tRNS", b"")
    return (*palette[index * 3:index * 3 + 3], alpha[index] if index < len(alpha) else 255)


def _icon_links(html):
    return re.findall(r'<link rel="(?:apple-touch-icon|icon)" href="([^"]+)"', html)


def _serve(static_dir):
    test_app = FastAPI()
    test_app.mount("/static", CurrentBuildFiles(directory=static_dir))
    return TestClient(test_app)


@pytest.fixture
def built_static(isolated_runtime):
    """static/ as `npm run build` leaves it: the manifest, plus frontend/public copied into dist/."""
    static = isolated_runtime / "static"
    shutil.copytree(REPO / "frontend/public", static / "dist")
    shutil.copy(REPO / "static/manifest.json", static)
    (static / "dist/index.html").write_text("<html></html>")
    with _serve(static) as client:
        yield client


def test_manifest_icons_are_same_origin_and_split_by_purpose():
    icons = MANIFEST["icons"]
    assert icons and all(icon["src"].startswith("/static/dist/") for icon in icons)
    purposes = [icon.get("purpose", "any") for icon in icons]
    assert "maskable" in purposes and "any maskable" not in purposes  # combined purpose pads "any" badly
    assert {"192x192", "512x512"} <= {i["sizes"] for i in icons if i.get("purpose", "any") == "any"}


def test_every_manifest_icon_is_served_at_its_declared_size(built_static):
    for icon in MANIFEST["icons"]:
        res = built_static.get(icon["src"])
        assert res.status_code == 200, icon["src"]
        assert res.headers["content-type"] == "image/png"
        assert "x".join(map(str, _png_size(res.content))) == icon["sizes"], icon["src"]


def test_index_links_apple_touch_icon_and_favicons(built_static):
    links = _icon_links(SOURCE_HTML)
    assert "/apple-touch-icon-180x180.png" in links
    for link in links:  # Vite serves public/ files under the /static/dist/ base
        assert built_static.get(f"/static/dist{link}").status_code == 200, link
    assert _png_size(built_static.get("/static/dist/apple-touch-icon-180x180.png").content) == (180, 180)


@pytest.mark.parametrize("name", ["apple-touch-icon-180x180.png", "maskable-icon-512x512.png"])
def test_full_bleed_icons_have_an_opaque_brand_background(name):
    # iOS fills transparent apple-touch-icon pixels with black; maskable icons are cropped to any shape.
    assert _corner_rgba((REPO / "frontend/public" / name).read_bytes()) == BRAND_BLUE


@pytest.mark.skipif(not (REPO / "static/dist/index.html").is_file(), reason="frontend not built")
def test_current_build_serves_every_icon_it_links():
    links = _icon_links((REPO / "static/dist/index.html").read_text(encoding="utf-8"))
    assert len(links) == 3 and all(link.startswith("/static/dist/") for link in links)
    with _serve(REPO / "static") as client:
        for link in links + [icon["src"] for icon in MANIFEST["icons"]]:
            assert client.get(link).status_code == 200, link
