"""Regression tests for review-20261102 bug 4.

GeminiProvider's three ``async def`` methods called the synchronous
``client.models.generate_content`` directly, blocking the event loop for the
whole request (tens of seconds for YouTube analysis). They now go through the
SDK's async client, or ``asyncio.to_thread`` when the SDK has none.

The google-genai SDK is replaced by a fake module here so the tests run
without the package and never touch the network.
"""
import asyncio
import sys
import time
import types as _types
from typing import Any, Dict, List

import pytest


class _Resp:
    def __init__(self, text: str):
        self.text = text


class _Part:
    def __init__(self, **kw):
        self.kw = kw

    @classmethod
    def from_uri(cls, **kw):
        return cls(**kw)


class _Config:
    def __init__(self, **kw):
        self.kw = kw


def _install_fake_genai(monkeypatch, *, with_aio: bool, delay: float, calls: List[Dict[str, Any]]):
    """Install a fake `google.genai` whose generate_content takes `delay` seconds."""

    class _SyncModels:
        def generate_content(self, **kw):
            calls.append({"path": "sync", **kw})
            time.sleep(delay)              # blocks the calling thread
            return _Resp('{"ok": true, "path": "sync"}')

    class _AsyncModels:
        async def generate_content(self, **kw):
            calls.append({"path": "aio", **kw})
            await asyncio.sleep(delay)     # yields to the loop
            return _Resp('{"ok": true, "path": "aio"}')

    class _Aio:
        def __init__(self):
            self.models = _AsyncModels()

    class _Client:
        def __init__(self, api_key: str, **options):
            self.api_key = api_key
            self.models = _SyncModels()
            if with_aio:
                self.aio = _Aio()

    genai_mod = _types.ModuleType("google.genai")
    genai_mod.Client = _Client
    types_mod = _types.ModuleType("google.genai.types")
    types_mod.GenerateContentConfig = _Config
    types_mod.Part = _Part
    types_mod.HttpOptions = _Config
    genai_mod.types = types_mod
    google_mod = _types.ModuleType("google")
    google_mod.genai = genai_mod

    monkeypatch.setitem(sys.modules, "google", google_mod)
    monkeypatch.setitem(sys.modules, "google.genai", genai_mod)
    monkeypatch.setitem(sys.modules, "google.genai.types", types_mod)


async def _ticks_during(coro, period: float = 0.01) -> int:
    """Count how many times the loop could run another task while `coro` ran."""
    ticks = 0
    stop = False

    async def ticker():
        nonlocal ticks
        while not stop:
            ticks += 1
            await asyncio.sleep(period)

    t = asyncio.create_task(ticker())
    try:
        await coro
    finally:
        stop = True
        await t
    return ticks


@pytest.mark.parametrize("with_aio", [True, False], ids=["sdk-native-aio", "to_thread-fallback"])
def test_gemini_calls_do_not_block_event_loop(monkeypatch, with_aio):
    from app.providers.gemini import GeminiProvider

    calls: List[Dict[str, Any]] = []
    delay = 0.3
    _install_fake_genai(monkeypatch, with_aio=with_aio, delay=delay, calls=calls)
    prov = GeminiProvider(api_keys=["k1", "k2"], model="fake-model")

    async def run():
        out = {}
        out["text_ticks"] = await _ticks_during(prov.generate_text("hi", system_prompt="sys"))
        out["json"] = await prov.generate_json("give json")
        out["yt"] = await prov.analyze_youtube("https://youtu.be/abc", "describe")
        return out

    out = asyncio.run(run())

    # With a 0.3s call and a 10ms ticker, a blocked loop yields ~1 tick; a
    # cooperative one yields on the order of 20+. Use a conservative bound.
    assert out["text_ticks"] >= 10, f"event loop was blocked: only {out['text_ticks']} ticks"
    assert out["json"] == {"ok": True, "path": "aio" if with_aio else "sync"}
    assert out["yt"]["ok"] is True

    assert [c["path"] for c in calls] == (["aio"] * 3 if with_aio else ["sync"] * 3)
    assert all(c["model"] == "fake-model" for c in calls)
    # Request shapes are unchanged by the refactor.
    assert calls[0]["contents"] == ["sys\n\n", "hi"]
    assert calls[0]["config"].kw == {"temperature": 0.3}
    assert calls[1]["config"].kw == {"temperature": 0.2, "response_mime_type": "application/json"}
    yt_part = calls[2]["contents"][0]
    assert yt_part.kw == {"file_uri": "https://youtu.be/abc", "mime_type": "video/youtube"}


def test_gemini_concurrent_calls_overlap(monkeypatch):
    """Three slow calls issued together must finish in ~1x delay, not 3x."""
    from app.providers.gemini import GeminiProvider

    calls: List[Dict[str, Any]] = []
    delay = 0.3
    _install_fake_genai(monkeypatch, with_aio=False, delay=delay, calls=calls)
    prov = GeminiProvider(api_keys=["k1"], model="fake-model")

    async def run():
        t0 = time.perf_counter()
        await asyncio.gather(*(prov.generate_text(f"p{i}") for i in range(3)))
        return time.perf_counter() - t0

    elapsed = asyncio.run(run())
    assert elapsed < delay * 2.5, f"calls serialized on the loop: {elapsed:.2f}s"
    assert len(calls) == 3


def test_gemini_requires_key():
    from app.providers.gemini import GeminiProvider
    prov = GeminiProvider(api_keys=[], model="fake-model")
    with pytest.raises(ValueError):
        asyncio.run(prov.generate_text("x"))
