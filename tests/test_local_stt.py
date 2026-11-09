"""Local speech-to-text (app/parsers/reel.py): which model, one in VRAM at a time, and its fallbacks.

faster-whisper and ctranslate2 are replaced with fakes, so this runs without them or a GPU."""
import importlib.machinery
import logging
import sys
import types
from unittest.mock import Mock

import numpy as np
import pytest

from app.parsers import reel
from app.parsers import transcript as tr

AUDIO = np.zeros(16000, dtype=np.float32)


def _fake_module(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None)  # find_spec reads it
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)


@pytest.fixture
def fake_stt(monkeypatch):
    """A GPU, a faster-whisper that records what it loads and unloads, and a downloadable Breeze."""
    state = {"built": [], "unloaded": [], "said": [(0.0, 2.0, "这个软件"), (2.0, 4.0, "很好用")], "language": "zh",
             "gpus": 1, "breeze": "breeze-dir", "calls": []}

    class WhisperModel:
        def __init__(self, path, device, **kwargs):
            self.path, self.device = path, device
            state["built"].append((path, device))
            self.model = Mock(unload_model=lambda: state["unloaded"].append(path))

        def transcribe(self, audio, language=None, **kwargs):
            state["calls"].append((self.path, language))
            segments = [Mock(start=a, end=b, text=f" {t} ") for a, b, t in state["said"]]
            return iter(segments), Mock(language=state["language"])

    def breeze_path():
        if isinstance(state["breeze"], Exception):
            raise state["breeze"]
        return state["breeze"]

    _fake_module(monkeypatch, "faster_whisper", WhisperModel=WhisperModel)
    _fake_module(monkeypatch, "faster_whisper.tokenizer", _LANGUAGE_CODES=("en", "ja", "zh", "yue"))
    _fake_module(monkeypatch, "ctranslate2", get_cuda_device_count=lambda: state["gpus"])
    monkeypatch.setattr(reel, "_preload_cuda_dlls", lambda: None)
    monkeypatch.setattr(reel, "_breeze_path", breeze_path)
    monkeypatch.setattr(reel, "_local_whisper_model", None)
    monkeypatch.setattr(reel, "_local_whisper_name", "")
    monkeypatch.setattr(reel, "_force_cpu_stt", False)
    monkeypatch.setattr(reel, "_breeze_off_until", 0.0)
    monkeypatch.setattr(tr, "_opencc", None)
    return state


def test_chinese_or_unknown_goes_to_breeze_and_a_declared_other_language_to_turbo(fake_stt):
    assert reel.transcribe_audio(AUDIO, "") and fake_stt["built"] == [("breeze-dir", "cuda")]
    reel.transcribe_audio(AUDIO, "zh-Hant")
    assert fake_stt["built"] == [("breeze-dir", "cuda")]  # already loaded: no second load
    fake_stt["said"], fake_stt["language"] = [(0.0, 3.0, "So in college")], "en"
    assert reel.transcribe_audio(AUDIO, "en-US") == [(0.0, 3.0, "So in college")]
    # One model in VRAM at a time: Breeze is unloaded before turbo is loaded.
    assert fake_stt["built"][-1] == ("large-v3-turbo", "cuda") and fake_stt["unloaded"] == ["breeze-dir"]
    # Breeze detects the language itself, as measured; turbo is told the declared one.
    assert fake_stt["calls"] == [("breeze-dir", None), ("breeze-dir", None), ("large-v3-turbo", "en")]
    for language in ("zh", "zh-TW", "cmn", ""):
        assert reel.chinese_or_unknown(language)
    for language in ("en", "ja", "yue", "ko-KR"):
        assert not reel.chinese_or_unknown(language)


def test_without_a_gpu_small_for_every_language(fake_stt):
    fake_stt["gpus"] = 0
    reel.transcribe_audio(AUDIO, "")
    reel.transcribe_audio(AUDIO, "en")
    assert fake_stt["built"] == [("small", "cpu")]


def test_breeze_that_cannot_be_downloaded_falls_back_to_turbo(fake_stt, monkeypatch, caplog):
    pytest.importorskip("opencc")
    fake_stt["breeze"] = OSError("couldn't connect to huggingface.co")
    with caplog.at_level(logging.WARNING, logger="omnikeep.reel"):
        said = reel.transcribe_audio(AUDIO, "zh-Hant")
    # Never no transcript; turbo's Simplified Chinese comes out in Taiwan Traditional.
    assert said == [(0.0, 2.0, "這個軟體"), (2.0, 4.0, "很好用")]
    assert fake_stt["built"] == [("large-v3-turbo", "cuda")] and fake_stt["calls"] == [("large-v3-turbo", "zh")]
    assert any("breeze-asr-25 could not be loaded" in r.getMessage() for r in caplog.records)
    reel.transcribe_audio(AUDIO, "")
    assert len(fake_stt["built"]) == 1  # not retried on every video ...
    monkeypatch.setattr(reel.time, "monotonic", lambda: reel._breeze_off_until + 1)
    fake_stt["breeze"] = "breeze-dir"
    reel.transcribe_audio(AUDIO, "")
    assert fake_stt["built"][-1] == ("breeze-dir", "cuda")  # ... but again an hour later


def test_only_chinese_from_turbo_or_small_is_converted(fake_stt):
    pytest.importorskip("opencc")
    assert [t for _, _, t in reel.transcribe_audio(AUDIO, "")] == ["这个软件", "很好用"]  # Breeze: as written
    fake_stt["gpus"] = 0
    assert [t for _, _, t in reel.transcribe_audio(AUDIO, "")] == ["這個軟體", "很好用"]
    fake_stt["said"], fake_stt["language"] = [(0.0, 1.0, "学校の会议")], "ja"
    assert reel.transcribe_audio(AUDIO, "ja") == [(0.0, 1.0, "学校の会议")]  # Japanese kanji stay Japanese


def test_the_model_is_loaded_and_swapped_under_the_transcription_lock(fake_stt, monkeypatch):
    held = []

    class Lock:
        def __init__(self):
            self.depth = 0

        def __enter__(self):
            self.depth += 1

        def __exit__(self, *exc):
            self.depth -= 1

    lock = Lock()
    monkeypatch.setattr(tr, "_stt_lock", lock)
    real_build = reel._build
    monkeypatch.setattr(reel, "_build", lambda name: held.append(lock.depth) or real_build(name))
    reel.transcribe_audio(AUDIO, "")
    reel.transcribe_audio(AUDIO, "en")
    assert held == [2, 2] and lock.depth == 0  # inside transcribe_audio's hold, taken again (reentrant)


def test_cuda_failure_rebuilds_the_model_on_cpu(monkeypatch, isolated_runtime):
    built = []

    class WhisperModel:
        def __init__(self, size, device, **kwargs):
            self.device = device
            built.append(device)

        def transcribe(self, audio, **kwargs):
            # CUDA init succeeds; the runtime DLL is only loaded at the first inference.
            if self.device == "cuda":
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            return iter([Mock(text=" hello ")]), None

    _fake_module(monkeypatch, "faster_whisper", WhisperModel=WhisperModel)
    _fake_module(monkeypatch, "ctranslate2", get_cuda_device_count=lambda: 1)
    monkeypatch.setattr(reel, "_preload_cuda_dlls", lambda: None)
    monkeypatch.setattr(reel, "_breeze_path", lambda: "breeze-dir")
    monkeypatch.setattr(reel, "_local_whisper_model", None)
    monkeypatch.setattr(reel, "_local_whisper_name", "")
    monkeypatch.setattr(reel, "_force_cpu_stt", False)
    pcm = np.zeros(16000, dtype=np.float32).tobytes()  # one second of 16 kHz audio from "ffmpeg"
    monkeypatch.setattr(reel.subprocess, "run", lambda *a, **k: Mock(returncode=0, stdout=pcm))
    audio = isolated_runtime / "clip.mp3"
    audio.write_bytes(b"x")

    assert reel.transcribe_local_whisper(str(audio)) == ""
    assert reel.transcribe_local_whisper(str(audio)) == "hello"
    assert built == ["cuda", "cpu"]
