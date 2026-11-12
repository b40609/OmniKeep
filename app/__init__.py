"""
OmniKeep - self-hosted: send a link, have it read, find it later.
"""
from pathlib import Path

from app.logging_setup import protect_http_logs

# Before anything can send a request: request URLs may carry a credential (the Telegram
# bot token), and they must not reach the log whichever way this process was started.
protect_http_logs()

# The repo-root VERSION file is the only place the version is written; the
# frontend build reads the same file (frontend/vite.config.ts).
__version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
