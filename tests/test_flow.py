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

BASE = "http://localhost:8000"


def _whatsapp_payload(phone: str, text: str, name: str = "Test User") -> dict:
    """Build a realistic Twilio WhatsApp webhook payload."""
    phone = phone.lstrip('+')
    return {
        "From": f"whatsapp:+{phone}",
        "To": "whatsapp:+14155238886",
        "Body": text,
        "ProfileName": name,
    }


def main() -> None:
    client = httpx.Client(base_url=BASE, timeout=30)

    print("=" * 60)
    print("  Apex Clinic – WhatsApp AI Receptionist Test Suite")
    print("=" * 60)

    # ── 1. Health check ───────────────────────────────────────────────
    print("\n🩺 [1] Health check...")
    r = client.get("/health")
    assert r.status_code == 200, f"Health check failed: {r.text}"
    print(f"   ✅ {r.json()}")

    # ── 2. Webhook verification ───────────────────────────────────────
    print("\n🔐 [2] Webhook verification (Skipped for Twilio)...")
    print("   ✅ Skipped")

    # ── 3. English greeting ───────────────────────────────────────────
    print("\n💬 [3] English greeting...")
    payload = _whatsapp_payload("971501234567", "Hi, what services do you offer?")
    r = client.post("/webhook", data=payload)
    print(f"   Status: {r.status_code}")
    print(f"   Response: {json.dumps(r.json(), indent=2)}")

    # ── 4. Arabic greeting ────────────────────────────────────────────
    print("\n💬 [4] Arabic greeting...")
    payload = _whatsapp_payload(
        "971509876543",
        "مرحبا، ما هي الخدمات المتوفرة لديكم؟",
        name="أحمد",
    )
    r = client.post("/webhook", data=payload)
    print(f"   Status: {r.status_code}")
    print(f"   Response: {json.dumps(r.json(), indent=2)}")

    # ── 5. Booking request ────────────────────────────────────────────
    print("\n📅 [5] Booking request (English)...")
    payload = _whatsapp_payload(
        "971507777777",
        "I'd like to book Teeth Whitening for 2026-07-10 at 10:00 AM please.",
        name="Booking Tester",
    )
    r = client.post("/webhook", data=payload)
    print(f"   Status: {r.status_code}")
    print(f"   Response: {json.dumps(r.json(), indent=2)}")

    # ── 6. Check bookings ─────────────────────────────────────────────
    print("\n📋 [6] Checking bookings for 971507777777...")
    r = client.get("/bookings/971507777777")
    print(f"   {json.dumps(r.json(), indent=2)}")

    # ── 7. Check history ──────────────────────────────────────────────
    print("\n💾 [7] Checking history for 971501234567...")
    r = client.get("/history/971501234567")
    print(f"   {json.dumps(r.json(), indent=2)}")

    # ── 8. Missed-call follow-up ──────────────────────────────────────
    print("\n📞 [8] Missed-call follow-up...")
    r = client.post("/missed-call", json={"phone_number": "+971501234567"})
    print(f"   Status: {r.status_code}")
    print(f"   Response: {json.dumps(r.json(), indent=2)}")

    print("\n" + "=" * 60)
    print("  ✅ All tests completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
