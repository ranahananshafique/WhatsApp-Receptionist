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
BUSINESS_NAME: str = "Apex Clinic"
BUSINESS_SERVICES: list[dict] = [
    {"name": "Teeth Whitening", "name_ar": "تبييض الأسنان", "price_aed": 500},
    {"name": "Dental Clean", "name_ar": "تنظيف الأسنان", "price_aed": 300},
]
BUSINESS_HOURS: str = "9 AM – 6 PM, Monday to Saturday"
BUSINESS_HOURS_AR: str = "٩ صباحاً – ٦ مساءً، الاثنين إلى السبت"
