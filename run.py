import logging
import uvicorn
from app.config import settings

if __name__ == "__main__":
    # httpx INFO request lines contain the Telegram Bot API token in the URL.
    # Application-specific bot logs provide diagnostics without exposing it.
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    print("=" * 60)
    print("OmniKeep - Multimodal Information Radar & Second Brain")
    print(f"Dashboard: http://localhost:{settings.PORT}")
    print(f"API Docs:  http://localhost:{settings.PORT}/docs")
    print("=" * 60)
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
