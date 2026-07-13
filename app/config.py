"""
Centralised configuration loaded from environment variables with sensible
defaults.  All secrets and tunables live here so the rest of the codebase
stays clean.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Load .env if present ──────────────────────────────────────────────
load_dotenv()

# ── Paths ─────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "receptionist.db"

# ── Meta WhatsApp Cloud API ───────────────────────────────────────────
WHATSAPP_VERIFY_TOKEN: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "apex_clinic_verify_token")
WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")

# ── LLM (Qwen 2.5 via OpenAI-compatible API) ─────────────────────────
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY: str = os.getenv("LLM_API_KEY", "not-needed")  # local server
LLM_MODEL: str = os.getenv("LLM_MODEL", "qwen2.5:3b")
LLM_MAX_TOKENS: int = int(os.getenv("LLM_MAX_TOKENS", "512"))
LLM_TEMPERATURE: float = float(os.getenv("LLM_TEMPERATURE", "0.3"))

# ── Session / Memory ─────────────────────────────────────────────────
MAX_HISTORY_MESSAGES: int = int(os.getenv("MAX_HISTORY_MESSAGES", "10"))

# ── Business Information (injected into the system prompt) ────────────
BUSINESS_NAME: str = "QuantX Skin Salon"
BUSINESS_SERVICES: list[dict] = [
    {"name": "Hydrafacial", "name_ar": "هيدرافيشيل", "price_aed": 400},
    {"name": "Chemical Peel", "name_ar": "تقشير كيميائي", "price_aed": 350},
    {"name": "Laser Hair Removal", "name_ar": "إزالة الشعر بالليزر", "price_aed": 500},
    {"name": "Microneedling", "name_ar": "الوخز بالإبر الدقيقة", "price_aed": 600},
    {"name": "Deep Cleansing Facial", "name_ar": "تنظيف عميق للبشرة", "price_aed": 250},
]
BUSINESS_HOURS: str = "9 AM – 6 PM, Monday to Saturday"
BUSINESS_HOURS_AR: str = "٩ صباحاً – ٦ مساءً، الاثنين إلى السبت"

# ── Module 2-5: Clinic Operations ─────────────────────────────────────
CLINIC_MANAGER_PHONE: str = os.getenv("CLINIC_MANAGER_PHONE", "")
CLINIC_PHONE: str = os.getenv("CLINIC_PHONE", "")
CLINIC_LATITUDE: str = os.getenv("CLINIC_LATITUDE", "25.2048")
CLINIC_LONGITUDE: str = os.getenv("CLINIC_LONGITUDE", "55.2708")
CLINIC_ADDRESS: str = os.getenv("CLINIC_ADDRESS", "Dubai, UAE")

# ── Payment Simulation ───────────────────────────────────────────────
DEPOSIT_AMOUNT_AED: int = int(os.getenv("DEPOSIT_AMOUNT_AED", "50"))

# ── Premium Services (require deposit for confirmation) ──────────────
PREMIUM_SERVICES: list[str] = [
    s.strip()
    for s in os.getenv("PREMIUM_SERVICES", "Microneedling,Laser Hair Removal").split(",")
    if s.strip()
]

# ── Retention Campaign Intervals (service → days since completion) ───
RETENTION_INTERVALS: dict[str, int] = {
    "Laser Hair Removal": 28,
    "Deep Cleansing Facial": 30,
    "Hydrafacial": 30,
}

# ── Google Review (placeholder for prototype) ────────────────────────
GOOGLE_REVIEW_LINK: str = os.getenv(
    "GOOGLE_REVIEW_LINK", "https://g.page/quantx-skin-salon/review"
)
