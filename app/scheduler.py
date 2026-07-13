"""
APScheduler cron engine – runs inside the FastAPI process.

Registered jobs:
  ┌──────────────────────┬────────────┬──────────────────────────────────┐
  │ Job                  │ Interval   │ Module                           │
  ├──────────────────────┼────────────┼──────────────────────────────────┤
  │ job_reminder_24h     │ 15 min     │ Module 2 – T-24h confirmation    │
  │ job_reminder_3h      │ 15 min     │ Module 2 – T-3h final reminder   │
  │ job_aftercare_checkin│ 30 min     │ Module 3 – 24h post-treatment    │
  │ job_review_requests  │ 30 min     │ Module 5 – Google review prompt  │
  │ job_retention_weekly │ Weekly Mon │ Module 4 – Cohort re-booking     │
  └──────────────────────┴────────────┴──────────────────────────────────┘

All jobs catch their own exceptions so one failure doesn't kill the
scheduler.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import database as db
from app.aftercare import send_aftercare_checkin
from app.reminders import send_24h_reminder, send_3h_reminder
from app.retention import run_retention_scan
from app.reviews import run_review_requests

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


# ── Job Functions ────────────────────────────────────────────────────

async def job_reminder_24h() -> None:
    """Send T-24h confirmation reminders for upcoming bookings."""
    try:
        bookings = db.get_bookings_needing_24h_reminder()
        for booking in bookings:
            try:
                await send_24h_reminder(booking)
            except Exception:
                logger.exception("Failed T-24h reminder for booking #%s", booking["id"])
        if bookings:
            logger.info("T-24h job: processed %d bookings", len(bookings))
    except Exception:
        logger.exception("T-24h reminder job failed")


async def job_reminder_3h() -> None:
    """Send T-3h final reminders for upcoming bookings."""
    try:
        bookings = db.get_bookings_needing_3h_reminder()
        for booking in bookings:
            try:
                await send_3h_reminder(booking)
            except Exception:
                logger.exception("Failed T-3h reminder for booking #%s", booking["id"])
        if bookings:
            logger.info("T-3h job: processed %d bookings", len(bookings))
    except Exception:
        logger.exception("T-3h reminder job failed")


async def job_aftercare_checkin() -> None:
    """Send 24h aftercare check-ins for completed bookings."""
    try:
        bookings = db.get_bookings_needing_aftercare_checkin()
        for booking in bookings:
            try:
                await send_aftercare_checkin(booking)
            except Exception:
                logger.exception("Failed aftercare check-in for booking #%s", booking["id"])
        if bookings:
            logger.info("Aftercare job: processed %d bookings", len(bookings))
    except Exception:
        logger.exception("Aftercare check-in job failed")


async def job_review_requests() -> None:
    """Send Google Review requests to patients with positive feedback."""
    try:
        await run_review_requests()
    except Exception:
        logger.exception("Review request job failed")


async def job_retention_weekly() -> None:
    """Run the weekly retention campaign scan."""
    try:
        count = await run_retention_scan()
        logger.info("Retention weekly job: sent %d messages", count)
    except Exception:
        logger.exception("Retention campaign job failed")


# ── Scheduler Lifecycle ─────────────────────────────────────────────

def start_scheduler() -> None:
    """Initialise and start the APScheduler with all registered jobs."""
    global _scheduler

    _scheduler = AsyncIOScheduler()

    # Module 2: T-24h reminders — every 15 minutes
    _scheduler.add_job(
        job_reminder_24h,
        trigger=IntervalTrigger(minutes=15),
        id="job_reminder_24h",
        name="T-24h Appointment Reminders",
        replace_existing=True,
    )

    # Module 2: T-3h reminders — every 15 minutes
    _scheduler.add_job(
        job_reminder_3h,
        trigger=IntervalTrigger(minutes=15),
        id="job_reminder_3h",
        name="T-3h Final Reminders",
        replace_existing=True,
    )

    # Module 3: Aftercare check-in — every 30 minutes
    _scheduler.add_job(
        job_aftercare_checkin,
        trigger=IntervalTrigger(minutes=30),
        id="job_aftercare_checkin",
        name="24h Aftercare Check-in",
        replace_existing=True,
    )

    # Module 5: Review requests — every 30 minutes
    _scheduler.add_job(
        job_review_requests,
        trigger=IntervalTrigger(minutes=30),
        id="job_review_requests",
        name="Google Review Requests",
        replace_existing=True,
    )

    # Module 4: Retention campaigns — every Monday at 10:00 AM
    _scheduler.add_job(
        job_retention_weekly,
        trigger=CronTrigger(day_of_week="mon", hour=10, minute=0),
        id="job_retention_weekly",
        name="Weekly Retention Campaigns",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
        _scheduler = None


def get_scheduler() -> AsyncIOScheduler | None:
    """Return the active scheduler instance (for inspection/testing)."""
    return _scheduler
