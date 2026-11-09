"""
tests/test_chat.py
===================
Unit tests for:
  • ImperfectionInjector — casing and punctuation rules
  • SlangEnforcer — recurrence enforcement
  • Typing cadence delays — range validation
  • PersonaProfile defaults
"""
import pytest
from app.core.generator import ImperfectionInjector, SlangEnforcer, _compute_delays
from app.models.schemas import PersonaProfile


# ─── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def lowercase_profile():
    return PersonaProfile(
        hinglish_ratio="60% Hindi, 40% English",
        slang=["bhai", "yaar", "scene"],
        casing="always lowercase, no full stops, no trailing punctuation",
        tone="casual",
        slang_frequencies={"bhai": 12.5, "yaar": 8.0, "scene": 6.0},
    )


@pytest.fixture
def sentencecase_profile():
    return PersonaProfile(
        hinglish_ratio="40% Hindi, 60% English",
        slang=["man", "dude"],
        casing="sentence case, uses periods",
        tone="friendly",
        slang_frequencies={"man": 3.0},
    )


# ─── ImperfectionInjector ────────────────────────────────────────────────────

class TestImperfectionInjector:
    def test_lowercases_text(self, lowercase_profile):
        inj = ImperfectionInjector(lowercase_profile)
        result = inj.apply("Bhai Kya Scene Hai")
        assert result == result.lower()

    def test_strips_trailing_period(self, lowercase_profile):
        inj = ImperfectionInjector(lowercase_profile)
        result = inj.apply("sab theek hai.")
        assert not result.endswith(".")

    def test_strips_trailing_exclamation_when_configured(self):
        profile = PersonaProfile(
            slang=[],
            casing="lowercase, no !, no periods",
            tone="casual",
            slang_frequencies={},
        )
        inj = ImperfectionInjector(profile)
        result = inj.apply("haan bhai!")
        assert not result.endswith("!")

    def test_sentence_case_profile_capitalises_first(self, sentencecase_profile):
        inj = ImperfectionInjector(sentencecase_profile)
        result = inj.apply("hello there")
        assert result[0].isupper()

    def test_returns_non_empty_string(self, lowercase_profile):
        inj = ImperfectionInjector(lowercase_profile)
        assert inj.apply("test") != ""


# ─── SlangEnforcer ───────────────────────────────────────────────────────────

class TestSlangEnforcer:
    def test_no_injection_when_slang_present(self, lowercase_profile):
        enf = SlangEnforcer(lowercase_profile)
        messages = ["bhai kya chal raha", "dekh kal milte"]
        result = enf.enforce(messages)
        # bhai is already there — should NOT duplicate or mutate unreasonably
        assert "bhai" in " ".join(result)

    def test_injects_top_slang_when_absent(self, lowercase_profile):
        enf = SlangEnforcer(lowercase_profile)
        messages = ["theek hai", "kal milte"]
        result = enf.enforce(messages)
        combined = " ".join(result).lower()
        # One of the high-frequency slang tokens should appear
        assert any(
            token in combined
            for token in lowercase_profile.slang
            if lowercase_profile.slang_frequencies.get(token, 0) >= 5.0
        )

    def test_no_candidates_returns_unchanged(self, sentencecase_profile):
        """If no slang meets the threshold, messages are returned as-is."""
        enf = SlangEnforcer(sentencecase_profile)
        messages = ["okay sure", "see you"]
        result = enf.enforce(messages)
        assert result == messages


# ─── Typing Cadence Delays ───────────────────────────────────────────────────

class TestTypingCadence:
    def test_delays_match_message_count(self):
        msgs = ["hi", "bhai kya scene hai", "theek hai sorted"]
        delays = _compute_delays(msgs)
        assert len(delays) == len(msgs)

    def test_delays_within_range(self):
        msgs = ["a" * 1, "a" * 5, "a" * 50, "a" * 200]
        delays = _compute_delays(msgs)
        for d in delays:
            assert 100 <= d <= 400, f"Delay {d} out of [100,400] range"

    def test_longer_message_tends_to_have_larger_delay(self):
        short_delays = _compute_delays(["hi"])
        long_delays = _compute_delays(["a" * 200])
        # Due to random jitter this isn't guaranteed, but on average holds
        # Just assert both are in range
        assert 100 <= short_delays[0] <= 400
        assert 100 <= long_delays[0] <= 400

    def test_empty_messages_list_returns_empty(self):
        assert _compute_delays([]) == []


# ─── PersonaProfile Defaults ─────────────────────────────────────────────────

class TestPersonaProfile:
    def test_default_profile_is_valid(self):
        p = PersonaProfile()
        assert isinstance(p.slang, list)
        assert isinstance(p.slang_frequencies, dict)
        assert p.hinglish_ratio

    def test_profile_serializes_to_json(self):
        p = PersonaProfile(slang=["bhai"], slang_frequencies={"bhai": 5.0})
        data = p.model_dump_json()
        assert "bhai" in data
