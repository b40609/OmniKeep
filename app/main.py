import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.static_assets import CurrentBuildFiles
from fastapi.responses import FileResponse
from app.config import settings
from app.database import init_db
from app.routers import (
    items_router, categories_router, ingest_router, line_router,
    radar_router, session_router, watch_router, behavior_router, rules_router
)
from app.mcp_server import mcp
from app.radar.scheduler import radar_scheduler
from app.queue.worker import task_worker
from app.security import verify_api_key

logger = logging.getLogger("omnikeep.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        from app.vector import init_vector_db
        init_vector_db()
    except Exception as e:
        logger.warning(f"Could not initialize vector database: {e}")
    if not settings.BACKGROUND_SERVICES_ENABLED:
        yield
        return
    from app.background import follow_up_pool
    from app.backup import backup_loop
    from app.bot.telegram_bot import get_telegram_bot
    tasks = []
    bot = None
    worker_started = False
    radar_started = False
    try:
        follow_up_pool.start()
        task_worker.start()
        worker_started = True
        if settings.RADAR_ENABLED:
            radar_scheduler.start()
            radar_started = True
        if settings.BACKUP_SINK != "off":
            tasks.append(asyncio.create_task(backup_loop()))
        bot = get_telegram_bot() if settings.TELEGRAM_BOT_TOKEN else None
        if bot:
            tasks.append(asyncio.create_task(bot.run_polling()))
        yield
    finally:
        # Stop polling/producers before draining consumers and closing bot HTTP.
        for task in tasks:
            task.cancel()
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("Background service failed (%s)", type(result).__name__)
        try:
            if radar_started:
                await radar_scheduler.stop()
        finally:
            try:
                if worker_started:
                    await task_worker.stop()
            finally:
                try:
                    await follow_up_pool.stop()
                finally:
                    if bot:
                        await bot.close()

app = FastAPI(
    title="OmniKeep",
    description="Self-hosted Multimodal Information Radar & Second Brain",
    version="0.1.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin for origin in settings.CORS_ORIGINS if origin != "*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# App-wide middleware also protects mounted MCP applications.
app.middleware("http")(verify_api_key)

# Include Routers
app.include_router(items_router)
app.include_router(categories_router)
app.include_router(ingest_router)
app.include_router(line_router)
app.include_router(radar_router)
app.include_router(session_router)
app.include_router(watch_router)
app.include_router(behavior_router)
app.include_router(rules_router)

# Mount Remote MCP Server (SSE Transport)
app.mount("/mcp", mcp.sse_app(mount_path="/mcp"))

# Mount Static Files for Web Dashboard & PWA
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    # Serve the Vite build (must be registered before the /static mount so the
    # Service-Worker-Allowed header reaches the PWA service worker).
    dist_dir = static_dir / "dist"
    if dist_dir.exists():
        @app.get("/static/dist/sw.js", include_in_schema=False)
        async def serve_service_worker():
            sw_file = dist_dir / "sw.js"
            return FileResponse(
                str(sw_file),
                media_type="application/javascript",
                headers={
                    "Service-Worker-Allowed": "/",
                    "Cache-Control": "no-cache",
                },
            )

    app.mount("/static", CurrentBuildFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def serve_dashboard():
    # Serve only the current compiled frontend.
    dist_index = static_dir / "dist" / "index.html"
    if dist_index.exists():
        return FileResponse(str(dist_index), headers={"Cache-Control": "no-cache"})
    return {"message": "OmniKeep API running. Build the frontend: cd frontend && npm run build"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "OmniKeep", "version": "0.1.0"}
