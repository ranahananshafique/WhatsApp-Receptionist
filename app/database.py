"""
SQLite persistence layer.

Tables:
  • patients               – patient profile (phone, name, language)
  • conversation_history   – per-user message log (last N messages kept)
  • bookings               – appointment records with status tracking

All public functions are plain *sync* helpers (SQLite is inherently sync);
FastAPI endpoints call them via `run_in_executor` or directly since the I/O
is local and sub-millisecond.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Generator

from app.config import DB_PATH, MAX_HISTORY_MESSAGES, PREMIUM_SERVICES

logger = logging.getLogger(__name__)


# ── Connection helper ─────────────────────────────────────────────────

def _ensure_data_dir() -> None:
    """Create the data/ directory if it doesn't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context-managed SQLite connection with WAL mode for concurrency."""
    _ensure_data_dir()
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Schema initialisation ────────────────────────────────────────────

def init_db() -> None:
    """Create tables if they don't exist.  Called once at app startup."""
    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients (
                phone       TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                language    TEXT NOT NULL DEFAULT 'en',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS conversation_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                phone       TEXT    NOT NULL,
                role        TEXT    NOT NULL CHECK(role IN ('user','assistant','system')),
                content     TEXT    NOT NULL,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_conv_phone
                ON conversation_history(phone);

            CREATE TABLE IF NOT EXISTS bookings (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                phone               TEXT    NOT NULL,
                patient_name        TEXT    NOT NULL DEFAULT '',
                service             TEXT    NOT NULL,
                date                TEXT    NOT NULL,
                time                TEXT    NOT NULL,
                status              TEXT    NOT NULL DEFAULT 'pending',
                is_premium          INTEGER NOT NULL DEFAULT 0,
                payment_status      TEXT    NOT NULL DEFAULT 'none',
                reminder_24h_sent   INTEGER NOT NULL DEFAULT 0,
                reminder_3h_sent    INTEGER NOT NULL DEFAULT 0,
                completed_at        TEXT    DEFAULT NULL,
                checkin_24h_sent    INTEGER NOT NULL DEFAULT 0,
                checkin_response    TEXT    DEFAULT NULL,
                review_request_sent INTEGER NOT NULL DEFAULT 0,
                retention_sent_at   TEXT    DEFAULT NULL,
                language            TEXT    NOT NULL DEFAULT 'en',
                created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_bookings_phone
                ON bookings(phone);
            """
        )
    # Run migration for existing databases
    _run_migration()


def _run_migration() -> None:
    """
    Safely add new columns to existing tables.
    Each ALTER is wrapped in try/except so it's idempotent.
    """
    new_columns = [
        ("bookings", "patient_name",        "TEXT NOT NULL DEFAULT ''"),
        ("bookings", "is_premium",          "INTEGER NOT NULL DEFAULT 0"),
        ("bookings", "payment_status",      "TEXT NOT NULL DEFAULT 'none'"),
        ("bookings", "reminder_24h_sent",   "INTEGER NOT NULL DEFAULT 0"),
        ("bookings", "reminder_3h_sent",    "INTEGER NOT NULL DEFAULT 0"),
        ("bookings", "completed_at",        "TEXT DEFAULT NULL"),
        ("bookings", "checkin_24h_sent",    "INTEGER NOT NULL DEFAULT 0"),
        ("bookings", "checkin_response",    "TEXT DEFAULT NULL"),
        ("bookings", "review_request_sent", "INTEGER NOT NULL DEFAULT 0"),
        ("bookings", "retention_sent_at",   "TEXT DEFAULT NULL"),
        ("bookings", "language",            "TEXT NOT NULL DEFAULT 'en'"),
    ]
    with get_connection() as conn:
        for table, column, col_type in new_columns:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                logger.info("Migration: added %s.%s", table, column)
            except sqlite3.OperationalError:
                pass  # Column already exists

        # Ensure patients table exists for upgrades from earlier schema
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                phone       TEXT PRIMARY KEY,
                name        TEXT NOT NULL DEFAULT '',
                language    TEXT NOT NULL DEFAULT 'en',
                created_at  TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )


# ── Patients ─────────────────────────────────────────────────────────

def upsert_patient(phone: str, name: str = "", language: str = "en") -> None:
    """Insert or update a patient record."""
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO patients (phone, name, language, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(phone) DO UPDATE SET
                name = CASE WHEN excluded.name != '' THEN excluded.name ELSE patients.name END,
                language = excluded.language,
                updated_at = datetime('now')
            """,
            (phone, name, language),
        )


def get_patient(phone: str) -> dict | None:
    """Return patient record or None."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM patients WHERE phone = ?", (phone,)
        ).fetchone()
    return dict(row) if row else None


# ── Conversation History ─────────────────────────────────────────────

def save_message(phone: str, role: str, content: str) -> None:
    """Append a message and prune to keep only the latest N per user."""
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO conversation_history (phone, role, content) VALUES (?, ?, ?)",
            (phone, role, content),
        )
        # Prune: keep only the latest MAX_HISTORY_MESSAGES rows per phone
        conn.execute(
            """
            DELETE FROM conversation_history
            WHERE phone = ? AND id NOT IN (
                SELECT id FROM conversation_history
                WHERE phone = ?
                ORDER BY id DESC
                LIMIT ?
            )
            """,
            (phone, phone, MAX_HISTORY_MESSAGES),
        )


def get_history(phone: str) -> list[dict]:
    """
    Return the last N messages for a phone number as a list of
    ``{"role": ..., "content": ...}`` dicts suitable for the Chat
    Completions API.
    """
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT role, content FROM conversation_history
            WHERE phone = ?
            ORDER BY id ASC
            """,
            (phone,),
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in rows]


def clear_history(phone: str) -> None:
    """Wipe conversation memory for a user (useful for /reset commands)."""
    with get_connection() as conn:
        conn.execute("DELETE FROM conversation_history WHERE phone = ?", (phone,))


# ── Bookings ─────────────────────────────────────────────────────────

def create_mock_booking(
    phone: str,
    service: str,
    date: str,
    time: str,
    patient_name: str = "",
    language: str = "en",
) -> dict:
    """
    Insert a booking row and return a confirmation dict.
    Automatically flags premium services.

    Returns
    -------
    dict
        ``{"booking_id": int, "phone": str, "service": str,
           "date": str, "time": str, "status": "pending",
           "is_premium": bool}``
    """
    is_premium = 1 if service in PREMIUM_SERVICES else 0
    with get_connection() as conn:
        conn.execute(
            "UPDATE bookings SET status = 'cancelled' WHERE phone = ? AND status = 'pending'",
            (phone,),
        )
        cursor = conn.execute(
            """
            INSERT INTO bookings
                (phone, patient_name, service, date, time, status, is_premium, language)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (phone, patient_name, service, date, time, is_premium, language),
        )
        booking_id = cursor.lastrowid

    return {
        "booking_id": booking_id,
        "phone": phone,
        "patient_name": patient_name,
        "service": service,
        "date": date,
        "time": time,
        "status": "pending",
        "is_premium": bool(is_premium),
    }


def get_bookings(phone: str) -> list[dict]:
    """Return all bookings for a given phone number."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE phone = ? ORDER BY id DESC",
            (phone,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_booking_by_id(booking_id: int) -> dict | None:
    """Return a single booking by ID."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE id = ?", (booking_id,)
        ).fetchone()
    return dict(row) if row else None


def get_pending_booking(phone: str) -> dict | None:
    """Return the most recent pending booking awaiting review/confirmation for a phone number."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM bookings WHERE phone = ? AND status = 'pending' ORDER BY id DESC LIMIT 1",
            (phone,),
        ).fetchone()
    return dict(row) if row else None


def update_booking_status(booking_id: int, status: str) -> None:
    """Update the status of a booking."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE bookings SET status = ? WHERE id = ?",
            (status, booking_id),
        )


def update_payment_status(booking_id: int, payment_status: str) -> None:
    """Update the payment status of a booking."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE bookings SET payment_status = ? WHERE id = ?",
            (payment_status, booking_id),
        )


def mark_booking_completed(booking_id: int) -> None:
    """Mark a booking as completed with a timestamp."""
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE bookings SET status = 'completed', completed_at = datetime('now')
            WHERE id = ?
            """,
            (booking_id,),
        )


# ── Module 2: Reminder Queries ───────────────────────────────────────

def get_bookings_needing_24h_reminder() -> list[dict]:
    """
    Return bookings whose appointment is 23–25 hours from now,
    reminder not yet sent, and not cancelled/completed.
    """
    now = datetime.now()
    window_start = (now + timedelta(hours=23)).strftime("%Y-%m-%d %H:%M")
    window_end = (now + timedelta(hours=25)).strftime("%Y-%m-%d %H:%M")

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bookings
            WHERE (date || ' ' || time) BETWEEN ? AND ?
              AND reminder_24h_sent = 0
              AND status NOT IN ('cancelled', 'completed', 'no_show')
            """,
            (window_start, window_end),
        ).fetchall()
    return [dict(r) for r in rows]


def get_bookings_needing_3h_reminder() -> list[dict]:
    """
    Return bookings whose appointment is 2.5–3.5 hours from now,
    reminder not yet sent, and confirmed/deposited.
    """
    now = datetime.now()
    window_start = (now + timedelta(hours=2, minutes=30)).strftime("%Y-%m-%d %H:%M")
    window_end = (now + timedelta(hours=3, minutes=30)).strftime("%Y-%m-%d %H:%M")

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bookings
            WHERE (date || ' ' || time) BETWEEN ? AND ?
              AND reminder_3h_sent = 0
              AND status IN ('confirmed', 'deposited')
            """,
            (window_start, window_end),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_reminder_sent(booking_id: int, reminder_column: str) -> None:
    """Mark a reminder as sent (reminder_24h_sent or reminder_3h_sent)."""
    assert reminder_column in ("reminder_24h_sent", "reminder_3h_sent")
    with get_connection() as conn:
        conn.execute(
            f"UPDATE bookings SET {reminder_column} = 1 WHERE id = ?",
            (booking_id,),
        )


# ── Module 3: Aftercare Queries ──────────────────────────────────────

def get_bookings_needing_aftercare_checkin() -> list[dict]:
    """
    Return bookings completed ~24h ago where the check-in hasn't been sent.
    Window: 23–25 hours after completed_at.
    """
    now = datetime.now()
    window_start = (now - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M")
    window_end = (now - timedelta(hours=23)).strftime("%Y-%m-%d %H:%M")

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bookings
            WHERE status = 'completed'
              AND completed_at BETWEEN ? AND ?
              AND checkin_24h_sent = 0
            """,
            (window_start, window_end),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_checkin_sent(booking_id: int) -> None:
    """Mark the aftercare check-in as sent."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE bookings SET checkin_24h_sent = 1 WHERE id = ?",
            (booking_id,),
        )


def save_checkin_response(booking_id: int, response: str) -> None:
    """Save the patient's aftercare check-in response."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE bookings SET checkin_response = ? WHERE id = ?",
            (response, booking_id),
        )


# ── Module 4: Retention Queries ──────────────────────────────────────

def get_bookings_for_retention(service: str, days_ago: int) -> list[dict]:
    """
    Return completed bookings for a specific service that were completed
    approximately `days_ago` days ago (±2 day window) with no retention
    message sent yet, AND the patient has no future bookings.
    """
    now = datetime.now()
    window_start = (now - timedelta(days=days_ago + 2)).strftime("%Y-%m-%d %H:%M")
    window_end = (now - timedelta(days=days_ago - 2)).strftime("%Y-%m-%d %H:%M")
    today = now.strftime("%Y-%m-%d")

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT b.* FROM bookings b
            WHERE b.status = 'completed'
              AND b.service = ?
              AND b.completed_at BETWEEN ? AND ?
              AND b.retention_sent_at IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM bookings b2
                  WHERE b2.phone = b.phone
                    AND b2.date >= ?
                    AND b2.status NOT IN ('cancelled', 'no_show')
              )
            """,
            (service, window_start, window_end, today),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_retention_sent(booking_id: int) -> None:
    """Mark a booking as having had its retention campaign sent."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE bookings SET retention_sent_at = datetime('now') WHERE id = ?",
            (booking_id,),
        )


# ── Module 5: Review Queries ────────────────────────────────────────

def get_bookings_for_review_request() -> list[dict]:
    """
    Return bookings where:
    - Patient gave a positive aftercare response ('perfect' or 'mild')
    - Check-in response was saved ≥ 2 hours ago
    - Review request not yet sent
    """
    cutoff = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT * FROM bookings
            WHERE checkin_response IN ('perfect', 'mild')
              AND review_request_sent = 0
              AND checkin_24h_sent = 1
              AND completed_at <= ?
            """,
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def mark_review_sent(booking_id: int) -> None:
    """Mark the review request as sent."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE bookings SET review_request_sent = 1 WHERE id = ?",
            (booking_id,),
        )
