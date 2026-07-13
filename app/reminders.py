"""
Module 2 – No-Show Reduction AI

Handles:
  • T-24h confirmation reminders with interactive buttons
  • Premium deposit simulation (Pay & Confirm button)
  • T-3h final reminders with clinic location pin
  • Button callback handlers for confirm / pay / reschedule
"""

from __future__ import annotations

import logging

from app import database as db
from app.config import (
    BUSINESS_NAME,
    CLINIC_ADDRESS,
    CLINIC_LATITUDE,
    CLINIC_LONGITUDE,
    DEPOSIT_AMOUNT_AED,
)
from app.whatsapp import (
    send_interactive_buttons,
    send_location_message,
    send_text_message,
)

logger = logging.getLogger(__name__)


# ── T-24h Reminder ───────────────────────────────────────────────────

async def send_24h_reminder(booking: dict) -> None:
    """
    Send the T-24h confirmation message.
    - Standard services → 2 buttons: [✅ Confirm] [📅 Reschedule]
    - Premium services  → 3 buttons: [✅ Confirm] [💳 Pay & Confirm] [📅 Reschedule]
    """
    bid = booking["id"]
    phone = booking["phone"]
    name = booking.get("patient_name") or "there"
    service = booking["service"]
    time_str = booking["time"]
    date_str = booking["date"]
    lang = booking.get("language", "en")

    if lang == "ar":
        body = (
            f"مرحبًا {name}! 👋\n\n"
            f"هذا تذكير بأن موعد *{service}* في {BUSINESS_NAME} "
            f"غدًا {date_str} الساعة {time_str}.\n\n"
            f"يرجى التأكيد أو إعادة الجدولة:"
        )
        btn_confirm = "✅ تأكيد"
        btn_pay = "💳 دفع وتأكيد"
        btn_reschedule = "📅 إعادة جدولة"
    else:
        body = (
            f"Hi {name}! 👋\n\n"
            f"This is a reminder that your *{service}* appointment at {BUSINESS_NAME} "
            f"is tomorrow, {date_str} at {time_str}.\n\n"
            f"Please confirm or reschedule:"
        )
        btn_confirm = "✅ Confirm"
        btn_pay = "💳 Pay & Confirm"
        btn_reschedule = "📅 Reschedule"

    buttons = [
        {"id": f"confirm:{bid}", "title": btn_confirm},
    ]

    # Premium services get the deposit simulation button
    if booking.get("is_premium") and booking.get("payment_status", "none") == "none":
        if lang == "ar":
            body += f"\n\n💎 هذه خدمة مميزة. ادفع وديعة {DEPOSIT_AMOUNT_AED} درهم لتأمين موعدك."
        else:
            body += f"\n\n💎 This is a premium service. Pay a {DEPOSIT_AMOUNT_AED} AED deposit to lock in your slot."
        buttons.append({"id": f"pay:{bid}", "title": btn_pay})

    buttons.append({"id": f"reschedule:{bid}", "title": btn_reschedule})

    await send_interactive_buttons(
        to=phone,
        body_text=body,
        buttons=buttons,
        footer_text=BUSINESS_NAME,
    )

    db.mark_reminder_sent(bid, "reminder_24h_sent")
    logger.info("T-24h reminder sent for booking #%s to %s", bid, phone)


# ── T-3h Final Reminder ─────────────────────────────────────────────

async def send_3h_reminder(booking: dict) -> None:
    """Send the T-3h final reminder with clinic location pin."""
    bid = booking["id"]
    phone = booking["phone"]
    name = booking.get("patient_name") or "there"
    service = booking["service"]
    time_str = booking["time"]
    lang = booking.get("language", "en")

    if lang == "ar":
        text = (
            f"نراك بعد 3 ساعات! 🕒\n\n"
            f"موعد *{service}* في {BUSINESS_NAME} الساعة {time_str}.\n"
            f"إليك موقعنا 📍"
        )
    else:
        text = (
            f"See you in 3 hours, {name}! 🕒\n\n"
            f"Your *{service}* appointment at {BUSINESS_NAME} is at {time_str}.\n"
            f"Here's our location 📍"
        )

    await send_text_message(phone, text)
    await send_location_message(
        to=phone,
        latitude=float(CLINIC_LATITUDE),
        longitude=float(CLINIC_LONGITUDE),
        name=BUSINESS_NAME,
        address=CLINIC_ADDRESS,
    )

    db.mark_reminder_sent(bid, "reminder_3h_sent")
    logger.info("T-3h reminder sent for booking #%s to %s", bid, phone)


# ── Button Callback Handlers ────────────────────────────────────────

async def handle_confirmation(booking_id: int, phone: str) -> str:
    """Handle [✅ Confirm] button tap. Returns reply text."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        return "Sorry, we couldn't find that booking."

    db.update_booking_status(booking_id, "confirmed")
    lang = booking.get("language", "en")

    if lang == "ar":
        return (
            f"✅ تم تأكيد موعدك!\n\n"
            f"📋 الخدمة: {booking['service']}\n"
            f"📅 التاريخ: {booking['date']}\n"
            f"🕐 الوقت: {booking['time']}\n\n"
            f"نتطلع لرؤيتك! 😊"
        )
    return (
        f"✅ Your appointment is confirmed!\n\n"
        f"📋 Service: {booking['service']}\n"
        f"📅 Date: {booking['date']}\n"
        f"🕐 Time: {booking['time']}\n\n"
        f"We look forward to seeing you! 😊"
    )


async def handle_pay_confirm(booking_id: int, phone: str) -> str:
    """Handle [💳 Pay & Confirm] button tap — simulated payment."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        return "Sorry, we couldn't find that booking."

    db.update_booking_status(booking_id, "deposited")
    db.update_payment_status(booking_id, "paid")
    lang = booking.get("language", "en")

    if lang == "ar":
        return (
            f"💳 تم الدفع بنجاح! تم معالجة وديعة {DEPOSIT_AMOUNT_AED} درهم "
            f"وتم تأمين موعدك رسميًا. نراك غدًا! 🎉"
        )
    return (
        f"💳 Payment successful! Your {DEPOSIT_AMOUNT_AED} AED deposit has been "
        f"processed and your slot is officially locked in. See you tomorrow! 🎉"
    )


async def handle_reschedule(booking_id: int, phone: str) -> str:
    """Handle [📅 Reschedule] button tap — hand off to LLM flow."""
    booking = db.get_booking_by_id(booking_id)
    if not booking:
        return "Sorry, we couldn't find that booking."

    db.update_booking_status(booking_id, "cancelled")
    lang = booking.get("language", "en")

    if lang == "ar":
        return (
            f"لا مشكلة! تم إلغاء موعدك السابق لـ *{booking['service']}*.\n\n"
            f"متى تود إعادة الحجز؟ يرجى إخباري بالتاريخ والوقت المفضلين. 📅"
        )
    return (
        f"No problem! Your previous *{booking['service']}* appointment has been cancelled.\n\n"
        f"When would you like to reschedule? Please let me know your preferred date and time. 📅"
    )
