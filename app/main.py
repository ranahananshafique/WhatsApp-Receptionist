"""
FastAPI application – WhatsApp webhook receiver and missed-call endpoint.

Routes:
  GET  /webhook      → Meta webhook verification handshake
  POST /webhook      → Incoming WhatsApp message handler (text + interactive)
  POST /missed-call  → Trigger a template message for missed calls
  GET  /health       → Simple health-check
  GET  /bookings/{phone}  → View bookings for a phone (debug helper)

  POST /admin/complete/{booking_id}  → Mark a booking as completed (testing)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, Form
from fastapi.responses import JSONResponse, PlainTextResponse

from app import database as db
from app.config import WHATSAPP_VERIFY_TOKEN
from app.llm_client import detect_language, extract_booking, generate_reply, strip_booking_json
from app.models import MissedCallRequest
from app.whatsapp import send_text_message, send_template_message
from app.reminders import handle_confirmation, handle_pay_confirm, handle_reschedule
from app.aftercare import handle_checkin_response
from app.scheduler import start_scheduler, stop_scheduler

# ── Logging ───────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
)
logger = logging.getLogger(__name__)


# ── App lifespan (DB init + Scheduler) ───────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialise the database and start the scheduler on startup."""
    db.init_db()
    logger.info("Database initialised at %s", db.DB_PATH)
    start_scheduler()
    logger.info("Background scheduler started")
    yield
    stop_scheduler()
    logger.info("Background scheduler stopped")


# ── FastAPI instance ─────────────────────────────────────────────────
app = FastAPI(
    title="QuantX Skin Salon – WhatsApp AI Receptionist",
    version="2.0.0",
    lifespan=lifespan,
)


# ══════════════════════════════════════════════════════════════════════
#  HEALTH CHECK
# ══════════════════════════════════════════════════════════════════════

@app.get("/health", tags=["ops"])
async def health_check():
    return {"status": "ok", "service": "whatsapp-receptionist", "version": "2.0.0"}


# ══════════════════════════════════════════════════════════════════════
#  WHATSAPP WEBHOOK – VERIFICATION (GET)
# ══════════════════════════════════════════════════════════════════════

@app.get("/webhook", tags=["whatsapp"])
async def verify_webhook(
    hub_mode: str = Query("", alias="hub.mode"),
    hub_verify_token: str = Query("", alias="hub.verify_token"),
    hub_challenge: str = Query("", alias="hub.challenge"),
):
    """
    Simulate webhook verification handshake.
    We check the token matches the configured WHATSAPP_VERIFY_TOKEN.
    """
    if hub_mode == "subscribe" and hub_verify_token == WHATSAPP_VERIFY_TOKEN:
        logger.info("Webhook verified successfully")
        return PlainTextResponse(content=hub_challenge)

    logger.warning("Webhook verification failed – token mismatch")
    raise HTTPException(status_code=403, detail="Verification failed")


# ══════════════════════════════════════════════════════════════════════
#  WHATSAPP WEBHOOK – INCOMING MESSAGES (POST)
# ══════════════════════════════════════════════════════════════════════

@app.post("/webhook", tags=["whatsapp"])
async def receive_message(request: Request):
    """
    Process incoming WhatsApp messages from Meta Cloud API.

    Handles two message types:
      • ``text``        → LLM-powered conversation (existing Phase 1 flow)
      • ``interactive`` → Button/list replies from Modules 2-5
    """
    payload = await request.json()

    # ── Parse the Meta WhatsApp webhook payload ──────────
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])

        if not messages:
            # Not a message event (e.g. status update), return OK
            return JSONResponse({"status": "ok"})

        message = messages[0]
        msg_type = message.get("type")
        phone = message.get("from")

        # Extract contact name from the webhook payload
        contacts = value.get("contacts", [])
        contact_name = ""
        if contacts:
            contact_name = contacts[0].get("profile", {}).get("name", "")

    except (IndexError, AttributeError):
        logger.warning("Failed to parse Meta payload: %s", payload)
        return JSONResponse({"status": "ok", "message": "parse_error"})

    # ── Route by message type ────────────────────────────
    if msg_type == "text":
        return await _handle_text_message(phone, message, contact_name)

    elif msg_type == "interactive":
        return await _handle_interactive_message(phone, message, contact_name)

    else:
        logger.info("Unsupported message type: %s from %s", msg_type, phone)
        return JSONResponse({"status": "ok", "message": "unsupported_type"})


# ── Text Message Handler (Phase 1 LLM Flow) ─────────────────────────

async def _handle_text_message(
    phone: str, message: dict, contact_name: str
) -> JSONResponse:
    """Handle a plain text WhatsApp message via the LLM."""
    user_text = message.get("text", {}).get("body", "").strip()
    logger.info("Incoming text from %s: %s", phone, user_text[:120])

    # ── 1. Detect language & upsert patient ──────────────
    language = detect_language(user_text)
    db.upsert_patient(phone, name=contact_name, language=language)

    # ── 2. History + LLM call ────────────────────────────
    history = db.get_history(phone)
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
            patient_name=contact_name,
            language=language,
        )
        if language == "ar":
            confirmation = (
                f"📅 تم جدولة موعدك!\n"
                f"📋 الخدمة: {result['service']}\n"
                f"📅 التاريخ: {result['date']}\n"
                f"🕐 الوقت: {result['time']}\n"
                f"🔖 رقم الحجز: #{result['booking_id']}\n\n"
                f"📲 ستتلقى تذكيراً للتأكيد قبل 24 ساعة من موعدك."
            )
        else:
            confirmation = (
                f"📅 Your appointment has been scheduled!\n"
                f"📋 Service: {result['service']}\n"
                f"📅 Date: {result['date']}\n"
                f"🕐 Time: {result['time']}\n"
                f"🔖 Booking ID: #{result['booking_id']}\n\n"
                f"📲 You'll receive a confirmation reminder 24 hours before your appointment."
            )
        if result.get("is_premium"):
            if language == "ar":
                confirmation += "\n💎 هذه خدمة مميزة — ستحتاج لدفع وديعة لتأكيد الحجز."
            else:
                confirmation += "\n💎 This is a premium service — a deposit will be required to confirm."
        display_reply = f"{display_reply}\n\n{confirmation}" if display_reply else confirmation

    # ── 4. Persist & send ────────────────────────────────
    db.save_message(phone, "user", user_text)
    db.save_message(phone, "assistant", display_reply)

    await send_text_message(phone, display_reply)

    return JSONResponse({"status": "ok"})


# ── Interactive Message Handler (Modules 2-5) ────────────────────────

async def _handle_interactive_message(
    phone: str, message: dict, contact_name: str
) -> JSONResponse:
    """
    Handle interactive replies (button taps and list selections).

    Button/list IDs follow the format: ``action:booking_id``
    """
    interactive = message.get("interactive", {})
    interactive_type = interactive.get("type")

    if interactive_type == "button_reply":
        button_id = interactive.get("button_reply", {}).get("id", "")
        button_title = interactive.get("button_reply", {}).get("title", "")
        logger.info("Button reply from %s: %s (%s)", phone, button_title, button_id)
        reply = await _route_button(phone, button_id)

    elif interactive_type == "list_reply":
        list_id = interactive.get("list_reply", {}).get("id", "")
        list_title = interactive.get("list_reply", {}).get("title", "")
        logger.info("List reply from %s: %s (%s)", phone, list_title, list_id)
        reply = await _route_list(phone, list_id)

    else:
        logger.warning("Unknown interactive type: %s from %s", interactive_type, phone)
        return JSONResponse({"status": "ok", "message": "unknown_interactive"})

    # Send the reply
    if reply:
        await send_text_message(phone, reply)

    return JSONResponse({"status": "ok"})


async def _route_button(phone: str, button_id: str) -> str:
    """Route a button reply to the appropriate handler."""
    if ":" not in button_id:
        logger.warning("Invalid button ID format: %s", button_id)
        return "Sorry, something went wrong. Please try again."

    action, booking_id_str = button_id.split(":", 1)

    try:
        booking_id = int(booking_id_str)
    except ValueError:
        logger.warning("Invalid booking ID in button: %s", button_id)
        return "Sorry, something went wrong. Please try again."

    if action == "confirm":
        return await handle_confirmation(booking_id, phone)

    elif action == "pay":
        return await handle_pay_confirm(booking_id, phone)

    elif action == "reschedule":
        return await handle_reschedule(booking_id, phone)

    elif action == "rebook":
        # Module 4: Patient wants to rebook — guide them to the LLM flow
        booking = db.get_booking_by_id(booking_id)
        if booking:
            lang = booking.get("language", "en")
            service = booking["service"]
            if lang == "ar":
                return f"رائع! متى تود حجز جلسة *{service}* القادمة؟ يرجى إخباري بالتاريخ والوقت المفضلين. 📅"
            return f"Great! When would you like to schedule your next *{service}* session? Please let me know your preferred date and time. 📅"
        return "When would you like to book? Please share your preferred date and time."

    elif action == "skip_rebook":
        booking = db.get_booking_by_id(booking_id)
        lang = (booking or {}).get("language", "en")
        if lang == "ar":
            return "لا مشكلة! سنتواصل معك لاحقًا. 😊"
        return "No worries! We'll check in with you later. 😊"

    else:
        logger.warning("Unknown button action: %s", action)
        return "Sorry, I didn't understand that action."


async def _route_list(phone: str, list_id: str) -> str:
    """Route a list selection to the appropriate handler."""
    if ":" not in list_id:
        logger.warning("Invalid list ID format: %s", list_id)
        return "Sorry, something went wrong. Please try again."

    action, booking_id_str = list_id.split(":", 1)

    try:
        booking_id = int(booking_id_str)
    except ValueError:
        logger.warning("Invalid booking ID in list: %s", list_id)
        return "Sorry, something went wrong. Please try again."

    # Module 3: Aftercare check-in responses
    if action in ("perfect", "mild", "severe"):
        return await handle_checkin_response(phone, booking_id, action)

    logger.warning("Unknown list action: %s", action)
    return "Thank you for your response."


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
        "How can QuantX Skin Salon help you today?"
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


@app.post("/admin/complete/{booking_id}", tags=["admin"])
async def mark_complete(booking_id: int):
    """
    Mark a booking as completed (for testing Module 3 aftercare flow).
    In production this would be triggered from the clinic's Google Sheet
    or internal system.
    """
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    db.mark_booking_completed(booking_id)
    logger.info("Booking #%s marked as completed", booking_id)
    return {
        "status": "completed",
        "booking_id": booking_id,
        "message": "Aftercare check-in will be sent ~24 hours from now.",
    }


@app.get("/admin/patients/{phone}", tags=["admin"])
async def get_patient(phone: str):
    """Return patient record (debug helper)."""
    patient = db.get_patient(phone)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


# ══════════════════════════════════════════════════════════════════════
#  DEMO / VIDEO RECORDING INSTANT TRIGGERS (MODULES 2–5)
# ══════════════════════════════════════════════════════════════════════

@app.post("/admin/trigger/reminder-24h/{booking_id}", tags=["demo"])
async def trigger_24h_reminder(booking_id: int):
    """Instantly send the T-24h reminder (Module 2) for a booking on WhatsApp."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    from app.reminders import send_24h_reminder
    await send_24h_reminder(booking)
    return {"status": "sent", "booking_id": booking_id, "type": "T-24h Reminder"}


@app.post("/admin/trigger/reminder-3h/{booking_id}", tags=["demo"])
async def trigger_3h_reminder(booking_id: int):
    """Instantly send the T-3h final reminder + location pin (Module 2) on WhatsApp."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    from app.reminders import send_3h_reminder
    await send_3h_reminder(booking)
    return {"status": "sent", "booking_id": booking_id, "type": "T-3h Reminder + Location"}


@app.post("/admin/trigger/aftercare/{booking_id}", tags=["demo"])
async def trigger_aftercare(booking_id: int):
    """Instantly send the Aftercare Check-in + Interactive List (Module 3) on WhatsApp."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    from app.aftercare import send_aftercare_checkin
    await send_aftercare_checkin(booking)
    return {"status": "sent", "booking_id": booking_id, "type": "Aftercare Check-in"}


@app.post("/admin/trigger/retention/{booking_id}", tags=["demo"])
async def trigger_retention(booking_id: int):
    """Instantly send the Retention Campaign message (Module 4) on WhatsApp."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    from app.retention import _send_retention_message
    await _send_retention_message(booking, booking["service"])
    db.mark_retention_sent(booking_id)
    return {"status": "sent", "booking_id": booking_id, "type": "Retention Campaign"}



@app.post("/admin/trigger/review/{booking_id}", tags=["demo"])
async def trigger_review(booking_id: int):
    """Instantly send the Google Review request (Module 5) on WhatsApp."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
    from app.reviews import send_review_request
    await send_review_request(booking)
    return {"status": "sent", "booking_id": booking_id, "type": "Google Review Request"}

