"""
OmniKeep - Self-hosted Multimodal Information Radar & Second Brain
"""
from pathlib import Path

# The repo-root VERSION file is the only place the version is written; the
# frontend build reads the same file (frontend/vite.config.ts).
__version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
