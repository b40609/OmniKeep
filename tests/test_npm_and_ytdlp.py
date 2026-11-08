"""npm pages come from the registry (npmjs.com answers 403); yt-dlp gets deno for YouTube's challenges."""
import asyncio

import pytest

from app.parsers import media_network, npm
from app.parsers.npm import npm_package, parse_npm_package


@pytest.mark.parametrize("url, expected", [
    ("https://www.npmjs.com/package/bareguard", ("bareguard", "")),
    ("https://npmjs.com/package/@anthropic-ai/sdk?activeTab=readme", ("@anthropic-ai/sdk", "")),
    ("https://www.npmjs.com/package/react/v/18.3.1", ("react", "18.3.1")),
    ("https://www.npmjs.com/search?q=react", None),
    ("https://github.com/package/react", None),
])
def test_package_pages(url, expected):
    assert npm_package(url) == expected


class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body
        self.text = body if isinstance(body, str) else ""

    def json(self):
        return self._body


def _client(answers, asked):
    class Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            asked.append(url)
            for part, answer in answers.items():
                if part in url:
                    return _Resp(*answer)
            return _Resp(404, "")
    return Client


def test_manifest_and_readme_become_the_page(monkeypatch):
    asked = []
    monkeypatch.setattr(npm, "public_http_client", _client({
        "registry.npmjs.org/@anthropic-ai%2Fsdk/latest": (200, {
            "name": "@anthropic-ai/sdk", "version": "1.6.0", "description": "The official TypeScript library",
            "repository": {"url": "git+https://github.com/anthropics/anthropic-sdk-typescript.git"},
            "license": "MIT", "keywords": ["anthropic", "ai"]}),
        "/README.md": (200, "# Anthropic SDK\nInstall with npm."),
    }, asked))
    page = asyncio.run(parse_npm_package("https://www.npmjs.com/package/@anthropic-ai/sdk"))
    assert page["title"] == "@anthropic-ai/sdk - npm" and page["http_status"] == 200
    text = page["content_raw"]
    assert text.startswith("@anthropic-ai/sdk 1.6.0\n\nThe official TypeScript library")
    assert "原始碼：https://github.com/anthropics/anthropic-sdk-typescript\n" in text
    assert "關鍵字：anthropic、ai" in text and text.endswith("# Anthropic SDK\nInstall with npm.")
    assert asked[1] == "https://cdn.jsdelivr.net/npm/@anthropic-ai/sdk@1.6.0/README.md"


def test_registry_failure_leaves_the_page_to_the_usual_fetch(monkeypatch):
    monkeypatch.setattr(npm, "public_http_client", _client({"registry.npmjs.org": (503, {})}, []))
    assert asyncio.run(parse_npm_package("https://www.npmjs.com/package/bareguard")) is None


def test_youtube_downloads_get_deno_and_never_node(monkeypatch, isolated_runtime):
    tmp_path = isolated_runtime
    deno = tmp_path / "deno.exe"
    deno.write_text("")
    monkeypatch.setattr(media_network.shutil, "which", lambda name: str(deno) if name == "deno" else "C:/node.exe")
    assert media_network.PublicYoutubeDL({"quiet": True}).params["js_runtimes"] == {"deno": {"path": str(deno)}}
    monkeypatch.setattr(media_network.shutil, "which", lambda name: "C:/node.exe" if name == "node" else None)
    monkeypatch.setattr(media_network.Path, "home", lambda: tmp_path / "nohome")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none"))
    runtimes = media_network.PublicYoutubeDL({"quiet": True}).params.get("js_runtimes") or {}
    assert "node" not in runtimes and not (runtimes.get("deno") or {}).get("path")  # yt-dlp's own default only
