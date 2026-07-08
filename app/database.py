"""
SQLite persistence layer.

Two tables:
  • conversation_history – per-user message log (last N messages kept)
  • bookings              – mock appointment records

All public functions are plain *sync* helpers (SQLite is inherently sync);
FastAPI endpoints call them via `run_in_executor` or directly since the I/O
is local and sub-millisecond.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator

from app.config import DB_PATH, MAX_HISTORY_MESSAGES


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
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                phone       TEXT    NOT NULL,
                service     TEXT    NOT NULL,
                date        TEXT    NOT NULL,
                time        TEXT    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'confirmed',
                created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_bookings_phone
                ON bookings(phone);
            """
        )


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
) -> dict:
    """
    Insert a booking row and return a confirmation dict.

    Returns
    -------
    dict
        ``{"booking_id": int, "phone": str, "service": str,
           "date": str, "time": str, "status": "confirmed"}``
    """
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO bookings (phone, service, date, time)
            VALUES (?, ?, ?, ?)
            """,
            (phone, service, date, time),
        )
        booking_id = cursor.lastrowid

    return {
        "booking_id": booking_id,
        "phone": phone,
        "service": service,
        "date": date,
        "time": time,
        "status": "confirmed",
    }


def get_bookings(phone: str) -> list[dict]:
    """Return all bookings for a given phone number."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM bookings WHERE phone = ? ORDER BY id DESC",
            (phone,),
        ).fetchall()
    return [dict(r) for r in rows]
