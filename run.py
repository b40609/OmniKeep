import logging
import uvicorn
from app.config import settings
from app.logging_setup import configure_logging

if __name__ == "__main__":
    # httpx INFO request lines contain the Telegram Bot API token in the URL.
    # Application-specific bot logs provide diagnostics without exposing it.
    # (app/logging_setup.py protect_http_logs() covers processes not started through this file.)
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    configure_logging()
    print("=" * 60)
    # ASCII only: a redirected stdout on Windows may not be able to encode anything else.
    print("OmniKeep - send a link, have it read, find it later")
    print(f"Dashboard: http://localhost:{settings.PORT}")
    print(f"API Docs:  http://localhost:{settings.PORT}/docs")
    print("=" * 60)
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
