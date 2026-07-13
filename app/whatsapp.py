"""
WhatsApp API helper – uses official Meta WhatsApp Cloud API.

Supports:
  • Plain text messages
  • Template messages
  • Interactive button messages  (Module 2 – confirmations)
  • Interactive list messages    (Module 3 – aftercare check-in)
  • Location messages            (Module 2 – T-3h clinic pin)
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

_API_BASE = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
_HEADERS = {
    "Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}",
    "Content-Type": "application/json",
}


def _format_phone(phone: str) -> str:
    """Format phone number to Meta format, just digits (no +)."""
    phone = phone.strip()
    if phone.startswith("whatsapp:"):
        phone = phone.replace("whatsapp:", "")
    if phone.startswith("+"):
        phone = phone.lstrip("+")
    return phone


async def _send(payload: dict) -> dict[str, Any]:
    """Send a payload to the Meta Messages API."""
    if not WHATSAPP_ACCESS_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        logger.error("WhatsApp credentials not configured.")
        return {"error": "not_configured"}

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(_API_BASE, json=payload, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
            logger.info("Meta message sent to %s", payload.get("to"))
            return data
        except httpx.HTTPStatusError as exc:
            logger.error(
                "Meta API error %s: %s",
                exc.response.status_code,
                exc.response.text,
            )
            return {"error": exc.response.text}
        except Exception:
            logger.exception("Failed to send Meta message to %s", payload.get("to"))
            return {"error": "send_failed"}


# ── Plain Text ───────────────────────────────────────────────────────

async def send_text_message(to: str, body: str) -> dict[str, Any]:
    """Send a plain text WhatsApp message via Meta Cloud API."""
    return await _send({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _format_phone(to),
        "type": "text",
        "text": {"preview_url": False, "body": body},
    })


# ── Template Messages ────────────────────────────────────────────────

async def send_template_message(
    to: str,
    template_name: str = "hello_world",
    language_code: str = "en_US",
    body_params: list[str] | None = None,
) -> dict[str, Any]:
    """Send a WhatsApp Template message via Meta Cloud API."""
    components = []
    if body_params:
        parameters = [{"type": "text", "text": p} for p in body_params]
        components.append({"type": "body", "parameters": parameters})

    return await _send({
        "messaging_product": "whatsapp",
        "to": _format_phone(to),
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language_code},
            "components": components,
        },
    })


# ── Interactive Buttons (Module 2 — T-24h Confirmation) ──────────────

async def send_interactive_buttons(
    to: str,
    body_text: str,
    buttons: list[dict[str, str]],
    header_text: str | None = None,
    footer_text: str | None = None,
) -> dict[str, Any]:
    """
    Send a WhatsApp interactive button message.

    Parameters
    ----------
    buttons
        Up to 3 buttons, each ``{"id": "unique_id", "title": "Button Text"}``.
        Title max 20 chars.
    """
    action_buttons = [
        {"type": "reply", "reply": {"id": btn["id"], "title": btn["title"]}}
        for btn in buttons[:3]  # WhatsApp max 3 buttons
    ]

    interactive: dict[str, Any] = {
        "type": "button",
        "body": {"text": body_text},
        "action": {"buttons": action_buttons},
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    return await _send({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _format_phone(to),
        "type": "interactive",
        "interactive": interactive,
    })


# ── Interactive List (Module 3 — Aftercare Check-in) ─────────────────

async def send_interactive_list(
    to: str,
    body_text: str,
    button_text: str,
    sections: list[dict],
    header_text: str | None = None,
    footer_text: str | None = None,
) -> dict[str, Any]:
    """
    Send a WhatsApp interactive list message.

    Parameters
    ----------
    sections
        List of sections, each::

            {
                "title": "Section Title",
                "rows": [
                    {"id": "row_id", "title": "Row Title", "description": "..."}
                ]
            }
    """
    interactive: dict[str, Any] = {
        "type": "list",
        "body": {"text": body_text},
        "action": {
            "button": button_text,
            "sections": sections,
        },
    }
    if header_text:
        interactive["header"] = {"type": "text", "text": header_text}
    if footer_text:
        interactive["footer"] = {"text": footer_text}

    return await _send({
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": _format_phone(to),
        "type": "interactive",
        "interactive": interactive,
    })


# ── Location Message (Module 2 — T-3h Clinic Pin) ───────────────────

async def send_location_message(
    to: str,
    latitude: float,
    longitude: float,
    name: str = "",
    address: str = "",
) -> dict[str, Any]:
    """Send a location pin via WhatsApp."""
    return await _send({
        "messaging_product": "whatsapp",
        "to": _format_phone(to),
        "type": "location",
        "location": {
            "latitude": latitude,
            "longitude": longitude,
            "name": name,
            "address": address,
        },
    })
