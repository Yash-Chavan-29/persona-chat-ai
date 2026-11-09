"""
app/api/routes.py
==================
All HTTP endpoints — all blocking ChromaDB / LLM calls are offloaded to
a thread pool via asyncio.to_thread so they never block the event loop.

  POST /api/upload-chat    — ingest WhatsApp or Telegram export
  POST /api/chat           — generate burst reply with typing delays
  GET  /api/persona-status — check indexing & profile state
  POST /api/profile        — force-regenerate the persona profile
"""
from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.config import get_settings
from app.core.generator import PersonaEngine
from app.core.parser import ChatParser
from app.core.profiler import generate_profile
from app.core.vector_store import PersonaMemory
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    PersonaProfile,
    PersonaStatusResponse,
    ProfileRegenerateResponse,
    UploadResponse,
)

router = APIRouter(prefix="/api", tags=["persona"])

# ── Lazy singletons ───────────────────────────────────────────────────────────
_memory: Optional[PersonaMemory] = None
_engine: Optional[PersonaEngine] = None
_active_persona_name: Optional[str] = None


def _get_memory() -> PersonaMemory:
    global _memory
    if _memory is None:
        settings = get_settings()
        _memory = PersonaMemory(persist_dir=settings.chroma_persist_dir)
    return _memory


def _get_engine() -> PersonaEngine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = PersonaEngine(
            api_key=settings.gemini_api_key,
            persona_profile_path=settings.persona_profile_path,
        )
    return _engine


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload-chat", response_model=UploadResponse)
async def upload_chat(
    file: UploadFile = File(..., description="WhatsApp .txt or Telegram result.json"),
    target_person: str = Form(..., description="Exact display name of the persona"),
    format: str = Form("whatsapp", description="'whatsapp' or 'telegram'"),
    auto_profile: bool = Form(
        True,
        description="Automatically regenerate persona profile after indexing",
    ),
):
    raw_bytes = await file.read()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")

    # Parsing is CPU-bound — run in thread
    if format.lower() == "telegram":
        dialogues = await asyncio.to_thread(ChatParser.parse_telegram, raw_text, target_person)
    else:
        dialogues = await asyncio.to_thread(ChatParser.parse_whatsapp, raw_text, target_person)

    if not dialogues:
        raise HTTPException(
            status_code=400,
            detail=f"No valid messages could be parsed. Ensure this is a valid {format} export.",
        )

    memory = _get_memory()
    indexed = await asyncio.to_thread(memory.index_dialogue_pairs, dialogues, target_person)

    if indexed == 0:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Parsed {len(dialogues)} messages but found no consecutive "
                f"user→{target_person} reply pairs. Check that target_person "
                "matches the exact display name in the export."
            ),
        )

    global _active_persona_name
    _active_persona_name = target_person

    if auto_profile:
        settings = get_settings()
        if not settings.gemini_api_key:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not set.")
        try:
            await asyncio.to_thread(
                generate_profile,
                dialogues,
                target_person,
                settings.gemini_api_key,
                settings.persona_profile_path,
            )
            engine = _get_engine()
            await asyncio.to_thread(engine.reload_profile, settings.persona_profile_path)
        except Exception as exc:
            print(f"[WARN] Profile generation failed: {exc}")

    return UploadResponse(
        status="success",
        parsed_messages=len(dialogues),
        indexed_pairs=indexed,
        target_person=target_person,
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Generate a persona reply as 1–3 burst messages with per-burst typing delays.
    """
    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not configured.")

    memory = _get_memory()
    engine = _get_engine()

    # ChromaDB query — blocking, run in thread
    relevant_pairs = await asyncio.to_thread(
        memory.retrieve_similar_pairs, request.message, 4
    )

    history_dicts = [h.model_dump() for h in request.history]

    # LLM call — blocking network I/O, run in thread
    messages, delays_ms = await asyncio.to_thread(
        engine.generate_reply,
        request.message,
        relevant_pairs,
        history_dicts,
    )

    return ChatResponse(messages=messages, delays_ms=delays_ms)


@router.get("/persona-status", response_model=PersonaStatusResponse)
async def persona_status():
    """Check whether the vector DB has been indexed and a profile exists."""
    settings = get_settings()
    memory = _get_memory()

    # count() touches the DB — run in thread
    indexed_pairs = await asyncio.to_thread(memory.count)
    profile_exists = os.path.isfile(settings.persona_profile_path)

    profile: Optional[PersonaProfile] = None
    if profile_exists:
        try:
            engine = _get_engine()
            profile = engine.profile
        except Exception:
            pass

    # Resolve active persona name dynamically from profile or last upload
    active_name = (
        (profile.name if profile and profile.name else None)
        or _active_persona_name
        or settings.persona_name
    )

    return PersonaStatusResponse(
        persona_name=active_name,
        is_indexed=indexed_pairs > 0,
        indexed_pairs=indexed_pairs,
        profile_exists=profile_exists,
        profile=profile,
    )


@router.post("/profile", response_model=ProfileRegenerateResponse)
async def regenerate_profile(
    file: UploadFile = File(...),
    target_person: str = Form(...),
    format: str = Form("whatsapp"),
):
    """Force-regenerate the persona profile without re-indexing."""
    settings = get_settings()
    if not settings.gemini_api_key:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY is not set.")

    raw_bytes = await file.read()
    raw_text = raw_bytes.decode("utf-8", errors="ignore")

    if format.lower() == "telegram":
        dialogues = await asyncio.to_thread(ChatParser.parse_telegram, raw_text, target_person)
    else:
        dialogues = await asyncio.to_thread(ChatParser.parse_whatsapp, raw_text, target_person)

    if not dialogues:
        raise HTTPException(status_code=400, detail="No valid messages parsed.")

    profile = await asyncio.to_thread(
        generate_profile,
        dialogues,
        target_person,
        settings.gemini_api_key,
        settings.persona_profile_path,
    )

    engine = _get_engine()
    await asyncio.to_thread(engine.reload_profile, settings.persona_profile_path)

    return ProfileRegenerateResponse(status="regenerated", profile=profile)
