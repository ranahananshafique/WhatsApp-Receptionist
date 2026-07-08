"""
LLM Client – talks to the local Qwen 2.5 3B server via the OpenAI-
compatible Chat Completions API.

Responsibilities:
  1. Build the system prompt with business info + guardrails.
  2. Detect language (Arabic vs English) from the user message.
  3. Call the LLM with conversation history.
  4. Parse the response for booking-intent tool calls (structured JSON
     extraction) since smaller models may not support native function
     calling reliably.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import (
    BUSINESS_HOURS,
    BUSINESS_HOURS_AR,
    BUSINESS_NAME,
    BUSINESS_SERVICES,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LLM_TEMPERATURE,
)

logger = logging.getLogger(__name__)

# ── Async OpenAI client (pointed at local server) ────────────────────
_client = AsyncOpenAI(
    base_url=LLM_BASE_URL,
    api_key=LLM_API_KEY,
)

# ── Service lookup helpers ────────────────────────────────────────────
_SERVICE_NAMES_EN = [s["name"].lower() for s in BUSINESS_SERVICES]
_SERVICE_NAMES_AR = [s["name_ar"] for s in BUSINESS_SERVICES]

_SERVICES_BLOCK_EN = "\n".join(
    f"  • {s['name']} – {s['price_aed']} AED" for s in BUSINESS_SERVICES
)
_SERVICES_BLOCK_AR = "\n".join(
    f"  • {s['name_ar']} – {s['price_aed']} درهم" for s in BUSINESS_SERVICES
)


# ── System prompt builder ────────────────────────────────────────────

def _build_system_prompt(language: str) -> str:
    """
    Return the system prompt in the detected language.
    Contains strict guardrails so the model stays in character.
    """
    if language == "ar":
        return f"""أنت موظف استقبال ذكي ومهذب في {BUSINESS_NAME}.
أنت تتحدث العربية فقط في هذه المحادثة. كن ودوداً ومحترفاً.

معلومات العيادة:
  الاسم: {BUSINESS_NAME}
  الخدمات المتوفرة:
{_SERVICES_BLOCK_AR}
  ساعات العمل: {BUSINESS_HOURS_AR}

القواعد الصارمة:
1. لا تخترع خدمات غير مذكورة أعلاه.
2. لا تقدم نصائح طبية أو تشخيصات.
3. إذا سأل المستخدم عن شيء خارج نطاقك، اعتذر بلطف ووجهه للاتصال بالعيادة.
4. إذا أراد المستخدم حجز موعد أو إعادة جدولة، اجمع منه: الخدمة، التاريخ، الوقت.
5. عندما تتوفر لديك الثلاثة (الخدمة والتاريخ والوقت)، أجب بسطر JSON واحد فقط بهذا الشكل بالضبط:
   BOOKING_JSON: {{"service": "...", "date": "YYYY-MM-DD", "time": "HH:MM"}}
   ثم أكمل ردك الطبيعي بعده.
6. تأكد دائماً من المعلومات قبل إنشاء سطر BOOKING_JSON."""

    # English (default)
    return f"""You are a polite, professional AI receptionist at {BUSINESS_NAME}.
You respond ONLY in English in this conversation. Be friendly yet concise.

Clinic Information:
  Name: {BUSINESS_NAME}
  Available Services:
{_SERVICES_BLOCK_EN}
  Working Hours: {BUSINESS_HOURS}

Strict Rules:
1. NEVER invent services not listed above.
2. NEVER provide medical advice or diagnoses.
3. If the user asks about something outside your scope, politely apologise and suggest they call the clinic directly.
4. If the user wants to book or reschedule, collect: service, date, time.
5. Once you have ALL THREE (service, date, time), include exactly one line of JSON in your reply in this format:
   BOOKING_JSON: {{"service": "...", "date": "YYYY-MM-DD", "time": "HH:MM"}}
   Then continue your natural reply after it.
6. Always confirm the details with the user before producing the BOOKING_JSON line."""


# ── Language detection (simple heuristic) ─────────────────────────────

_ARABIC_RANGE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]+")


def detect_language(text: str) -> str:
    """Return ``'ar'`` if the text contains significant Arabic script, else ``'en'``."""
    arabic_chars = len(_ARABIC_RANGE.findall(text))
    # If more than 30 % of "word tokens" are Arabic, treat as Arabic
    words = text.split()
    if not words:
        return "en"
    arabic_ratio = arabic_chars / len(words)
    return "ar" if arabic_ratio > 0.3 else "en"


# ── Booking JSON extraction ──────────────────────────────────────────

_BOOKING_RE = re.compile(
    r"BOOKING_JSON:\s*(\{.*?\})",
    re.DOTALL,
)


def extract_booking(text: str) -> dict | None:
    """
    Try to extract a ``BOOKING_JSON`` blob from the assistant reply.

    Returns
    -------
    dict or None
        ``{"service": str, "date": str, "time": str}`` if found, else None.
    """
    match = _BOOKING_RE.search(text)
    if not match:
        return None

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        logger.warning("Found BOOKING_JSON marker but JSON was invalid: %s", match.group(1))
        return None

    # Validate required keys
    if all(k in data for k in ("service", "date", "time")):
        return {
            "service": str(data["service"]).strip(),
            "date": str(data["date"]).strip(),
            "time": str(data["time"]).strip(),
        }

    logger.warning("BOOKING_JSON missing required keys: %s", data)
    return None


def strip_booking_json(text: str) -> str:
    """Remove the ``BOOKING_JSON: {...}`` line from the reply shown to the user."""
    return _BOOKING_RE.sub("", text).strip()


# ── Chat completion call ─────────────────────────────────────────────

async def generate_reply(
    history: list[dict[str, str]],
    user_message: str,
    language: str | None = None,
) -> str:
    """
    Send the conversation history + new user message to the LLM and
    return the assistant's reply text.

    Parameters
    ----------
    history
        Prior messages as ``[{"role": "user"|"assistant", "content": "..."}]``.
    user_message
        The latest user message (not yet in *history*).
    language
        ``"en"`` or ``"ar"``.  Auto-detected from *user_message* if ``None``.

    Returns
    -------
    str
        The raw assistant reply (may contain a ``BOOKING_JSON`` line).
    """
    if language is None:
        language = detect_language(user_message)

    system_prompt = _build_system_prompt(language)
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        response = await _client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=LLM_MAX_TOKENS,
            temperature=LLM_TEMPERATURE,
        )
        reply = response.choices[0].message.content or ""
        return reply.strip()

    except Exception:
        logger.exception("LLM call failed")
        if language == "ar":
            return "عذراً، حدث خطأ تقني. يرجى المحاولة مرة أخرى لاحقاً أو الاتصال بالعيادة مباشرة."
        return (
            "Sorry, I'm experiencing a technical issue right now. "
            "Please try again shortly or call the clinic directly."
        )
