"""Public source assets must not distribute the developer's old credentials."""

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "static"


def test_retired_pages_and_qr_codes_stay_removed():
    # The pre-Vue UI, its service worker, the mobile test page and the QR codes that
    # pointed at a personal webhook. The app serves only manifest.json and the current build.
    retired = ["index-legacy.html", "sw.js", "mobile_test.html"]
    assert [name for name in retired if (STATIC / name).exists()] == []
    assert sorted(p.name for p in STATIC.glob("qr_*")) == []
