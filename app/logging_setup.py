"""Where the app's own log records go.

Until now the only handler was the one FastMCP's constructor installs on the root logger
when app.mcp_server is imported (logging.basicConfig, format "%(message)s"), so app
records carried no time, level or source, and only by that side effect. Library loggers
are left alone: httpx at INFO would log the Telegram token in request URLs (see run.py)."""
import logging
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
