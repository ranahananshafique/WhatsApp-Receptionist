"""
Pydantic models used across the application for request / response
validation and internal data transfer.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── WhatsApp Webhook Payload (simplified subset we actually need) ─────
class WhatsAppProfile(BaseModel):
    name: str = ""


class WhatsAppContact(BaseModel):
    profile: WhatsAppProfile = Field(default_factory=WhatsAppProfile)
    wa_id: str = ""


class WhatsAppTextBody(BaseModel):
    body: str = ""


class WhatsAppMessage(BaseModel):
    from_: str = Field("", alias="from")
    id: str = ""
    timestamp: str = ""
    type: str = ""
    text: WhatsAppTextBody | None = None

    class Config:
        populate_by_name = True


class WhatsAppMessageValue(BaseModel):
    messaging_product: str = ""
    contacts: list[WhatsAppContact] = Field(default_factory=list)
    messages: list[WhatsAppMessage] = Field(default_factory=list)


class WhatsAppChange(BaseModel):
    field: str = ""
    value: WhatsAppMessageValue = Field(default_factory=WhatsAppMessageValue)


class WhatsAppEntry(BaseModel):
    id: str = ""
    changes: list[WhatsAppChange] = Field(default_factory=list)


class WhatsAppWebhookPayload(BaseModel):
    """
    Top-level model for the incoming webhook JSON from Meta's
    WhatsApp Cloud API.
    """

    object: str = ""
    entry: list[WhatsAppEntry] = Field(default_factory=list)


# ── Missed-Call Endpoint ──────────────────────────────────────────────
class MissedCallRequest(BaseModel):
    phone_number: str = Field(
        ...,
        description="Phone number in international format, e.g. +971501234567",
    )


# ── Internal Booking ─────────────────────────────────────────────────
class BookingDetails(BaseModel):
    service: str
    date: str
    time: str


class BookingRecord(BaseModel):
    id: int | None = None
    phone: str
    service: str
    date: str
    time: str
    created_at: str = ""
