"""Local speech-to-text falls back to CPU when CUDA inference fails (app/parsers/reel.py).

faster-whisper and ctranslate2 are replaced with fakes, so this runs without them or a GPU."""
import importlib.machinery
import sys
import types
from unittest.mock import Mock

import numpy as np

from app.parsers import reel


def _fake_module(monkeypatch, name, **attrs):
    module = types.ModuleType(name)
    module.__spec__ = importlib.machinery.ModuleSpec(name, None)  # find_spec reads it
    module.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, module)


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
    monkeypatch.setattr(reel, "_local_whisper_model", None)
    monkeypatch.setattr(reel, "_force_cpu_stt", False)
    pcm = np.zeros(16000, dtype=np.float32).tobytes()  # one second of 16 kHz audio from "ffmpeg"
    monkeypatch.setattr(reel.subprocess, "run", lambda *a, **k: Mock(returncode=0, stdout=pcm))
    audio = isolated_runtime / "clip.mp3"
    audio.write_bytes(b"x")

    assert reel.transcribe_local_whisper(str(audio)) == ""
    assert reel.transcribe_local_whisper(str(audio)) == "hello"
    assert built == ["cuda", "cpu"]
