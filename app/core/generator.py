"""
app/core/generator.py
======================
PersonaEngine — the LLM pipeline responsible for:

  1. Building a dynamic system prompt from the cached PersonaProfile.
  2. Injecting few-shot examples retrieved from ChromaDB.
  3. Calling Gemini 2.5 Flash with JSON-mode to get burst messages.
  4. Post-processing via ImperfectionInjector (casing, punctuation, typos).
  5. Enforcing Slang Recurrence (adds signature slang if under-represented).
  6. Computing per-burst Typing Cadence delays (100–400 ms, proportional
     to message length with a small random jitter).

Returns: (messages: List[str], delays_ms: List[int])
"""
from __future__ import annotations

import json
import random
import re
from typing import Any, List, Optional, Tuple

# google-genai is imported lazily inside PersonaEngine.__init__ to avoid
# conflicts with the global `google` namespace package when running tests
# in environments where google-cloud packages are also installed.

from app.models.schemas import PersonaProfile


# ─── Typing Imperfection Injector ────────────────────────────────────────────

class ImperfectionInjector:
    """
    Post-processes LLM output to match the target's casing and punctuation
    habits extracted from their PersonaProfile.
    """

    def __init__(self, profile: PersonaProfile):
        self.profile = profile
        self._casing_lower = "lowercase" in profile.casing.lower()
        self._no_periods = (
            "no period" in profile.casing.lower()
            or "no full stop" in profile.casing.lower()
            or "rarely uses full stop" in profile.casing.lower()
            or "no trailing" in profile.casing.lower()
        )
        self._no_exclamation = "no !" in profile.casing.lower()

    def apply(self, text: str) -> str:
        """Apply casing & punctuation rules to a single burst message."""
        # Casing
        if self._casing_lower:
            text = text.lower()
        else:
            # Sentence-case: capitalise first letter only
            text = text[:1].upper() + text[1:] if text else text

        # Trailing punctuation
        if self._no_periods and text.endswith("."):
            text = text[:-1]
        if self._no_exclamation and text.endswith("!"):
            text = text[:-1]

        return text.strip()


# ─── Slang Recurrence Enforcer ────────────────────────────────────────────────

class SlangEnforcer:
    """
    Checks whether signature slang appears at least once per N messages
    (based on the stored per-100 rate) and optionally injects it.
    """

    # Minimum rate (per 100 msgs) before we consider injecting
    INJECT_THRESHOLD = 5.0

    def __init__(self, profile: PersonaProfile):
        self.profile = profile
        # Build ordered list: slang tokens with a meaningful recurrence rate
        self._candidates = [
            token
            for token in profile.slang
            if profile.slang_frequencies.get(token, 0) >= self.INJECT_THRESHOLD
        ]

    def enforce(self, messages: List[str]) -> List[str]:
        """
        If none of the signature slang tokens appear across all burst messages,
        prepend the most frequent one naturally to the first message.
        """
        if not self._candidates:
            return messages

        combined = " ".join(messages).lower()
        present = any(
            re.search(rf"\b{re.escape(token)}\b", combined)
            for token in self._candidates
        )

        if present:
            return messages

        # Inject the top-frequency slang naturally at the start of msg[0]
        top_token = self._candidates[0]
        messages = list(messages)  # don't mutate caller's list
        messages[0] = f"{top_token} {messages[0]}"
        return messages


# ─── Typing Cadence Calculator ────────────────────────────────────────────────

def _compute_delays(messages: List[str]) -> List[int]:
    """
    Return one delay_ms per message: a base proportional to char length
    (simulating typing speed) plus random jitter in [100, 400] ms range.
    """
    delays = []
    for msg in messages:
        # ~40 ms per character, bounded between 100 and 400 ms
        base = min(max(int(len(msg) * 40), 100), 400)
        jitter = random.randint(-40, 60)
        delays.append(max(100, min(400, base + jitter)))
    return delays


# ─── Persona Engine ───────────────────────────────────────────────────────────

class PersonaEngine:
    """
    Orchestrates the full reply generation pipeline:
    vector retrieval → prompt assembly → Gemini call → post-processing.
    """

    MODEL = "gemini-2.5-flash"

    def __init__(
        self,
        api_key: str,
        persona_profile_path: str = "./data/persona_profile.json",
    ):
        # Lazy import to avoid google namespace collision at module level
        try:
            from google import genai as _genai  # type: ignore[import]
            self.client: Any = _genai.Client(api_key=api_key)
        except ImportError as exc:
            raise ImportError(
                "google-genai is not installed. Run: pip install google-genai"
            ) from exc
        self.profile = self._load_profile(persona_profile_path)
        self.injector = ImperfectionInjector(self.profile)
        self.enforcer = SlangEnforcer(self.profile)

    # ── Profile loading ───────────────────────────────────────────────────────

    def _load_profile(self, path: str) -> PersonaProfile:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return PersonaProfile(**data)
        except (FileNotFoundError, Exception):
            # Safe fallback defaults
            return PersonaProfile(
                hinglish_ratio="60% Hindi Latin script, 40% English",
                slang=["bhai", "yaar", "scene", "sorted", "haan", "matlab", "arre", "chal"],
                casing="mostly lowercase, rarely uses full stops",
                tone="casual, frank, conversational",
                slang_frequencies={},
            )

    def reload_profile(self, path: str) -> None:
        """Hot-reload the profile (called after /api/profile regeneration)."""
        self.profile = self._load_profile(path)
        self.injector = ImperfectionInjector(self.profile)
        self.enforcer = SlangEnforcer(self.profile)

    # ── Main generation ───────────────────────────────────────────────────────

    def generate_reply(
        self,
        user_message: str,
        few_shot_pairs: List[dict],
        chat_history: List[dict],
    ) -> Tuple[List[str], List[int]]:
        """
        Generate burst messages + per-burst delays.

        Returns
        -------
        (messages, delays_ms) — parallel lists, one entry per burst segment.
        """
        p = self.profile

        # ── System instruction ─────────────────────────────────────────────
        persona_display = f"{p.name} (a real human)" if p.name else "a real human"
        system_instruction = f"""You are roleplaying as {persona_display} texting on WhatsApp.

PERSONA PROFILE:
- Language: Authentic Indian Hinglish ({p.hinglish_ratio}).
- Typical Slang & Fillers: {", ".join(p.slang)}.
- Casing & Punctuation Style: {p.casing}.
- Conversational Tone: {p.tone}.

CRITICAL OUTPUT RULES:
1. Humans rarely send one big paragraph. Split your reply into 1 to 3 SHORT burst messages just like real WhatsApp texting.
2. Each burst should feel like a separate send — short, punchy, natural.
3. Honour the persona's casing and punctuation habits exactly.
4. Mix Hindi (written in Latin script) and English naturally — do NOT write in Devanagari.
5. NEVER break character. NEVER say you are an AI.
6. Return ONLY a raw JSON array of strings, e.g.: ["bhai ruk", "dekh ke batata hu"]
7. No extra keys, no explanation, no markdown — just the JSON array."""

        # ── Few-shot block ─────────────────────────────────────────────────
        examples_str = ""
        if few_shot_pairs:
            examples_str = "### How you typically respond:\n"
            for pair in few_shot_pairs:
                examples_str += f'User: {pair["query"]}\nYou: {pair["response"]}\n\n'

        # ── History block ──────────────────────────────────────────────────
        history_str = ""
        if chat_history:
            history_str = "### Recent conversation:\n"
            for turn in chat_history[-6:]:
                role = "User" if turn.get("role") == "user" else "You"
                history_str += f'{role}: {turn.get("content", "")}\n'

        prompt = f"""{examples_str}{history_str}
User: {user_message}
You:"""

        # ── Gemini call with fallback chain ─────────────────────────────────
        models_to_try = [self.MODEL, "gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash-lite"]
        response = None
        last_error = None

        for model_name in models_to_try:
            try:
                response = self.client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config={
                        "system_instruction": system_instruction,
                        "response_mime_type": "application/json",
                        "temperature": 0.85,
                    },
                )
                if response and response.text:
                    break
            except Exception as exc:
                last_error = exc
                print(f"[PersonaEngine] Model {model_name} error: {exc}. Trying next fallback...")
                continue

        # ── Parse burst messages ───────────────────────────────────────────
        messages: List[str] = []
        if response and response.text:
            try:
                raw_text = response.text.strip()
                parsed = json.loads(raw_text)
                if isinstance(parsed, list):
                    messages = [str(m) for m in parsed[:3] if str(m).strip()]
                elif isinstance(parsed, dict) and "messages" in parsed:
                    messages = [str(m) for m in parsed["messages"][:3] if str(m).strip()]
                elif isinstance(parsed, str):
                    messages = [parsed]
            except Exception:
                messages = [response.text.strip()]

        # Graceful fallback: If all models failed (e.g. rate limit), use top vector retrieved response
        if not messages:
            if few_shot_pairs:
                top_resp = few_shot_pairs[0]["response"]
                messages = [top_resp]
            else:
                messages = ["arre yaar", "ek min ruk"]

        # ── Post-processing ────────────────────────────────────────────────
        messages = [self.injector.apply(m) for m in messages]
        messages = self.enforcer.enforce(messages)

        # ── Typing delays ──────────────────────────────────────────────────
        delays_ms = _compute_delays(messages)

        return messages, delays_ms
