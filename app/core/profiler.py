"""
app/core/profiler.py
=====================
• generate_profile() — sends sample messages to Gemini and produces a
  structured PersonaProfile JSON saved to disk.
• SlangTracker — counts token frequency in the target person's messages
  and computes a recurrence rate (occurrences per 100 messages).
"""
from __future__ import annotations

import json
import re
from collections import Counter
from typing import Dict, List

# google-genai imported lazily inside generate_profile() to avoid
# global google namespace package conflicts during test collection.

from app.models.schemas import PersonaProfile


# ─── Slang Tracker ────────────────────────────────────────────────────────────

class SlangTracker:
    """
    Tracks how often signature vocabulary appears across the target's messages
    so the generator can enforce authentic recurrence rates.
    """

    # Common Hinglish filler / slang tokens to always track
    DEFAULT_WATCHLIST = [
        "bhai", "yaar", "scene", "sorted", "matlab", "arre", "haan",
        "nahi", "bas", "chal", "sahi", "dekh", "kyun", "kya", "abhi",
        "kal", "theek", "lol", "ok", "bro", "bc",
    ]

    def __init__(self, watchlist: List[str] | None = None):
        self.watchlist = [w.lower() for w in (watchlist or self.DEFAULT_WATCHLIST)]
        self._counter: Counter = Counter()
        self._total_messages = 0

    def ingest(self, messages: List[str]) -> None:
        """Feed all messages from the target person into the tracker."""
        self._total_messages += len(messages)
        for msg in messages:
            tokens = re.findall(r"\b\w+\b", msg.lower())
            for token in tokens:
                if token in self.watchlist:
                    self._counter[token] += 1

    def frequencies_per_100(self) -> Dict[str, float]:
        """Return occurrences per 100 messages for each tracked token."""
        if self._total_messages == 0:
            return {}
        return {
            token: round(count / self._total_messages * 100, 2)
            for token, count in self._counter.most_common()
        }

    def top_slang(self, n: int = 12) -> List[str]:
        """Return the top-n most frequent slang tokens."""
        return [token for token, _ in self._counter.most_common(n)]


# ─── Profile Generator ────────────────────────────────────────────────────────

def generate_profile(
    dialogues: list,
    target_person: str,
    api_key: str,
    output_path: str = "./data/persona_profile.json",
) -> PersonaProfile:
    """
    Analyses the target person's messages with Gemini and writes a
    PersonaProfile JSON to output_path.

    Parameters
    ----------
    dialogues   : parsed dialogue list [{"sender":..., "text":...}]
    target_person: display name of the person to profile
    api_key     : Gemini API key
    output_path : where to write persona_profile.json
    """
    # ── 1. Filter messages to only the target person ───────────────────────
    target_msgs = [
        d["text"]
        for d in dialogues
        if d.get("sender", "").strip().lower() == target_person.strip().lower()
    ]

    if not target_msgs:
        raise ValueError(
            f"No messages found for '{target_person}' in the provided dialogues."
        )

    # ── 2. SlangTracker pass ───────────────────────────────────────────────
    tracker = SlangTracker()
    tracker.ingest(target_msgs)
    freq_map = tracker.frequencies_per_100()
    top_slang = tracker.top_slang(12)

    # ── 3. Sample up to 300 messages for Gemini analysis ──────────────────
    sample_text = "\n".join(target_msgs[:300])

    prompt = f"""Analyze these messages sent by one person:
\"\"\"{sample_text}\"\"\"

Return a JSON object with EXACTLY these keys:
- "hinglish_ratio": string — estimated split between Hindi (Latin script) and English (e.g. "65% Hindi, 35% English")
- "slang": list of 8-12 top recurring slang terms or verbal fillers this person uses
- "casing": string — describe capitalization habits, e.g. "always lowercase, never uses periods, uses '?' rarely"
- "tone": string — a short 1-2 sentence summary of the persona's conversational vibe

Only return valid JSON, no extra text."""

    from google import genai as _genai  # lazy import — avoids google namespace collision
    client = _genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config={"response_mime_type": "application/json"},
    )

    raw = response.text.strip()

    # ── 4. Parse & enrich with SlangTracker data ──────────────────────────
    try:
        profile_dict = json.loads(raw)
    except json.JSONDecodeError:
        # Fallback to safe defaults if Gemini returns something unexpected
        profile_dict = {
            "hinglish_ratio": "60% Hindi, 40% English",
            "slang": top_slang,
            "casing": "mostly lowercase",
            "tone": "casual and conversational",
        }

    # Merge: use LLM slang if available, supplement with tracker top terms
    llm_slang: List[str] = profile_dict.get("slang", [])
    merged_slang = list(dict.fromkeys(llm_slang + top_slang))[:12]
    profile_dict["name"] = target_person
    profile_dict["slang"] = merged_slang
    profile_dict["slang_frequencies"] = freq_map

    profile = PersonaProfile(**profile_dict)

    # ── 5. Write to disk ──────────────────────────────────────────────────
    import os
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(profile.model_dump_json(indent=2))

    return profile
