"""Start the local OpenAI-compatible endpoint (app/llm_gateway.py) on 127.0.0.1.

scripts/watchdog.ps1 starts it (and starts it again if it stops) when llm_gateway.json exists
next to the database; scripts/llm_gateway_setup.py creates that file. Runs beside run.py: the
OmniKeep server need not be restarted for it.

    python run_gateway.py                 port from llm_gateway.json (default 5101)
    python run_gateway.py --config x.json --port 5199   a second instance with another order
"""
import argparse
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

import uvicorn

from app.logging_setup import configure_logging


def log_file() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / ".local" / "share") / "OmniKeep" / "logs"
    base.mkdir(parents=True, exist_ok=True)
    return base / "llm_gateway.log"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", help="order file (default: llm_gateway.json next to the database)")
    parser.add_argument("--port", type=int, help="port (default: the file's port)")
    args = parser.parse_args()

    logging.getLogger("httpx").setLevel(logging.CRITICAL)  # as in run.py
    configure_logging()
    handler = RotatingFileHandler(log_file(), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    logging.getLogger("omnikeep").addHandler(handler)

    from app import ai_usage
    from app.database import get_db_connection
    from app.llm_gateway import HOST, create_app, load_config
    from contextlib import closing
    with closing(get_db_connection()) as db, db:
        ai_usage.ensure_sources_table(db)  # run.py may not have migrated this database yet
    config_file = Path(args.config).resolve() if args.config else None
    config = load_config(config_file)
    port = args.port or config["port"]
    logging.getLogger("omnikeep.llm_gateway").info(
        "Gateway listening on http://%s:%d/v1 (connections %s, models %s, thinking %s)", HOST, port,
        config["connections"], config["models"], config["thinking_level"])
    uvicorn.run(create_app(config_file), host=HOST, port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
