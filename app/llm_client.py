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
from datetime import datetime
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


_ARABIC_DAYS = {
    0: "الاثنين",
    1: "الثلاثاء",
    2: "الأربعاء",
    3: "الخميس",
    4: "الجمعة",
    5: "السبت",
    6: "الأحد",
}


# ── Greeting response builder ────────────────────────────────────────


def get_greeting_response(language: str) -> str:
    """
    Return a greeting message along with a short introduction of the salon
    and the services offered here.
    """
    if language == "ar":
        return (
            f"مرحباً بك في {BUSINESS_NAME}!\n\n"
            f"نحن صالون متخصص في العناية بالبشرة والجمال نقدم أفضل العلاجات المتطورة والإجراءات التجميلية المهنية. "
            f"ساعات العمل لدينا: {BUSINESS_HOURS_AR}.\n\n"
            f"إليك الخدمات المتوفرة لدينا:\n"
            f"{_SERVICES_BLOCK_AR}\n\n"
            f"كيف يمكنني مساعدتك اليوم؟ هل ترغب في حجز موعد؟"
        )

    return (
        f"Hello! Welcome to {BUSINESS_NAME}.\n\n"
        f"We are a premier skin care salon offering professional aesthetic and dermatological treatments. "
        f"Our working hours are {BUSINESS_HOURS}.\n\n"
        f"Here are the services offered here:\n"
        f"{_SERVICES_BLOCK_EN}\n\n"
        f"How can I assist you today? Would you like to book an appointment?"
    )


# ── System prompt builder ────────────────────────────────────────────

def _build_system_prompt(language: str, current_time: datetime | None = None) -> str:
    """
    Return the system prompt in the detected language.
    Contains strict guardrails so the model stays in character and current
    datetime context so the model accurately calculates booking dates and times.
    """
    now = current_time or datetime.now()
    date_iso = now.strftime("%Y-%m-%d")
    day_en = now.strftime("%A")
    time_str = now.strftime("%I:%M %p")
    day_ar = _ARABIC_DAYS.get(now.weekday(), "")

    if language == "ar":
        return f"""أنت موظف استقبال ذكي ومهذب في {BUSINESS_NAME}.
أنت تتحدث العربية فقط في هذه المحادثة. كن ودوداً ومحترفاً.
عندما يرسل المستخدم رسالة ترحيب (مثل مرحبا، السلام عليكم، أهلا، أو أي تحية في البداية)، يجب عليك الرد برسالة ترحيبية بالإضافة إلى مقدمة موجزة عن الصالون وساعات العمل والخدمات المقدمة هنا مع أسعارها.

معلومات العيادة:
  الاسم: {BUSINESS_NAME}
  الخدمات المتوفرة:
{_SERVICES_BLOCK_AR}
  ساعات العمل: {BUSINESS_HOURS_AR}

الوقت والتاريخ الحالي:
  تاريخ اليوم: {date_iso} ({day_ar})
  الوقت الحالي: {time_str}

القواعد الصارمة:
1. لا تخترع خدمات غير مذكورة أعلاه.
2. لا تقدم نصائح طبية أو تشخيصات.
3. إذا سأل المستخدم عن شيء خارج نطاقك، اعتذر بلطف ووجهه للاتصال بالعيادة.
4. عندما يرسل المستخدم تحية أو ترحيباً (مثل مرحبا، السلام عليكم، أهلا، أو أي رسالة ترحيبية في البداية)، يجب عليك الرد برسالة ترحيبية بالإضافة إلى مقدمة موجزة عن الصالون وساعات العمل والخدمات المقدمة هنا مع أسعارها.
5. إذا أراد المستخدم حجز موعد أو إعادة جدولة، اجمع منه: الخدمة، التاريخ، الوقت.
6. استخدم دائماً "تاريخ اليوم" المذكور أعلاه ({date_iso} - {day_ar}) والوقت الحالي لحساب التواريخ والأوقات النسبية بدقة (مثل: "اليوم"، "غداً"، أو أيام الأسبوع) ولتجنب ذكر أي تاريخ أو وقت خاطئ.
7. بمجرد توفر الثلاثة (الخدمة والتاريخ والوقت) من المستخدم، أجب فوراً بسطر JSON واحد فقط بهذا الشكل بالضبط دون انتظار تأكيد إضافي:
   BOOKING_JSON: {{"service": "...", "date": "YYYY-MM-DD", "time": "HH:MM"}}
8. تأكد دائماً أن حقل "date" في BOOKING_JSON هو التاريخ الدقيق بصيغة YYYY-MM-DD محسوباً بالنسبة لتاريخ اليوم ({date_iso})، وأن الوقت هو الوقت الدقيق لحجز الموعد بصيغة 24 ساعة (HH:MM)."""

    # English (default)
    return f"""You are a polite, professional AI receptionist at {BUSINESS_NAME}.
You respond ONLY in English in this conversation. Be friendly yet concise. 
Whenever a user enters a hello or a greeting (e.g. 'Hello', 'Hi', 'Hey', 'Good morning', or any introductory greeting), you MUST respond with a greeting message along with a short introduction of the salon (including working hours) and the services offered here with their prices.

Clinic Information:
  Name: {BUSINESS_NAME}
  Available Services:
{_SERVICES_BLOCK_EN}
  Working Hours: {BUSINESS_HOURS}

Current Date & Time Context:
  Today's Date: {date_iso} ({day_en})
  Current Time: {time_str}

Strict Rules:
1. NEVER invent services not listed above.
2. NEVER provide medical advice or diagnoses.
3. If the user asks about something outside your scope, politely apologise and suggest they call the clinic directly.
4. When a user enters a hello or a greeting (e.g. 'Hello', 'Hi', 'Hey', 'Good morning', or any introductory greeting), you MUST respond with a greeting message along with a short introduction of the salon (including working hours) and the services offered here with their prices.
5. If the user wants to book or reschedule, collect: service, date, time.
6. Always use the Current Date & Time above ({date_iso}, {day_en}) to accurately resolve relative dates (e.g. 'today', 'tomorrow', day of the week like 'Monday' or 'Friday', 'next week') so that booking confirmation messages always show the correct date and time.
7. Once the user provides ALL THREE (service, date, time), you MUST IMMEDIATELY include exactly one line of JSON in your reply in this format without asking for extra confirmation first:
   BOOKING_JSON: {{"service": "...", "date": "YYYY-MM-DD", "time": "HH:MM"}}
   Then continue your natural reply after it.
8. Ensure "date" is the exact YYYY-MM-DD calendar date relative to today ({date_iso}) and "time" is the exact appointment time in 24-hour HH:MM format (e.g. "14:00" for 2:00 PM)."""


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


def extract_booking(text: str, user_message: str = "") -> dict | None:
    """
    Try to extract a ``BOOKING_JSON`` blob from the assistant reply,
    falling back to extracting from text + user_message if all 3 fields exist.
    """
    match = _BOOKING_RE.search(text)
    if match:
        try:
            data = json.loads(match.group(1))
            if all(k in data for k in ("service", "date", "time")):
                date_val = str(data["date"]).strip()
                time_val = str(data["time"]).strip()
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", date_val)
                if date_match:
                    date_val = date_match.group(1)
                time_match = re.search(r"^(\d{1,2}:\d{2}):00(?:\.\d+)?$", time_val)
                if time_match:
                    time_val = time_match.group(1)
                return {
                    "service": str(data["service"]).strip(),
                    "date": date_val,
                    "time": time_val,
                }
        except Exception:
            logger.warning("Found BOOKING_JSON marker but JSON was invalid: %s", match.group(1))

    # Fallback extraction from text / user_message
    combined = f"{text} {user_message}"
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", combined)
    time_match = re.search(r"\b(\d{1,2}:\d{2}(?:\s*[APap][Mm])?)\b", combined)
    if not time_match:
        time_match = re.search(r"\b(\d{1,2}(?:\s*[APap][Mm]))\b", combined)

    if date_match and time_match:
        date_val = date_match.group(1)
        time_val = time_match.group(1)
        if ":" not in time_val and any(x in time_val.upper() for x in ("AM", "PM")):
            t_num = re.sub(r"[^\d]", "", time_val)
            suffix = "AM" if "AM" in time_val.upper() else "PM"
            time_val = f"{t_num}:00 {suffix}"

        for s in _SERVICE_NAMES_EN:
            if s in combined.lower():
                for svc in BUSINESS_SERVICES:
                    if svc["name"].lower() == s:
                        return {"service": svc["name"], "date": date_val, "time": time_val}
        for s_ar in _SERVICE_NAMES_AR:
            if s_ar in combined:
                for svc in BUSINESS_SERVICES:
                    if svc["name_ar"] == s_ar:
                        return {"service": svc["name_ar"], "date": date_val, "time": time_val}

    return None


def strip_booking_json(text: str) -> str:
    """Remove the ``BOOKING_JSON: {...}`` line from the reply shown to the user."""
    return _BOOKING_RE.sub("", text).strip()


# ── Chat completion call ─────────────────────────────────────────────

async def generate_reply(
    history: list[dict[str, str]],
    user_message: str,
    language: str | None = None,
    current_time: datetime | None = None,
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
    current_time
        Optional explicit datetime to use for system prompt context.

    Returns
    -------
    str
        The raw assistant reply (may contain a ``BOOKING_JSON`` line).
    """
    if language is None:
        language = detect_language(user_message)

    system_prompt = _build_system_prompt(language, current_time=current_time)
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
