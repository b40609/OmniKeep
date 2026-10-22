import uvicorn
from app.config import settings

if __name__ == "__main__":
    print("=" * 60)
    print("OmniKeep - Multimodal Information Radar & Second Brain")
    print(f"Dashboard: http://localhost:{settings.PORT}")
    print(f"API Docs:  http://localhost:{settings.PORT}/docs")
    print("=" * 60)
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=False)
