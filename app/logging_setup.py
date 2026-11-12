"""Where the app's own log records go.

Until now the only handler was the one FastMCP's constructor installs on the root logger
when app.mcp_server is imported (logging.basicConfig, format "%(message)s"), so app
records carried no time, level or source, and only by that side effect. Library loggers
are left alone, with one exception: httpx. At INFO it logs every request's URL, and the
Telegram Bot API carries the token in the URL (https://api.telegram.org/bot<token>/...).
run.py turns that logger down, but a process started another way (uvicorn app.main:app,
the MCP server, a test server) did not, and FastMCP's root handler then printed the token.
protect_http_logs() is applied when the app package is imported, so every entry point has it."""
import logging
import re
import sys

APP_LOGGER = "omnikeep"


def configure_logging(level: int = logging.INFO) -> None:
    """Send omnikeep.* records to stderr. Safe to call more than once.

    stderr, not stdout: in MCP stdio mode stdout may carry only protocol messages."""
    logger = logging.getLogger(APP_LOGGER)
    if not any(getattr(h, "_omnikeep", False) for h in logger.handlers):
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        handler._omnikeep = True
        logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False  # or FastMCP's root handler prints every record a second time


# /bot<id>:<secret>/ in a Telegram Bot API address, and credentials passed as query values.
_BOT_TOKEN = re.compile(r"/bot\d+:[A-Za-z0-9_-]+")
_QUERY_SECRET = re.compile(r"(?i)([?&](?:key|api_key|apikey|access_token|token)=)[^&\s\"']+")
HTTP_LOGGERS = ("httpx", "httpcore")


def redact_url_secrets(text: str) -> str:
    """Hide a Telegram bot token and key-like query values in a log line."""
    return _QUERY_SECRET.sub(r"\1***", _BOT_TOKEN.sub("/bot***", text))


class _RedactUrlSecrets(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        clean = redact_url_secrets(message)
        if clean != message:
            record.msg, record.args = clean, None
        return True


def protect_http_logs() -> None:
    """Keep credentials in request URLs out of the log, however the process was started.

    The HTTP client loggers are turned down to WARNING unless someone set a level on them
    (run.py sets CRITICAL), and what they do log has tokens removed. Safe to call again."""
    for name in HTTP_LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, _RedactUrlSecrets) for f in logger.filters):
            logger.addFilter(_RedactUrlSecrets())
        if logger.level == logging.NOTSET:
            logger.setLevel(logging.WARNING)
