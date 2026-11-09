# Persona Chat AI 🤖

A FastAPI backend that impersonates a real person's WhatsApp texting style using **Gemini 2.5 Flash** + **ChromaDB** few-shot retrieval. Upload a chat export, and the system learns to reply in that person's authentic Hinglish voice — including their slang, casing habits, and burst-message cadence.

---

## Features

| Feature | Description |
|---|---|
| 🔤 **Hinglish Token Harmonizer** | Normalises phonetic variants (`kyun/kyu/kyuu`) so vector search never misses a match |
| 💬 **Typing Burst Simulation** | Replies arrive as 1–3 short messages with realistic 100–400ms per-burst delays |
| 🔒 **PII Redaction Engine** | Strips phones, UPI IDs, Aadhaar, passwords, and addresses before any data is stored |
| ✍️ **Typing Imperfection Injector** | Enforces target's casing rules (lowercase-dominant, no trailing periods, etc.) |
| 📊 **Slang & Catchphrase Bank** | Tracks recurrence rates of signature vocab and injects it if under-represented |

---

## Project Structure

```
persona-chat-ai/
├── app/
│   ├── config.py           # Pydantic-Settings env config
│   ├── main.py             # FastAPI app + CORS + health check
│   ├── api/routes.py       # All HTTP endpoints
│   ├── core/
│   │   ├── parser.py       # WhatsApp/Telegram parser + PII + Harmonizer
│   │   ├── profiler.py     # Gemini persona profiler + SlangTracker
│   │   ├── vector_store.py # ChromaDB wrapper
│   │   └── generator.py    # LLM pipeline + post-processing
│   └── models/schemas.py   # Pydantic request/response models
├── data/
│   ├── uploads/            # Raw exports (gitignored)
│   ├── vector_db/          # ChromaDB (gitignored)
│   └── persona_profile.json
├── tests/
│   ├── test_parser.py
│   └── test_chat.py
├── .env.example
├── Dockerfile
└── requirements.txt
```

---

## Quick Start

### 1. Prerequisites

- Python 3.11+
- A [Gemini API key](https://aistudio.google.com/app/apikey)

### 2. Install

```bash
cd persona-chat-ai
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
# Edit .env and set GEMINI_API_KEY and PERSONA_NAME
```

### 4. Run

```bash
uvicorn app.main:app --reload --port 8000
```

Interactive docs: http://localhost:8000/docs

---

## API Endpoints

### `POST /api/upload-chat`

Upload a WhatsApp or Telegram export to index the persona.

```bash
curl -X POST http://localhost:8000/api/upload-chat \
  -F "file=@/path/to/WhatsApp Chat with Rahul.txt" \
  -F "target_person=Rahul" \
  -F "format=whatsapp" \
  -F "auto_profile=true"
```

**Response:**
```json
{
  "status": "success",
  "parsed_messages": 1842,
  "indexed_pairs": 412,
  "target_person": "Rahul"
}
```

---

### `POST /api/chat`

Get a burst reply with typing delays.

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "bhai aaj kya plan hai",
    "history": []
  }'
```

**Response:**
```json
{
  "messages": ["arre yaar", "soch raha tha ghar pe hi rahu", "kuch sorted nahi hai abhi"],
  "delays_ms": [152, 284, 340]
}
```

> The frontend should show `messages[0]` after `delays_ms[0]` ms, `messages[1]` after `delays_ms[1]` ms, and so on.

---

### `GET /api/persona-status`

Check indexing and profile state.

```bash
curl http://localhost:8000/api/persona-status
```

---

### `POST /api/profile`

Force-regenerate the persona profile from a new export.

```bash
curl -X POST http://localhost:8000/api/profile \
  -F "file=@/path/to/chat.txt" \
  -F "target_person=Rahul" \
  -F "format=whatsapp"
```

---

## WhatsApp Export Format

1. Open WhatsApp → Chat → ⋮ → **More → Export Chat**
2. Choose **Without Media**
3. The downloaded `.txt` file is what you upload

## Telegram Export Format

1. Open Telegram Desktop → Chat → ⋮ → **Export Chat History**
2. Choose **JSON format** and deselect media
3. Upload the `result.json` file with `format=telegram`

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Docker

```bash
docker build -t persona-chat-ai .
docker run -p 8000:8000 \
  -e GEMINI_API_KEY=your_key \
  -e PERSONA_NAME=Rahul \
  -v $(pwd)/data:/app/data \
  persona-chat-ai
```

---

## Privacy Notes

- All PII (phone numbers, UPI IDs, Aadhaar, passwords, addresses) is redacted **before** any text is embedded or stored in ChromaDB.
- The `data/uploads/` and `data/vector_db/` directories are gitignored by default.
- The persona profile (`data/persona_profile.json`) contains extracted behavioral patterns — **no raw message text**.
