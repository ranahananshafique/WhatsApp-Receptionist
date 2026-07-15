"""
End-to-end test script that simulates WhatsApp webhook calls against
the running FastAPI server.  Run with:

    python -m tests.test_flow

Requires the server to be running on http://localhost:8000.
"""

from __future__ import annotations

import json
import sys
import httpx
from fastapi.testclient import TestClient
from app.main import app

BASE = "http://localhost:8000"


def _whatsapp_payload(phone: str, text: str, name: str = "Test User") -> dict:
    """Build a realistic Meta WhatsApp webhook payload."""
    phone = phone.lstrip('+')
    return {
        "object": "whatsapp_business_account",
        "entry": [{
            "id": "BUSINESS_ID",
            "changes": [{
                "field": "messages",
                "value": {
                    "messaging_product": "whatsapp",
                    "contacts": [{"profile": {"name": name}, "wa_id": phone}],
                    "messages": [{
                        "from": phone,
                        "id": "wamid.test123",
                        "timestamp": "1719878400",
                        "type": "text",
                        "text": {"body": text}
                    }]
                }
            }]
        }]
    }


def _get_client():
    try:
        client = httpx.Client(base_url=BASE, timeout=5)
        r = client.get("/health")
        if r.status_code == 200:
            return client
    except Exception:
        pass
    return TestClient(app)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    from app.database import get_connection
    with get_connection() as conn:
        for p in ("971501234567", "971509876543", "971507777777"):
            conn.execute("DELETE FROM bookings WHERE phone = ?", (p,))
            conn.execute("DELETE FROM conversation_history WHERE phone = ?", (p,))

    client = _get_client()

    print("=" * 60)
    print("  Apex Clinic – WhatsApp AI Receptionist Test Suite")
    print("=" * 60)

    # ── 1. Health check ───────────────────────────────────────────────
    print("\n🩺 [1] Health check...")
    r = client.get("/health")
    assert r.status_code == 200, f"Health check failed: {r.text}"
    print(f"   ✅ {r.json()}")

    # ── 2. Webhook verification ───────────────────────────────────────
    print("\n🔐 [2] Webhook verification...")
    r = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "quantx",
            "hub.challenge": "CHALLENGE_ACCEPTED",
        },
    )
    assert r.status_code == 200 and r.text == "CHALLENGE_ACCEPTED", f"Verify failed: {r.text}"
    print("   ✅ Verification passed")

    # ── 3. English greeting ───────────────────────────────────────────
    print("\n💬 [3] English greeting...")
    payload = _whatsapp_payload("971501234567", "Hi, what services do you offer?")
    r = client.post("/webhook", json=payload)
    print(f"   Status: {r.status_code}")
    print(f"   Response: {json.dumps(r.json(), indent=2)}")
    r_hist_en = client.get("/history/971501234567")
    history_data_en = r_hist_en.json().get("history", [])
    last_msg_en = next((msg["content"] for msg in reversed(history_data_en) if msg["role"] == "assistant"), "")
    assert "Welcome to" in last_msg_en and "Hydrafacial" in last_msg_en, f"English greeting response missing intro/services: {last_msg_en}"
    print("   ✅ English greeting verified:\n" + "\n".join("      " + line for line in last_msg_en.splitlines()))

    # ── 4. Arabic greeting ────────────────────────────────────────────
    print("\n💬 [4] Arabic greeting...")
    payload = _whatsapp_payload(
        "971509876543",
        "مرحبا، ما هي الخدمات المتوفرة لديكم؟",
        name="أحمد",
    )
    r = client.post("/webhook", json=payload)
    print(f"   Status: {r.status_code}")
    print(f"   Response: {json.dumps(r.json(), indent=2)}")
    r_hist_ar = client.get("/history/971509876543")
    history_data_ar = r_hist_ar.json().get("history", [])
    last_msg_ar = next((msg["content"] for msg in reversed(history_data_ar) if msg["role"] == "assistant"), "")
    assert "مرحباً بك في" in last_msg_ar and "هيدرافيشيل" in last_msg_ar, f"Arabic greeting response missing intro/services: {last_msg_ar}"
    print("   ✅ Arabic greeting verified:\n" + "\n".join("      " + line for line in last_msg_ar.splitlines()))

    # ── 5. Booking request (Review Step) ──────────────────────────────
    print("\n📅 [5] Booking request (Review details step)...")
    payload = _whatsapp_payload(
        "971507777777",
        "I'd like to book Teeth Whitening for 2026-07-10 at 10:00 AM please.",
        name="Booking Tester",
    )
    r = client.post("/webhook", json=payload)
    print(f"   Status: {r.status_code}")

    # Verify booking is created in pending state and review details are displayed
    r_book = client.get("/bookings/971507777777")
    bookings_data = r_book.json().get("bookings", [])
    assert len(bookings_data) > 0, "Expected at least one booking created"
    latest_booking = bookings_data[0]
    assert latest_booking["status"] == "pending", f"Expected pending status before confirmation, got {latest_booking['status']}"
    print(f"   ✅ Pending review booking created: #{latest_booking['id']} - {latest_booking['patient_name']} ({latest_booking['service']})")

    # Check conversation history to verify review details were presented
    r_hist = client.get("/history/971507777777")
    history_data = r_hist.json().get("history", [])
    last_assistant_msg = next((msg["content"] for msg in reversed(history_data) if msg["role"] == "assistant"), "")
    assert "Booking ID" in last_assistant_msg and "Booking Name" in last_assistant_msg, f"Review message missing details: {last_assistant_msg}"
    print("   ✅ Review message displayed details properly:\n" + "\n".join("      " + line for line in last_assistant_msg.splitlines()))

    # ── 6. Booking confirmation ───────────────────────────────────────
    print("\n✅ [6] Booking confirmation step...")
    payload_confirm = _whatsapp_payload(
        "971507777777",
        "Yes, please confirm my booking!",
        name="Booking Tester",
    )
    r = client.post("/webhook", json=payload_confirm)
    print(f"   Status: {r.status_code}")

    r_book_after = client.get("/bookings/971507777777")
    latest_booking_after = r_book_after.json().get("bookings", [])[0]
    assert latest_booking_after["status"] == "confirmed", f"Expected confirmed status after confirmation, got {latest_booking_after['status']}"
    print(f"   ✅ Booking #{latest_booking_after['id']} successfully confirmed!")

    r_hist_after = client.get("/history/971507777777")
    history_data_after = r_hist_after.json().get("history", [])
    confirm_msg = next((msg["content"] for msg in reversed(history_data_after) if msg["role"] == "assistant"), "")
    print("   ✅ Confirmation message:\n" + "\n".join("      " + line for line in confirm_msg.splitlines()))

    # ── 7. Check bookings list ────────────────────────────────────────
    print("\n📋 [7] Checking bookings for 971507777777...")
    r = client.get("/bookings/971507777777")
    print(f"   {json.dumps(r.json(), indent=2)}")

    # ── 8. Check history ──────────────────────────────────────────────
    print("\n💾 [8] Checking history for 971501234567...")
    r = client.get("/history/971501234567")
    print(f"   {json.dumps(r.json(), indent=2)}")

    # ── 9. Missed-call follow-up ──────────────────────────────────────
    print("\n📞 [9] Missed-call follow-up...")
    r = client.post("/missed-call", json={"phone_number": "+971501234567"})
    print(f"   Status: {r.status_code}")
    print(f"   Response: {json.dumps(r.json(), indent=2)}")

    print("\n" + "=" * 60)
    print("  ✅ All tests completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
