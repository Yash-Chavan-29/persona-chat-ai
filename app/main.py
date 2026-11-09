"""
app/main.py — FastAPI application entry point.

Features:
  • Serves the modern cyberpunk glassmorphism UI at GET /
  • Serves static assets from /static
  • Pre-warms ChromaDB PersonaMemory in a background thread at startup
  • Registers CORS middleware
  • Exposes OpenAPI docs at /docs
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import router, _get_memory
from app.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):  # noqa: ARG001
    """
    Pre-warm the ChromaDB PersonaMemory in a background thread so that
    the SentenceTransformer model is downloaded/loaded before any request
    arrives.
    """
    settings = get_settings()
    print(
        f"[PersonaChatAI] Starting — env={settings.app_env} "
        f"persona={settings.persona_name} "
        f"chroma={settings.chroma_persist_dir}"
    )
    print("[PersonaChatAI] Pre-warming embedding model (may download on first run)...")
    await asyncio.to_thread(_get_memory)
    print("[PersonaChatAI] Embedding model ready [OK]")
    yield
    print("[PersonaChatAI] Shutdown complete.")


app = FastAPI(
    title="Persona Chat AI",
    description=(
        "Impersonate a real person's WhatsApp texting style using "
        "Gemini 2.5 Flash + ChromaDB few-shot retrieval."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API Routes ────────────────────────────────────────────────────────────────
app.include_router(router)

# ── Static Files & Frontend ───────────────────────────────────────────────────
_static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(_static_dir):
    app.mount("/static", StaticFiles(directory=_static_dir), name="static")


@app.get("/", tags=["frontend"])
async def serve_ui():
    index_path = os.path.join(_static_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {
        "service": "PersonaChatAI",
        "status": "running",
        "docs": "/docs",
    }
