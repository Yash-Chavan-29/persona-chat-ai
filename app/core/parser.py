"""
app/core/parser.py
==================
Handles:
  • WhatsApp text export parsing (multi-line message stitching)
  • Telegram JSON export parsing
  • PII redaction (phones, UPI IDs, email-like patterns)
  • Hinglish Token Harmonizer (phonetic normalisation)
"""
from __future__ import annotations

import json
import re
from typing import Dict, List, Optional


# ─── Hinglish Token Harmonizer ────────────────────────────────────────────────

class HinglishHarmonizer:
    """
    Normalises common phonetic variants in Hinglish text so that vector
    search treats e.g. 'kyun', 'kyu', 'kyuu' as the same token.
    """

    # (pattern, canonical) — all case-insensitive, word-boundary aware
    VARIANTS: List[tuple[str, str]] = [
        # kyun / why
        (r"\bkyu+n?\b", "kyun"),
        # nahi / no
        (r"\bn(?:ahi|hi|ai|a)\b", "nahi"),
        # haan / yes
        (r"\bh(?:aan|an|na|aaan)\b", "haan"),
        # yaar / friend
        (r"\byar+\b", "yaar"),
        # bhai / brother
        (r"\bbha+i\b", "bhai"),
        # ek / one
        (r"\b1\b", "ek"),
        # theek / okay / fine
        (r"\bth[ei]+k\b", "theek"),
        # sahi / correct
        (r"\bsa+hi\b", "sahi"),
        # matlab / meaning
        (r"\bma+tlab\b", "matlab"),
        # dekh / look
        (r"\bdekh+\b", "dekh"),
        # kal / tomorrow/yesterday
        (r"\bka+l\b", "kal"),
        # abhi / now
        (r"\ba+bhi\b", "abhi"),
        # bas / enough
        (r"\bba+s\b", "bas"),
        # chal / let's go
        (r"\bcha+l\b", "chal"),
        # kya / what
        (r"\bky+a\b", "kya"),
        # arre / hey
        (r"\barre+\b", "arre"),
        # hua / happened
        (r"\bhu+a\b", "hua"),
        # scene / situation
        (r"\bsce+ne\b", "scene"),
        # sorted
        (r"\bsorte+d\b", "sorted"),
        # bro
        (r"\bbr+o\b", "bro"),
        # ok / okay
        (r"\bo+k+a*y?\b", "ok"),
        # lol
        (r"\bl+o+l+\b", "lol"),
        # bc (common informal abbreviation)
        (r"\bb+c+\b", "bc"),
    ]

    _compiled: Optional[List[tuple[re.Pattern, str]]] = None

    @classmethod
    def _get_compiled(cls) -> List[tuple[re.Pattern, str]]:
        if cls._compiled is None:
            cls._compiled = [
                (re.compile(pat, re.IGNORECASE), canon)
                for pat, canon in cls.VARIANTS
            ]
        return cls._compiled

    @classmethod
    def normalize(cls, text: str) -> str:
        """Return text with all phonetic variants collapsed to their canonical form."""
        for pattern, canonical in cls._get_compiled():
            text = pattern.sub(canonical, text)
        return text


# ─── PII Redaction ────────────────────────────────────────────────────────────

class PIIRedactor:
    """Strips personally identifiable information from a message string."""

    # Indian & international phone numbers
    _PHONE = re.compile(
        r"(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}"
    )
    # UPI IDs  e.g. someone@okaxis, abc.def@paytm
    _UPI = re.compile(r"[a-zA-Z0-9.\-_]{2,256}@[a-zA-Z]{2,64}")
    # Passwords — very rough heuristic: "password is X" / "pwd: X"
    _PASSWORD = re.compile(
        r"(?:password|pwd|passcode|pin)\s*(?:is|:)\s*\S+",
        re.IGNORECASE,
    )
    # Aadhaar-like 12-digit numbers
    _AADHAAR = re.compile(r"\b\d{4}\s\d{4}\s\d{4}\b")
    # Addresses with "flat/house/block" keywords
    _ADDRESS = re.compile(
        r"\b(?:flat|house|plot|block|sector|near|opposite|opp\.?)\b.{0,80}",
        re.IGNORECASE,
    )

    @classmethod
    def redact(cls, text: str) -> str:
        text = cls._PHONE.sub("[PHONE_REDACTED]", text)
        text = cls._UPI.sub("[UPI_REDACTED]", text)
        text = cls._PASSWORD.sub("[PASSWORD_REDACTED]", text)
        text = cls._AADHAAR.sub("[AADHAAR_REDACTED]", text)
        text = cls._ADDRESS.sub("[ADDRESS_REDACTED]", text)
        return text.strip()


# ─── WhatsApp Parser ──────────────────────────────────────────────────────────

class ChatParser:
    """
    Parses WhatsApp text exports and Telegram JSON exports into a flat list
    of {'sender': str, 'text': str} dicts with PII already redacted.
    """

    # Covers:
    # 1. Android: "12/31/23, 5:30 PM - Sender: Message" or "31/12/2023, 15:30 - Sender: Message"
    # 2. iOS: "[31/12/23, 5:30:05 PM] Sender: Message" or "[12/31/2023, 15:30:05] Sender: Message"
    # Also handles narrow non-breaking space (\u202f, \xa0) common in phone exports
    WHATSAPP_REGEX = re.compile(
        r"^(?:\[)?(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4},?\s+[\d:.]+(?:[\s\u202f\xa0]?[apAP][mM])?)(?:\]|\s+-)?\s+([^:]+?):\s+(.*)$"
    )

    # System messages to skip
    _IGNORED_FRAGMENTS = [
        "<Media omitted>",
        "This message was deleted",
        "Messages and calls are end-to-end encrypted",
        "changed the group description",
        "changed this group",
        "added",
        "removed",
        "left",
        "created group",
        "null",
    ]

    # ── WhatsApp ──────────────────────────────────────────────────────────────

    @classmethod
    def parse_whatsapp(
        cls,
        raw_content: str,
        target_person: str,
    ) -> List[Dict[str, str]]:
        """
        Parse a WhatsApp .txt export.
        Multi-line messages are stitched together correctly.
        Returns list of {'sender': str, 'text': str}.
        """
        dialogues: List[Dict[str, str]] = []
        current_sender: Optional[str] = None
        current_lines: List[str] = []

        for line in raw_content.splitlines():
            match = cls.WHATSAPP_REGEX.match(line)
            if match:
                # Flush previous message
                if current_sender and current_lines:
                    cls._flush(dialogues, current_sender, current_lines)
                current_sender = match.group(2).strip()
                current_lines = [match.group(3).strip()]
            else:
                # Continuation of previous message
                if current_sender and line.strip():
                    current_lines.append(line.strip())

        # Flush last message
        if current_sender and current_lines:
            cls._flush(dialogues, current_sender, current_lines)

        return dialogues

    # ── Telegram ──────────────────────────────────────────────────────────────

    @classmethod
    def parse_telegram(
        cls,
        json_content: str,
        target_person: str,
    ) -> List[Dict[str, str]]:
        """
        Parse a Telegram JSON export (result.json from "Export chat history").
        Only handles personal DMs and group messages with text content.
        """
        try:
            data = json.loads(json_content)
        except json.JSONDecodeError:
            return []

        messages = data.get("messages", [])
        dialogues: List[Dict[str, str]] = []

        for msg in messages:
            if msg.get("type") != "message":
                continue
            sender = msg.get("from", "") or msg.get("actor", "")
            text_raw = msg.get("text", "")

            # text can be a list of segments or a plain string
            if isinstance(text_raw, list):
                text = " ".join(
                    seg if isinstance(seg, str) else seg.get("text", "")
                    for seg in text_raw
                )
            else:
                text = str(text_raw)

            text = text.strip()
            if not text or cls._is_ignorable(text):
                continue

            dialogues.append({
                "sender": sender,
                "text": PIIRedactor.redact(text),
            })

        return dialogues

    # ── Helpers ───────────────────────────────────────────────────────────────

    @classmethod
    def _flush(
        cls,
        dialogues: List[Dict[str, str]],
        sender: str,
        lines: List[str],
    ) -> None:
        full_text = " ".join(lines)
        if not cls._is_ignorable(full_text):
            dialogues.append({
                "sender": sender,
                "text": PIIRedactor.redact(full_text),
            })

    @classmethod
    def _is_ignorable(cls, text: str) -> bool:
        lower = text.lower()
        return any(frag.lower() in lower for frag in cls._IGNORED_FRAGMENTS)
