"""
WhatsApp API helper – uses official Meta WhatsApp Cloud API.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import (
    WHATSAPP_ACCESS_TOKEN,
    WHATSAPP_PHONE_NUMBER_ID,
)

logger = logging.getLogger(__name__)

def _format_phone(phone: str) -> str:
    """Format phone number to Meta format, just digits (no +)."""
    phone = phone.strip()
    if phone.startswith("whatsapp:"):
        phone = phone.replace("whatsapp:", "")
    if phone.startswith("+"):
        phone = phone.lstrip("+")
    return phone

async def send_text_message(to: str, body: str) -> dict[str, Any]:
    """
    Send a plain text WhatsApp message via Meta Cloud API.
    """
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials not configured.")
        return {"error": "not_configured"}

    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _format_phone(to),
        "type": "text",
        "text": {"preview_url": False, "body": body}
    }

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Meta Message sent to %s", to)
            return data
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Meta API error %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return {"error": exc.response.text}
        except Exception:
            logger.exception("Failed to send Meta message to %s", to)
            return {"error": "send_failed"}


async def send_template_message(
    to: str,
    template_name: str = "hello_world",
    language_code: str = "en_US",
    body_params: list[str] | None = None,
) -> dict[str, Any]:
    """
    Send a WhatsApp Template message via Meta Cloud API.
    """
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials not configured.")
        return {"error": "not_configured"}

    url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    
    components = []
    if body_params:
        parameters = [{"type": "text", "text": p} for p in body_params]
        components.append({"type": "body", "parameters": parameters})
        
    payload = {
        "messaging_product": "whatsapp",
        "to": _format_phone(to),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": components
        }
    }

    headers = {
        "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json"
    }

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Meta Template message sent to %s", to)
            return data
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Meta API error %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return {"error": exc.response.text}
        except Exception:
            logger.exception("Failed to send Meta template message to %s", to)
            return {"error": "send_failed"}
