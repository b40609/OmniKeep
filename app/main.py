import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.static_assets import CurrentBuildFiles
from fastapi.responses import FileResponse
from app import __version__
from app.config import settings
from app.database import init_db
from app.routers import (
    items_router, categories_router, ingest_router, line_router,
    radar_router, session_router, watch_router, behavior_router, rules_router, push_router,
    telegram_router, settings_router, brain_router, ai_router, setup_router,
)
from app.mcp_server import mcp
from app.mcp_http import STREAMABLE_HTTP_PATH, StreamableHTTPEndpoint, streamable_http_session
from app import setup_flow
from app.radar.scheduler import radar_scheduler
from app.queue.worker import task_worker
from app.security import verify_api_key
from app import services
from app.services import supervise_telegram_polling  # noqa: F401  (kept importable from here)

logger = logging.getLogger("omnikeep.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # MCP over Streamable HTTP runs for the whole lifespan, background services or not;
    # setup tools served from here call the service's own routes in-process. Its task
    # group sits inside the service lifespan, so a shutdown error there is raised as it
    # is instead of wrapped in an ExceptionGroup.
    async with _service_lifespan(app), streamable_http_session():
        setup_flow.bind_in_process(app)
        try:
            yield
        finally:
            setup_flow.unbind_in_process()


@asynccontextmanager
async def _service_lifespan(app: FastAPI):
    init_db()
    try:
        # Once per database: the flat AI settings become connections and task slots.
        from app.ai_connections import migrate_legacy
        migrate_legacy()
    except Exception as exc:  # the older settings keep working without the migration
        logger.error("Could not move the AI settings into connections (%s: %s)", type(exc).__name__, exc)
    try:
        from app.vector import init_vector_db
        init_vector_db()
    except Exception as e:
        logger.warning(f"Could not initialize vector database: {e}")
    if settings.LOCAL_AUTO_LOGIN:
        # On by default since the sign-in switch moved to 設定 › 系統, so this is a note, not a warning.
        logger.info(
            "LOCAL_AUTO_LOGIN is on (設定 › 進階 › 這台電腦免登入): /api/session/local-auth hands the "
            "API key to loopback clients. Requests with reverse-proxy headers are refused; turn it "
            "off if another process on this machine forwards traffic to this port."
        )
    if not settings.BACKGROUND_SERVICES_ENABLED:
        yield
        return
    try:
        # Only the instance that runs background services (and so sends pushes)
        # creates the pair; a pair from .env is kept as it is.
        from app import vapid
        vapid.ensure()
    except Exception as exc:  # push being off must not keep the service from starting
        logger.error("Could not prepare the Web Push key pair (%s)", type(exc).__name__)
    from app.background import follow_up_pool
    from app.backup import backup_loop
    from app.parsers.cookie_manager import sweep_cookie_exports
    # Cookie exports left by a crash, and the all-sites export older versions kept in TEMP.
    sweep_cookie_exports()
    tasks = []
    worker_started = False
    radar_started = False
    try:
        follow_up_pool.start()
        task_worker.start()
        worker_started = True
        # Always running; each cycle checks the radar settings toggle, and saving the
        # settings wakes it, so switching the radar on or off needs no restart.
        radar_scheduler.start()
        radar_started = True
        # Always running too: each tick reads BACKUP_SINK, which the settings page can change.
        tasks.append(asyncio.create_task(backup_loop()))
        # Items whose fetch got only an error page are fetched again for a week (app.refetch).
        from app.refetch import refetch_loop
        tasks.append(asyncio.create_task(refetch_loop()))
        # Telegram polling lives in app.services so a token saved in the app restarts it.
        services.start_telegram()
        yield
    finally:
        # Stop polling/producers before draining consumers and closing bot HTTP.
        await services.stop_telegram_polling()
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
                    await services.shutdown()

app = FastAPI(
    title="OmniKeep",
    description="Self-hosted: send a link, have it read, find it later",
    version=__version__,
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
app.include_router(push_router)
app.include_router(telegram_router)
app.include_router(settings_router)
app.include_router(brain_router)
app.include_router(ai_router)
app.include_router(setup_router)

# Remote MCP: Streamable HTTP at /mcp-http (agents on another computer, via Tailscale),
# SSE kept at /mcp. Both sit behind verify_api_key like every other path.
app.add_route(STREAMABLE_HTTP_PATH, StreamableHTTPEndpoint(), include_in_schema=False)
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
    return {"status": "healthy", "service": "OmniKeep", "version": __version__}
