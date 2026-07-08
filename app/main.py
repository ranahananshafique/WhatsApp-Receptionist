"""
FastAPI application – WhatsApp webhook receiver and missed-call endpoint.

Routes:
  GET  /webhook      → Meta webhook verification handshake
  POST /webhook      → Incoming WhatsApp message handler
  POST /missed-call  → Trigger a template message for missed calls
  GET  /health       → Simple health-check
  GET  /bookings/{phone}  → View bookings for a phone (debug helper)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Form
from fastapi.responses import JSONResponse, PlainTextResponse

from app import database as db
from app.config import TWILIO_ACCOUNT_SID
from app.llm_client import detect_language, extract_booking, generate_reply, strip_booking_json
from app.models import MissedCallRequest
from app.whatsapp import send_template_message, send_text_message

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
)
logger = logging.getLogger(__name__)


# ── App lifespan (DB init) ───────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database on startup."""
    db.init_db()
    logger.info("Database initialised at %s", db.DB_PATH)
    yield


# ── FastAPI instance ─────────────────────────────────────────────────
app = FastAPI(
    title="Apex Clinic – WhatsApp AI Receptionist",
    version="1.0.0",
    lifespan=lifespan,
)


# ══════════════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["ops"])
async def health_check():
    return {"status": "ok", "service": "whatsapp-receptionist"}


# ══════════════════════════════════════════════════════════════════════
#  WHATSAPP WEBHOOK – TWILIO VERIFICATION (NOT NEEDED FOR SANDBOX)
# ══════════════════════════════════════════════════════════════════════
# Twilio does not require a GET verification handshake like Meta.


# ══════════════════════════════════════════════════════════════════════
#  WHATSAPP WEBHOOK – INCOMING MESSAGES (POST)
# ══════════════════════════════════════════════════════════════════════

@app.post("/webhook", tags=["whatsapp"])
async def receive_message(
    From: str = Form(None),
    Body: str = Form(None)
):
    """
    Process incoming WhatsApp messages from Twilio API:
      1. Parse Form payload to extract From and Body.
      2. Load conversation history from SQLite.
      3. Detect language & call the LLM.
      4. Check if the LLM reply contains a booking intent (BOOKING_JSON).
      5. If yes → create mock booking, append confirmation.
      6. Persist messages and send the reply back via Twilio API.
    """
    if not From or not Body:
        logger.warning("Failed to parse Twilio payload: missing From or Body")
        return PlainTextResponse(content="Missing data", status_code=400)
    
    # Clean up phone number (Twilio sends whatsapp:+1234567890)
    phone = From.replace("whatsapp:", "").lstrip("+")
    user_text = Body.strip()

    logger.info("Incoming from %s: %s", phone, user_text[:120])

    # ── 1. History + language ─────────────────────────────
    history = db.get_history(phone)
    language = detect_language(user_text)

    # ── 2. LLM call ──────────────────────────────────────
    raw_reply = await generate_reply(history, user_text, language)
    logger.info("LLM raw reply: %s", raw_reply[:200])

    # ── 3. Booking extraction ────────────────────────────
    booking = extract_booking(raw_reply)
    display_reply = strip_booking_json(raw_reply)

    if booking:
        logger.info("Booking detected: %s", booking)
        result = db.create_mock_booking(
            phone=phone,
            service=booking["service"],
            date=booking["date"],
            time=booking["time"],
        )
        if language == "ar":
            confirmation = (
                f"✅ تم تأكيد حجزك!\n"
                f"📋 الخدمة: {result['service']}\n"
                f"📅 التاريخ: {result['date']}\n"
                f"🕐 الوقت: {result['time']}\n"
                f"🔖 رقم الحجز: #{result['booking_id']}"
            )
        else:
            confirmation = (
                f"✅ Your booking is confirmed!\n"
                f"📋 Service: {result['service']}\n"
                f"📅 Date: {result['date']}\n"
                f"🕐 Time: {result['time']}\n"
                f"🔖 Booking ID: #{result['booking_id']}"
            )
        display_reply = f"{display_reply}\n\n{confirmation}" if display_reply else confirmation

    # ── 4. Persist & send ────────────────────────────────
    db.save_message(phone, "user", user_text)
    db.save_message(phone, "assistant", display_reply)

    await send_text_message(phone, display_reply)

    return JSONResponse({"status": "ok"})


# ══════════════════════════════════════════════════════════════════════
#  MISSED-CALL FOLLOW-UP ENDPOINT
# ══════════════════════════════════════════════════════════════════════

@app.post("/missed-call", tags=["whatsapp"])
async def missed_call_followup(body: MissedCallRequest):
    """
    Accepts ``{"phone_number": "+971..."}`` and sends a pre-approved
    WhatsApp template message initiating the chat.

    In production the template would be registered in Meta's dashboard.
    For the MVP we also send a fallback text message so the flow can be
    tested end-to-end without an approved template.
    """
    phone = body.phone_number.strip().lstrip("+")
    logger.info("Missed-call follow-up triggered for %s", phone)

    # Attempt to send template (will fail in mock/dev without an approved template)
    template_result = await send_template_message(to=phone)

    # Fallback: send a plain text message for local testing
    fallback_text = (
        "Hi! 👋 We noticed we missed a call from you. "
        "How can Apex Clinic help you today?"
    )
    text_result = await send_text_message(to=phone, body=fallback_text)

    return JSONResponse(
        {
            "status": "sent",
            "phone": phone,
            "template_result": template_result,
            "text_fallback_result": text_result,
        }
    )


# ══════════════════════════════════════════════════════════════════════
#  DEBUG / ADMIN HELPERS
# ══════════════════════════════════════════════════════════════════════

@app.get("/bookings/{phone}", tags=["admin"])
async def list_bookings(phone: str):
    """Return all bookings for a phone number (debug helper)."""
    bookings = db.get_bookings(phone)
    return {"phone": phone, "bookings": bookings}


@app.get("/history/{phone}", tags=["admin"])
async def list_history(phone: str):
    """Return conversation history for a phone number (debug helper)."""
    history = db.get_history(phone)
    return {"phone": phone, "history": history}
