# 🏥 Apex Clinic – WhatsApp AI Receptionist

A production-ready MVP for a **bilingual (English / Arabic)** WhatsApp AI receptionist powered by a locally running **Qwen 2.5 3B** model, **FastAPI**, and **SQLite**.

---

## ✨ Features

| Feature | Description |
|---|---|
| **WhatsApp Webhook** | Handles Twilio incoming messages (POST) |
| **Bilingual Support** | Auto-detects Arabic vs English and responds in the same language |
| **Session Memory** | Last 10 messages per user stored in SQLite for contextual replies |
| **Guardrailed LLM** | Strict system prompt with fixed business info (services, prices, hours) |
| **Smart Booking** | Extracts service + date + time from conversation → saves to SQLite |
| **Missed-Call Follow-up** | `/missed-call` endpoint sends a template + fallback text message |
| **Debug Endpoints** | `/bookings/{phone}` and `/history/{phone}` for inspection |

---

## 📁 Project Structure

```
WhatsApp Receptionist/
├── app/
│   ├── __init__.py        # Package marker
│   ├── config.py          # Env vars, business constants
│   ├── database.py        # SQLite: conversation history & bookings
│   ├── llm_client.py      # OpenAI-compatible client → Qwen 2.5
│   ├── main.py            # FastAPI routes (webhook, missed-call, admin)
│   ├── models.py          # Pydantic models for payloads
│   └── whatsapp.py        # WhatsApp Cloud API send helpers
├── data/                  # Auto-created; holds receptionist.db
├── tests/
│   └── test_flow.py       # End-to-end mock test script
├── .env.example           # Template for environment variables
├── requirements.txt       # Python dependencies
├── run.py                 # Convenience entry-point
└── README.md              # ← You are here
```

---

## 🚀 Quick Start

### 1. Prerequisites

- **Python 3.11+**
- **Local LLM server** running Qwen 2.5 3B with an OpenAI-compatible API.
  Recommended: [Ollama](https://ollama.com) (`ollama run qwen2.5:3b`).

### 2. Install Dependencies

```bash
cd "WhatsApp Receptionist"
pip install -r requirements.txt
```

### 3. Configure Environment

```bash
copy .env.example .env
# Edit .env with your WhatsApp Cloud API credentials
```

| Variable | Description | Default |
|---|---|---|
| `TWILIO_ACCOUNT_SID` | Your Twilio Account SID | *(required)* |
| `TWILIO_AUTH_TOKEN` | Your Twilio Auth Token | *(required)* |
| `TWILIO_WHATSAPP_NUMBER` | Your Twilio Sandbox Number | *(required)* |
| `LLM_BASE_URL` | OpenAI-compatible endpoint | `http://localhost:11434/v1` |
| `LLM_MODEL` | Model name | `qwen2.5:3b` |

### 4. Start the LLM Server

```bash
# Using Ollama:
ollama run qwen2.5:3b

# Or using LM Studio / vLLM – just make sure it serves on the configured URL.
```

### 5. Run the Server

```bash
python run.py
# Server starts at http://localhost:8000
```

Or directly:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🧪 Testing with cURL

### Health Check

```bash
curl http://localhost:8000/health
```

### Simulate an Incoming WhatsApp Message (English)

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=whatsapp:+971501234567&Body=Hi, what services do you offer?&To=whatsapp:+14155238886"
```

### Simulate an Incoming WhatsApp Message (English)

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{
    "object": "whatsapp_business_account",
    "entry": [{
      "id": "BUSINESS_ID",
      "changes": [{
        "field": "messages",
        "value": {
          "messaging_product": "whatsapp",
          "contacts": [{"profile": {"name": "Test User"}, "wa_id": "971501234567"}],
          "messages": [{
            "from": "971501234567",
            "id": "wamid.test123",
            "timestamp": "1719878400",
            "type": "text",
            "text": {"body": "Hi, what services do you offer?"}
          }]
        }
      }]
    }]
  }'
```

### Simulate an Arabic Message

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=whatsapp:+971509876543&Body=مرحبا، أريد حجز موعد لتبييض الأسنان يوم الأحد الساعة ١٠ صباحاً&To=whatsapp:+14155238886"
```

### Simulate a Booking Request (English)

```bash
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=whatsapp:+971507777777&Body=I want to book a Teeth Whitening appointment on 2026-07-10 at 10:00&To=whatsapp:+14155238886"
```

### Trigger Missed-Call Follow-up

```bash
curl -X POST http://localhost:8000/missed-call \
  -H "Content-Type: application/json" \
  -d '{"phone_number": "+971501234567"}'
```

### View Bookings for a Phone Number

```bash
curl http://localhost:8000/bookings/971507777777
```

### View Conversation History

```bash
curl http://localhost:8000/history/971501234567
```

---

## 🏗️ Architecture

```
┌─────────────┐     ┌──────────────┐     ┌──────────────────┐
│  WhatsApp   │────▶│   FastAPI     │────▶│  Qwen 2.5 3B     │
│  Cloud API  │◀────│   /webhook    │◀────│  (local server)  │
└─────────────┘     └──────┬───────┘     └──────────────────┘
                           │
                    ┌──────▼───────┐
                    │   SQLite DB   │
                    │ • history     │
                    │ • bookings    │
                    └──────────────┘
```

**Message flow:**

1. Twilio sends a POST to `/webhook` with the user's message as Form Data.
2. `main.py` parses the payload, loads the last 10 messages from SQLite.
3. `llm_client.py` builds a guardrailed system prompt, calls Qwen 2.5.
4. If the LLM reply contains `BOOKING_JSON: {...}`, the booking is saved.
5. The cleaned reply (+ confirmation if booked) is sent back via Twilio API.

---

## ⚙️ Production Deployment Notes

- **Expose with ngrok** for Twilio webhook testing: `ngrok http 8000`
- **Use Gunicorn** in production: `gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker`
- **Migrate to PostgreSQL** for multi-instance concurrency (replace SQLite).
- **Setup Twilio WhatsApp Sender**: Ensure your webhook URL is set in the Twilio Console under WhatsApp Sandbox settings.

---

## 📄 License

MIT – built for Apex Clinic by QuantX.
