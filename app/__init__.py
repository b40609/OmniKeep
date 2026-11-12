"""
OmniKeep - self-hosted: send a link, have it read, find it later.
"""
from pathlib import Path

from app.logging_setup import protect_http_logs

# Before anything can send a request: request URLs may carry a credential (the Telegram
# bot token), and they must not reach the log whichever way this process was started.
protect_http_logs()


def _trust_system_certificates() -> None:
    """Check HTTPS against the operating system's certificate store, not only certifi's bundle.

    A company network that inspects TLS re-signs every site with its own root, which IT installs
    in the OS store (2026-11-12: facebook.com arrived signed by an internal CA). httpx and yt-dlp
    only trusted certifi, so every link failed with CERTIFICATE_VERIFY_FAILED on that network.
    truststore is what pip uses for the same reason; without it, behaviour stays as before.
    """
    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()


_trust_system_certificates()

# The repo-root VERSION file is the only place the version is written; the
# frontend build reads the same file (frontend/vite.config.ts).
__version__ = (Path(__file__).resolve().parent.parent / "VERSION").read_text(encoding="utf-8").strip()
