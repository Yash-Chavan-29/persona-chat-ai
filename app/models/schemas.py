"""
app/models/schemas.py — Pydantic request/response models.
"""
from __future__ import annotations

from typing import List, Optional
from pydantic import BaseModel, Field


# ─── Upload ────────────────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    status: str
    parsed_messages: int
    indexed_pairs: int
    target_person: str


# ─── Chat ──────────────────────────────────────────────────────────────────────

class HistoryMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: List[HistoryMessage] = Field(default_factory=list)
    persona_name: Optional[str] = None   # override persona for this request


class ChatResponse(BaseModel):
    messages: List[str]
    delays_ms: List[int] = Field(
        ...,
        description="Per-burst delay in milliseconds before each message is shown",
    )


# ─── Persona ───────────────────────────────────────────────────────────────────

class PersonaProfile(BaseModel):
    name: Optional[str] = None
    hinglish_ratio: str = "60% Hindi Latin script, 40% English"
    slang: List[str] = Field(default_factory=list)
    casing: str = "mostly lowercase, rarely uses full stops"
    tone: str = "casual, frank, conversational"
    slang_frequencies: dict = Field(
        default_factory=dict,
        description="Token → occurrences per 100 messages",
    )


class PersonaStatusResponse(BaseModel):
    persona_name: str
    is_indexed: bool
    indexed_pairs: int
    profile_exists: bool
    profile: Optional[PersonaProfile] = None


class ProfileRegenerateResponse(BaseModel):
    status: str
    profile: PersonaProfile
