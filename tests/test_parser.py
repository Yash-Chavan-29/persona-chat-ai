"""
tests/test_parser.py
=====================
Unit tests for:
  • WhatsApp multi-line message parsing
  • PII redaction (phone, UPI, address, password)
  • Ignorable system message filtering
  • Hinglish Token Harmonizer normalization
  • Telegram JSON parsing
"""
import pytest
from app.core.parser import ChatParser, HinglishHarmonizer, PIIRedactor


# ─── WhatsApp Parsing ─────────────────────────────────────────────────────────

SAMPLE_WA = """1/1/24, 10:00 AM - Rahul: bhai kya scene hai
1/1/24, 10:01 AM - Priya: sab sorted hai yaar
dont worry
1/1/24, 10:02 AM - Rahul: arre achha
1/1/24, 10:03 AM - Priya: haan sahi hai
1/1/24, 10:04 AM - Priya: <Media omitted>
1/1/24, 10:05 AM - Priya: This message was deleted
"""


def test_whatsapp_parses_basic_messages():
    dialogues = ChatParser.parse_whatsapp(SAMPLE_WA, target_person="Priya")
    senders = [d["sender"] for d in dialogues]
    assert "Rahul" in senders
    assert "Priya" in senders


def test_whatsapp_multiline_stitching():
    """Multi-line continuation should be joined into one message."""
    dialogues = ChatParser.parse_whatsapp(SAMPLE_WA, target_person="Priya")
    priya_msgs = [d["text"] for d in dialogues if d["sender"] == "Priya"]
    # "sab sorted hai yaar dont worry" should be one message
    stitched = any("dont worry" in m for m in priya_msgs)
    assert stitched, f"Expected stitched message, got: {priya_msgs}"


def test_whatsapp_ignores_media_and_deleted():
    dialogues = ChatParser.parse_whatsapp(SAMPLE_WA, target_person="Priya")
    texts = [d["text"] for d in dialogues]
    assert not any("<Media omitted>" in t for t in texts)
    assert not any("This message was deleted" in t for t in texts)


# ─── PII Redaction ─────────────────────────────────────────────────────────────

class TestPIIRedactor:
    def test_phone_redacted(self):
        result = PIIRedactor.redact("call me on +91-9876543210 ok?")
        assert "[PHONE_REDACTED]" in result
        assert "9876543210" not in result

    def test_upi_redacted(self):
        result = PIIRedactor.redact("send to rahul@okaxis please")
        assert "[UPI_REDACTED]" in result

    def test_password_redacted(self):
        result = PIIRedactor.redact("password is hunter2")
        assert "[PASSWORD_REDACTED]" in result

    def test_clean_text_unchanged(self):
        clean = "bhai kya scene hai"
        assert PIIRedactor.redact(clean) == clean

    def test_aadhaar_redacted(self):
        result = PIIRedactor.redact("mera aadhaar 1234 5678 9012 hai")
        assert "[AADHAAR_REDACTED]" in result


# ─── Hinglish Token Harmonizer ───────────────────────────────────────────────

class TestHinglishHarmonizer:
    def test_kyun_variants(self):
        for variant in ["kyu", "kyuu", "kyun"]:
            assert HinglishHarmonizer.normalize(variant) == "kyun"

    def test_nahi_variants(self):
        for variant in ["nhi", "nai"]:
            result = HinglishHarmonizer.normalize(variant)
            assert result == "nahi", f"{variant!r} → {result!r}"

    def test_haan_variants(self):
        for variant in ["han", "hna", "haan"]:
            result = HinglishHarmonizer.normalize(variant)
            assert result == "haan", f"{variant!r} → {result!r}"

    def test_yaar_variants(self):
        assert HinglishHarmonizer.normalize("yar") == "yaar"

    def test_numeric_ek(self):
        result = HinglishHarmonizer.normalize("send me 1 message")
        assert "ek" in result

    def test_ok_variants(self):
        for variant in ["ok", "okay", "okk", "okkk"]:
            result = HinglishHarmonizer.normalize(variant)
            assert result == "ok", f"{variant!r} → {result!r}"

    def test_unrelated_words_unchanged(self):
        text = "python is awesome"
        assert HinglishHarmonizer.normalize(text) == text


# ─── Telegram Parsing ─────────────────────────────────────────────────────────

TELEGRAM_JSON = """{
  "messages": [
    {"type": "message", "from": "Rahul", "text": "bhai kya chal raha"},
    {"type": "message", "from": "Priya", "text": "sab theek hai"},
    {"type": "service", "from": "Priya", "text": "Priya joined the group"},
    {"type": "message", "from": "Rahul", "text": [{"type": "bold", "text": "dekh"}, " ye link"]},
    {"type": "message", "from": "Priya", "text": ""}
  ]
}"""


def test_telegram_parses_messages():
    dialogues = ChatParser.parse_telegram(TELEGRAM_JSON, target_person="Priya")
    senders = [d["sender"] for d in dialogues]
    assert "Rahul" in senders
    assert "Priya" in senders


def test_telegram_skips_service_messages():
    dialogues = ChatParser.parse_telegram(TELEGRAM_JSON, target_person="Priya")
    texts = [d["text"] for d in dialogues]
    assert not any("joined the group" in t for t in texts)


def test_telegram_handles_list_text():
    dialogues = ChatParser.parse_telegram(TELEGRAM_JSON, target_person="Priya")
    texts = [d["text"] for d in dialogues]
    assert any("dekh" in t for t in texts)


def test_telegram_skips_empty_messages():
    dialogues = ChatParser.parse_telegram(TELEGRAM_JSON, target_person="Priya")
    texts = [d["text"] for d in dialogues]
    assert not any(t == "" for t in texts)
