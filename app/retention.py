"""
Module 4 – Patient Retention Campaigns

Weekly cron scans completed appointments for cohort-based re-booking triggers.
Example rules:
  • Laser Hair Removal completed 4 weeks ago → re-booking prompt
  • Facial completed 30 days ago → "monthly glow-up" prompt
"""

from __future__ import annotations

import logging

from app import database as db
from app.config import BUSINESS_NAME, RETENTION_INTERVALS
from app.whatsapp import send_interactive_buttons

logger = logging.getLogger(__name__)


# ── Retention message templates (bilingual) ──────────────────────────

_RETENTION_MESSAGES: dict[str, dict[str, str]] = {
    "Laser Hair Removal": {
        "en": (
            "Hi {name}! 👋\n\n"
            "It's been 4 weeks since your last *Laser Hair Removal* session at {business}. "
            "For the best results, it's time for your next session! ✨\n\n"
            "Would you like to book a slot this week?"
        ),
        "ar": (
            "مرحبًا {name}! 👋\n\n"
            "مرّت 4 أسابيع على آخر جلسة *إزالة الشعر بالليزر* في {business}. "
            "للحصول على أفضل النتائج، حان وقت جلستك القادمة! ✨\n\n"
            "هل ترغب في حجز موعد هذا الأسبوع؟"
        ),
    },
    "Deep Cleansing Facial": {
        "en": (
            "Hi {name}! ✨\n\n"
            "Time for your monthly glow-up! It's been 30 days since your last "
            "*Deep Cleansing Facial* at {business}.\n\n"
            "Ready to keep that radiant skin? Book your next session!"
        ),
        "ar": (
            "مرحبًا {name}! ✨\n\n"
            "حان وقت إشراقتك الشهرية! مرّ 30 يومًا على آخر جلسة "
            "*تنظيف عميق للبشرة* في {business}.\n\n"
            "هل أنت مستعد/ة للحفاظ على بشرتك المشرقة؟ احجز جلستك القادمة!"
        ),
    },
    "Hydrafacial": {
        "en": (
            "Hi {name}! 💧\n\n"
            "Your skin is calling! It's been 30 days since your last *Hydrafacial* "
            "at {business}. Keep the hydration going with another session!\n\n"
            "Would you like to book?"
        ),
        "ar": (
            "مرحبًا {name}! 💧\n\n"
            "بشرتك تناديك! مرّ 30 يومًا على آخر جلسة *هيدرافيشيل* "
            "في {business}. حافظ على ترطيب بشرتك بجلسة جديدة!\n\n"
            "هل ترغب في الحجز؟"
        ),
    },
}

_DEFAULT_RETENTION = {
    "en": (
        "Hi {name}! 👋\n\n"
        "It's been a while since your last *{service}* at {business}. "
        "Would you like to schedule your next session?\n\n"
        "We'd love to see you again! 😊"
    ),
    "ar": (
        "مرحبًا {name}! 👋\n\n"
        "مرّ وقت على آخر جلسة *{service}* في {business}. "
        "هل ترغب في حجز جلستك القادمة؟\n\n"
        "يسعدنا رؤيتك مجددًا! 😊"
    ),
}


# ── Run Retention Scan ───────────────────────────────────────────────

async def run_retention_scan() -> int:
    """
    Scan all cohort rules and send re-booking prompts.
    Returns the number of messages sent.
    """
    total_sent = 0

    for service, days in RETENTION_INTERVALS.items():
        bookings = db.get_bookings_for_retention(service, days)

        for booking in bookings:
            try:
                await _send_retention_message(booking, service)
                db.mark_retention_sent(booking["id"])
                total_sent += 1
            except Exception:
                logger.exception(
                    "Failed to send retention message for booking #%s",
                    booking["id"],
                )

    if total_sent > 0:
        logger.info("Retention scan complete: %d messages sent", total_sent)
    else:
        logger.debug("Retention scan complete: no eligible patients")

    return total_sent


async def _send_retention_message(booking: dict, service: str) -> None:
    """Send a retention re-booking message for a specific booking."""
    phone = booking["phone"]
    name = booking.get("patient_name") or "there"
    lang = booking.get("language", "en")
    bid = booking["id"]

    # Get the message template
    templates = _RETENTION_MESSAGES.get(service, _DEFAULT_RETENTION)
    template = templates.get(lang, templates.get("en", ""))
    body = template.format(name=name, service=service, business=BUSINESS_NAME)

    if lang == "ar":
        btn_book = "📅 احجز الآن"
        btn_skip = "⏭️ ليس الآن"
    else:
        btn_book = "📅 Book Now"
        btn_skip = "⏭️ Not Now"

    buttons = [
        {"id": f"rebook:{bid}", "title": btn_book},
        {"id": f"skip_rebook:{bid}", "title": btn_skip},
    ]

    await send_interactive_buttons(
        to=phone,
        body_text=body,
        buttons=buttons,
        footer_text=BUSINESS_NAME,
    )

    logger.info("Retention message sent for %s to %s (booking #%s)", service, phone, bid)
