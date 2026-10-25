import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from app.config import settings
from app.database import init_db
from app.routers import items_router, categories_router, ingest_router, line_router, radar_router, session_router, watch_router, behavior_router
from app.mcp_server import mcp
from app.radar.scheduler import radar_scheduler
from app.queue.worker import task_worker

logger = logging.getLogger("omnikeep.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and tables
    init_db()
    # Start task worker for persistent background queue processing
    task_worker.start()
    # Start periodic Radar Scheduler in background
    if settings.RADAR_ENABLED:
        radar_scheduler.start()
    # Daily multi-sink backup loop (local/rclone/git; off disables)
    backup_task = None
    if settings.BACKUP_SINK != "off":
        from app.backup import backup_loop
        backup_task = asyncio.create_task(backup_loop())
        logger.info("Backup scheduler started (sink=%s)", settings.BACKUP_SINK)
    # Start Telegram ingestion bot polling in-process so a single
    # `python run.py` brings up the whole stack (bot previously required
    # a separate `python run_bot.py` process and silently died on reboot).
    telegram_task = None
    if settings.TELEGRAM_BOT_TOKEN:
        from app.bot.telegram_bot import get_telegram_bot
        bot = get_telegram_bot()
        if bot:
            telegram_task = asyncio.create_task(bot.run_polling())
            logger.info("Telegram ingestion bot polling started (embedded)")
    yield
    # Graceful shutdown of Radar Scheduler, Task Worker, Backup loop and Telegram bot
    if backup_task:
        backup_task.cancel()
        try:
            await backup_task
        except asyncio.CancelledError:
            pass
    if telegram_task:
        telegram_task.cancel()
        try:
            await telegram_task
        except asyncio.CancelledError:
            pass
    await radar_scheduler.stop()
    await task_worker.stop()

app = FastAPI(
    title="OmniKeep",
    description="Self-hosted Multimodal Information Radar & Second Brain",
    version="0.1.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Remote MCP Token Authentication Middleware for /mcp routes
@app.middleware("http")
async def mcp_security_middleware(request: Request, call_next):
    if request.url.path.startswith("/mcp"):
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:].strip()
        if not token:
            token = request.query_params.get("token") or request.query_params.get("api_key") or ""

        if settings.API_KEY and token != settings.API_KEY:
            return JSONResponse(
                status_code=401,
                content={"error": "Unauthorized: Invalid or missing API key for Remote MCP"}
            )
            
    return await call_next(request)

# Include Routers
app.include_router(items_router)
app.include_router(categories_router)
app.include_router(ingest_router)
app.include_router(line_router)
app.include_router(radar_router)
app.include_router(session_router)
app.include_router(watch_router)
app.include_router(behavior_router)

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

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def serve_dashboard():
    # Prefer the compiled Vite app; fall back to the pre-rebuild single-file UI.
    dist_index = static_dir / "dist" / "index.html"
    if dist_index.exists():
        return FileResponse(str(dist_index))
    legacy_index = static_dir / "index-legacy.html"
    if legacy_index.exists():
        return FileResponse(str(legacy_index))
    return {"message": "OmniKeep API running. Build the frontend: cd frontend && npm run build"}

@app.get("/health")
async def health_check():
    # Passive cookie-bridge snapshot for ops visibility (never launches Chrome).
    from app.routers.session import _bridge_snapshot
    try:
        session = _bridge_snapshot()
    except Exception:
        session = {"mode": "unknown"}

    return {
        "status": "healthy",
        "service": "OmniKeep",
        "version": "0.1.0",
        "primary_provider": settings.PRIMARY_LLM_PROVIDER,
        "gemini_keys_count": len(settings.gemini_keys),
        "mcp_enabled": True,
        "session_bridge": {
            "mode": session.get("mode"),
            "cdp_reachable": session.get("cdp_reachable", False),
            "connected_platforms": [p["id"] for p in session.get("platforms", []) if p.get("connected")],
        },
    }
