"""
Module 5 – AI Review & Reputation Manager

After a positive aftercare response, wait ~2 hours then send a Google
Review request.  The review link is a configurable placeholder for the
prototype.
"""

from __future__ import annotations

import logging

from app import database as db
from app.config import BUSINESS_NAME, GOOGLE_REVIEW_LINK
from app.whatsapp import send_text_message

logger = logging.getLogger(__name__)


async def send_review_request(booking: dict) -> None:
    """
    Send a Google Review request to a patient who gave positive feedback.
    Called by the scheduler ~2 hours after a positive aftercare response.
    """
    bid = booking["id"]
    phone = booking["phone"]
    name = booking.get("patient_name") or "there"
    lang = booking.get("language", "en")

    if lang == "ar":
        message = (
            f"مرحبًا {name}! 😊\n\n"
            f"يسعدنا أنك حظيت بتجربة رائعة في {BUSINESS_NAME}! "
            f"هل يمكنك تخصيص 30 ثانية لمشاركة تقييمك على Google؟ "
            f"يساعد فريقنا كثيرًا! 🌟\n\n"
            f"📝 {GOOGLE_REVIEW_LINK}\n\n"
            f"شكرًا لدعمك! 💖"
        )
    else:
        message = (
            f"Hi {name}! 😊\n\n"
            f"We're so glad you had a great experience at {BUSINESS_NAME}! "
            f"Could you take 30 seconds to share your review on Google? "
            f"It helps our team a lot! 🌟\n\n"
            f"📝 {GOOGLE_REVIEW_LINK}\n\n"
            f"Thank you for your support! 💖"
        )

    await send_text_message(phone, message)
    db.mark_review_sent(bid)
    logger.info("Review request sent to %s for booking #%s", phone, bid)


async def run_review_requests() -> int:
    """
    Check for positive aftercare responses that are ≥ 2 hours old
    and send review requests. Returns count of messages sent.
    """
    bookings = db.get_bookings_for_review_request()
    sent = 0

    for booking in bookings:
        try:
            await send_review_request(booking)
            sent += 1
        except Exception:
            logger.exception(
                "Failed to send review request for booking #%s",
                booking["id"],
            )

    if sent > 0:
        logger.info("Review requests sent: %d", sent)

    return sent
