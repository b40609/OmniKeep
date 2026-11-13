"""Serve the current build without exposing archived UIs or credential bundles."""
import re
from pathlib import Path

from fastapi import HTTPException
from fastapi.staticfiles import StaticFiles


_CHUNK_REF = re.compile(r'["\'`(/]((?:assets/)?[\w.-]+-[\w-]{8}\.js)["\'`)]')
_chunk_cache: dict = {}


def _lazy_chunks(root: Path, entry: set) -> set:
    """The JS chunks the build's entry scripts load later with import(), e.g. mermaid for the
    deep analysis flowcharts (frontend/src/lib/mermaid.ts), followed from file to file. Only
    files this build references are served, as for the entry scripts."""
    stamp = tuple(sorted((p, (root / p).stat().st_mtime) for p in entry if (root / p).is_file()))
    if _chunk_cache.get("stamp") == stamp:
        return _chunk_cache["chunks"]
    found, todo = set(), list(entry)
    while todo:
        path = root / todo.pop()
        if not path.is_file():
            continue
        for ref in _CHUNK_REF.findall(path.read_text(encoding="utf-8", errors="ignore")):
            name = "dist/assets/" + ref.removeprefix("assets/")
            if name not in found and name not in entry and (root / name).is_file():
                found.add(name)
                todo.append(name)
    _chunk_cache.update(stamp=stamp, chunks=found)
    return found


class CurrentBuildFiles(StaticFiles):
    async def get_response(self, path, scope):
        # Starlette normalizes mount paths with os.path on Windows.
        path = path.replace("\\", "/")
        root = Path(self.directory)
        allowed = {"manifest.json", "dist/index.html", "dist/sw.js", "dist/push-sw.js",
                   "dist/favicon.svg", "dist/favicon.ico",
                   # PWA icons from frontend/public (npm run generate-pwa-assets)
                   "dist/pwa-64x64.png", "dist/pwa-192x192.png", "dist/pwa-512x512.png",
                   "dist/maskable-icon-512x512.png", "dist/apple-touch-icon-180x180.png"}
        index = root / "dist/index.html"
        if index.is_file():
            html = index.read_text(encoding="utf-8")
            entry = {"dist/" + asset for asset in re.findall(r'/static/dist/([^"\s<>]+\.js)', html)}
            allowed.update(entry)
            allowed.update(_lazy_chunks(root, entry))
        worker = root / "dist/sw.js"
        if worker.is_file():
            # generateSW loads its runtime as define(["./workbox-<hash>"]) and appends
            # ".js" at run time, so the reference in sw.js has no extension.
            allowed.update(f"dist/{name}.js" for name in re.findall(
                r'workbox-[\w-]+', worker.read_text(encoding="utf-8")))
        assets = path.startswith("dist/assets/") and Path(path).suffix.lower() in {
            ".css", ".woff", ".woff2", ".ttf", ".png", ".jpg", ".svg", ".ico",
        }
        if path not in allowed and not assets:
            raise HTTPException(status_code=404)
        response = await super().get_response(path, scope)
        if path in ("dist/index.html", "dist/sw.js", "dist/push-sw.js"):
            response.headers["Cache-Control"] = "no-cache"
        return response
