"""FastAPI application entry point with CORS and .env support."""

import asyncio
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

from config import settings
from api.routes import router
from db.init_db import init_sqlite

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    debug=settings.DEBUG,
)

# ── Static files (for test.html) ────────────────────────────────────────
import os
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.isdir(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")

# ── CORS ────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/")
async def root():
    return {
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "invoke": "POST /api/v1/invoke",
            "stream": "GET  /api/v1/stream/{thread_id}",
            "resume": "POST /api/v1/resume/{thread_id}",
            "health": "GET  /api/v1/health",
        },
    }


@app.on_event("startup")
async def on_startup():
    """Initialize DB synchronously, try Chroma in background."""
    init_sqlite()
    asyncio.create_task(_init_chroma_async())


async def _init_chroma_async():
    """Try to initialize Chroma; log failure but don't crash."""
    try:
        from tools.rag_tool import _ensure_chroma
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, _ensure_chroma)
    except Exception as e:
        print(f"[startup] Chroma init skipped: {e}")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )
