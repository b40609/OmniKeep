from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from app.config import settings
from app.database import init_db
from app.routers import items_router, categories_router, ingest_router, line_router, radar_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize SQLite database and tables
    init_db()
    yield

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

# Include Routers
app.include_router(items_router)
app.include_router(categories_router)
app.include_router(ingest_router)
app.include_router(line_router)
app.include_router(radar_router)

# Mount Static Files for Web Dashboard & PWA
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def serve_dashboard():
    index_file = static_dir / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return {"message": "OmniKeep API running. Place index.html in static/"}

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "OmniKeep",
        "version": "0.1.0",
        "primary_provider": settings.PRIMARY_LLM_PROVIDER,
        "gemini_keys_count": len(settings.gemini_keys)
    }
