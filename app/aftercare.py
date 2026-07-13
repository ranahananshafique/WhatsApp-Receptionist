"""
Module 3 – Post-Treatment Follow-Up & Safety Escalation

Handles:
  • 24h aftercare check-in with treatment-specific tips
  • Interactive list menu for patient self-assessment
  • Safety escalation → alert to clinic manager
  • Empathetic disclaimer to patient
"""

from __future__ import annotations

import logging

from app import database as db
from app.config import (
    BUSINESS_NAME,
    CLINIC_MANAGER_PHONE,
    CLINIC_PHONE,
)
from app.whatsapp import send_interactive_list, send_text_message

logger = logging.getLogger(__name__)


# ── Aftercare Tips (per-service, bilingual) ──────────────────────────

AFTERCARE_TIPS: dict[str, dict[str, str]] = {
    "Hydrafacial": {
        "en": (
            "🔆 *Post-Hydrafacial Care:*\n\n"
            "• Avoid direct sun exposure for 24 hours\n"
            "• Skip heavy makeup for 6–12 hours\n"
            "• Stay hydrated – drink plenty of water\n"
            "• Use a gentle moisturiser\n"
            "• Avoid exfoliating products for 48 hours"
        ),
        "ar": (
            "🔆 *نصائح بعد الهيدرافيشيل:*\n\n"
            "• تجنب التعرض المباشر للشمس لمدة 24 ساعة\n"
            "• تجنب المكياج الثقيل لمدة 6-12 ساعة\n"
            "• اشرب الكثير من الماء\n"
            "• استخدم مرطبًا لطيفًا\n"
            "• تجنب منتجات التقشير لمدة 48 ساعة"
        ),
    },
    "Chemical Peel": {
        "en": (
            "🧴 *Post-Chemical Peel Care:*\n\n"
            "• Do NOT pick or peel any flaking skin\n"
            "• Apply SPF 50+ sunscreen every 2 hours outdoors\n"
            "• Use gentle, fragrance-free moisturiser\n"
            "• Avoid saunas and hot water for 48 hours\n"
            "• Mild redness is normal for 24–48 hours"
        ),
        "ar": (
            "🧴 *نصائح بعد التقشير الكيميائي:*\n\n"
            "• لا تقشر أي جلد متقشر\n"
            "• ضع واقي شمس SPF 50+ كل ساعتين في الخارج\n"
            "• استخدم مرطبًا لطيفًا بدون عطر\n"
            "• تجنب الساونا والماء الساخن لمدة 48 ساعة\n"
            "• الاحمرار الخفيف طبيعي لمدة 24-48 ساعة"
        ),
    },
    "Laser Hair Removal": {
        "en": (
            "🔆 *Post-Laser Care:*\n\n"
            "• Avoid sun exposure for 48 hours\n"
            "• Apply aloe vera gel if there's redness\n"
            "• Avoid hot showers, saunas, and gyms for 24 hours\n"
            "• Do NOT shave the treated area for 3–5 days\n"
            "• Wear loose-fitting clothes over the treated area"
        ),
        "ar": (
            "🔆 *نصائح بعد الليزر:*\n\n"
            "• تجنب التعرض للشمس لمدة 48 ساعة\n"
            "• ضع جل الصبار إذا كان هناك احمرار\n"
            "• تجنب الاستحمام بالماء الساخن والساونا والرياضة لمدة 24 ساعة\n"
            "• لا تحلق المنطقة المعالجة لمدة 3-5 أيام\n"
            "• ارتدِ ملابس فضفاضة على المنطقة المعالجة"
        ),
    },
    "Microneedling": {
        "en": (
            "🩹 *Post-Microneedling Care:*\n\n"
            "• Avoid touching your face for 6 hours\n"
            "• Skip all active skincare (retinol, AHA, BHA) for 5 days\n"
            "• Apply only hyaluronic acid serum & gentle moisturiser\n"
            "• Avoid sun exposure – SPF 50+ is mandatory\n"
            "• Redness & swelling are normal for 24–48 hours"
        ),
        "ar": (
            "🩹 *نصائح بعد الوخز بالإبر الدقيقة:*\n\n"
            "• تجنب لمس وجهك لمدة 6 ساعات\n"
            "• تخطَّ جميع منتجات العناية النشطة لمدة 5 أيام\n"
            "• استخدم فقط سيروم حمض الهيالورونيك ومرطب لطيف\n"
            "• تجنب التعرض للشمس – واقي شمس SPF 50+ ضروري\n"
            "• الاحمرار والتورم طبيعيان لمدة 24-48 ساعة"
        ),
    },
    "Deep Cleansing Facial": {
        "en": (
            "✨ *Post-Facial Care:*\n\n"
            "• Avoid touching your face for a few hours\n"
            "• Skip makeup for 12 hours to let pores breathe\n"
            "• Drink plenty of water\n"
            "• Use a gentle cleanser tonight\n"
            "• Avoid exfoliating for 48 hours"
        ),
        "ar": (
            "✨ *نصائح بعد تنظيف البشرة:*\n\n"
            "• تجنب لمس وجهك لعدة ساعات\n"
            "• تجنب المكياج لمدة 12 ساعة\n"
            "• اشرب الكثير من الماء\n"
            "• استخدم غسولًا لطيفًا الليلة\n"
            "• تجنب التقشير لمدة 48 ساعة"
        ),
    },
}

# Fallback tips for services not in the map
_DEFAULT_TIPS = {
    "en": (
        "✨ *Post-Treatment Care:*\n\n"
        "• Follow any specific instructions given by your therapist\n"
        "• Avoid sun exposure and use SPF\n"
        "• Stay hydrated\n"
        "• Contact us if you have any concerns"
    ),
    "ar": (
        "✨ *نصائح بعد العلاج:*\n\n"
        "• اتبع التعليمات الخاصة من المعالج\n"
        "• تجنب التعرض للشمس واستخدم واقي شمس\n"
        "• اشرب الكثير من الماء\n"
        "• تواصل معنا إذا كان لديك أي مخاوف"
    ),
}


# ── Send Aftercare Check-in ──────────────────────────────────────────

async def send_aftercare_checkin(booking: dict) -> None:
    """
    Send aftercare tips for the treatment, followed by an interactive
    list menu asking how the patient is feeling.
    """
    bid = booking["id"]
    phone = booking["phone"]
    name = booking.get("patient_name") or "there"
    service = booking["service"]
    lang = booking.get("language", "en")

    # 1. Send aftercare tips
    tips = AFTERCARE_TIPS.get(service, _DEFAULT_TIPS).get(lang, _DEFAULT_TIPS["en"])

    if lang == "ar":
        greeting = f"مرحبًا {name}! 👋\n\nنأمل أنك استمتعت بجلسة *{service}* في {BUSINESS_NAME} أمس.\n\n"
    else:
        greeting = f"Hi {name}! 👋\n\nWe hope you enjoyed your *{service}* session at {BUSINESS_NAME} yesterday.\n\n"

    await send_text_message(phone, greeting + tips)

    # 2. Send interactive list for self-assessment
    if lang == "ar":
        body = "كيف تشعر بشرتك اليوم؟ يرجى اختيار ما يصف حالتك:"
        button_text = "اختر حالتك"
        section_title = "حالتك"
        rows = [
            {"id": f"perfect:{bid}", "title": "ممتاز ✨", "description": "أشعر بشكل رائع"},
            {"id": f"mild:{bid}", "title": "احمرار خفيف 🟡", "description": "احمرار خفيف أو تورم بسيط"},
            {"id": f"severe:{bid}", "title": "ألم شديد 🚨", "description": "ألم شديد أو تقرحات"},
        ]
    else:
        body = "How is your skin feeling today? Please select what best describes your condition:"
        button_text = "Select Condition"
        section_title = "Your Condition"
        rows = [
            {"id": f"perfect:{bid}", "title": "Perfect ✨", "description": "Feeling great, no issues"},
            {"id": f"mild:{bid}", "title": "Mild Redness 🟡", "description": "Slight redness or minor swelling"},
            {"id": f"severe:{bid}", "title": "Severe Pain 🚨", "description": "Severe pain or blistering"},
        ]

    await send_interactive_list(
        to=phone,
        body_text=body,
        button_text=button_text,
        sections=[{"title": section_title, "rows": rows}],
        footer_text=BUSINESS_NAME,
    )

    db.mark_checkin_sent(bid)
    logger.info("Aftercare check-in sent for booking #%s to %s", bid, phone)


# ── Handle Check-in Response ────────────────────────────────────────

async def handle_checkin_response(
    phone: str, booking_id: int, response: str
) -> str:
    """
    Process the patient's aftercare self-assessment.

    Parameters
    ----------
    response
        One of: ``'perfect'``, ``'mild'``, ``'severe'``

    Returns
    -------
    str
        Reply message to send to the patient.
    """
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        return "Sorry, we couldn't find that booking record."

    lang = booking.get("language", "en")
    name = booking.get("patient_name") or "there"
    service = booking["service"]

    # Save the response
    db.save_checkin_response(booking_id, response)

    if response == "perfect":
        if lang == "ar":
            reply = f"رائع {name}! 😊 يسعدنا أنك بخير بعد جلسة *{service}*. شكرًا لاختيارك {BUSINESS_NAME}! 💖"
        else:
            reply = f"Wonderful, {name}! 😊 We're so glad you're feeling great after your *{service}*. Thank you for choosing {BUSINESS_NAME}! 💖"

    elif response == "mild":
        if lang == "ar":
            reply = (
                f"شكرًا لإخبارنا، {name}. الاحمرار الخفيف طبيعي بعد *{service}* "
                f"ويجب أن يزول خلال 24-48 ساعة. 🙏\n\n"
                f"إذا استمر أو ساءت الحالة، لا تتردد في الاتصال بنا على {CLINIC_PHONE}."
            )
        else:
            reply = (
                f"Thanks for letting us know, {name}. Mild redness is completely normal after *{service}* "
                f"and should subside within 24–48 hours. 🙏\n\n"
                f"If it persists or worsens, don't hesitate to call us at {CLINIC_PHONE}."
            )

    elif response == "severe":
        # ── Safety Escalation ────────────────────────────────
        reply = await _escalate_severe(phone, name, service, booking_id, lang)

    else:
        reply = "Thank you for your response."

    return reply


async def _escalate_severe(
    phone: str, name: str, service: str, booking_id: int, lang: str
) -> str:
    """
    Handle severe symptom report:
    1. Alert clinic manager immediately
    2. Return empathetic disclaimer for the patient
    """
    # 1. Alert the clinic manager
    if CLINIC_MANAGER_PHONE:
        alert = (
            f"🚨 ALERT: Patient {name} ({phone}) reported severe symptoms "
            f"after {service}! (Booking #{booking_id})\n\n"
            f"Please contact the patient immediately."
        )
        await send_text_message(CLINIC_MANAGER_PHONE, alert)
        logger.warning(
            "ESCALATION: Severe symptoms reported by %s after %s (booking #%s)",
            phone, service, booking_id,
        )
    else:
        logger.error(
            "ESCALATION FAILED: No CLINIC_MANAGER_PHONE configured! "
            "Patient %s reported severe symptoms after %s", phone, service,
        )

    # 2. Empathetic disclaimer to the patient
    if lang == "ar":
        return (
            f"نأسف لسماع ذلك، {name}. 😔\n\n"
            f"لقد أبلغنا فريقنا الطبي عن حالتك وسيتواصلون معك قريبًا.\n\n"
            f"إذا كانت هذه حالة طوارئ، يرجى الاتصال بنا مباشرة على "
            f"{CLINIC_PHONE} أو زيارة العيادة فورًا.\n\n"
            f"صحتك أولويتنا القصوى. 🏥"
        )
    return (
        f"We're sorry to hear that, {name}. 😔\n\n"
        f"We have notified our medical team about your condition and they will "
        f"reach out to you shortly.\n\n"
        f"If this is an emergency, please contact us directly at "
        f"{CLINIC_PHONE} or visit the clinic immediately.\n\n"
        f"Your health is our top priority. 🏥"
    )
