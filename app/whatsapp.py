"""
WhatsApp API helper – uses official Meta WhatsApp Cloud API.
"""

from __future__ import annotations

import logging
from typing import Any

from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException

from app.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER,
)

logger = logging.getLogger(__name__)

def _format_phone(phone: str) -> str:
    """Format phone number to Twilio format, needs whatsapp:+ prefix."""
    phone = phone.strip()
    if not phone.startswith("whatsapp:"):
        if not phone.startswith("+"):
            phone = f"+{phone}"
        phone = f"whatsapp:{phone}"
    return phone

async def send_text_message(to: str, body: str) -> dict[str, Any]:
    """
    Send a plain text WhatsApp message via Twilio API.
    """
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN or not TWILIO_WHATSAPP_NUMBER:
        logger.error("Twilio credentials not configured.")
        return {"error": "not_configured"}

    try:
        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
        message = client.messages.create(
            from_=_format_phone(TWILIO_WHATSAPP_NUMBER),
            body=body,
            to=_format_phone(to)
        )
        logger.info("Twilio Message sent to %s (SID: %s)", to, message.sid)
        return {"status": "sent", "sid": message.sid}
    except TwilioRestException as exc:
        logger.error("Twilio API error %s: %s", exc.status, exc.msg)
        return {"error": exc.msg}
    except Exception:
        logger.exception("Failed to send Twilio message to %s", to)
        return {"error": "send_failed"}


async def send_template_message(
    to: str,
    template_name: str = "hello_world",
    language_code: str = "en_US",
    body_params: list[str] | None = None,
) -> dict[str, Any]:
    """
    Send a WhatsApp Template message via Twilio API.
    Twilio handles templates through the Content API or by passing 
    ContentSid, but for the basic sandbox, plain text works.
    We will just send a standard text for the missed call fallback.
    """
    if not TWILIO_ACCOUNT_SID or not TWILIO_AUTH_TOKEN:
        logger.error("Twilio credentials not configured.")
        return {"error": "not_configured"}

    # Twilio sandbox doesn't strictly enforce templates for user-initiated 
    # conversations. For business-initiated, you need approved templates.
    # We will simulate the template by sending the raw text.
    logger.info("Sending template via standard text (Twilio handles template matching by body).")
    
    body = "Hi! 👋 We noticed we missed a call from you. How can Apex Clinic help you today?"
    return await send_text_message(to=to, body=body)
