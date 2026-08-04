from __future__ import annotations

import os
from dotenv import load_dotenv

load_dotenv()

# DataCrazy API
DATACRAZY_API_TOKEN = os.getenv("DATACRAZY_API_TOKEN", "")
DATACRAZY_BASE_URL = os.getenv("DATACRAZY_BASE_URL", "https://api.g1.datacrazy.io")
DATACRAZY_INSTANCE_ID = os.getenv("DATACRAZY_INSTANCE_ID", "")

# LLM — OmniRoute
OMNIROUTE_API_KEY = os.getenv("OMNIROUTE_API_KEY", "")
OMNIROUTE_MODEL_ID = os.getenv("OMNIROUTE_MODEL_ID", "xiaomi-mimo/mimo-v2.5-pro")
OMNIROUTE_BASE_URL = os.getenv("OMNIROUTE_BASE_URL", "<OMNIROUTE_BASE_URL>")
# Alias for SDR-compatible code paths
OMNIROUTE_ENDPOINT = os.getenv("OMNIROUTE_ENDPOINT", OMNIROUTE_BASE_URL)

# Media: image/sticker analysis — MUST be the regular (multimodal) model, NOT pro
OMNIROUTE_MEDIA_MODEL_ID = os.getenv("OMNIROUTE_MEDIA_MODEL_ID", "mimo/mimo-v2.5")
# Media: vision fallback cascade
OMNIROUTE_VISION_FALLBACK_MODEL = os.getenv("OMNIROUTE_VISION_FALLBACK_MODEL", "gweb/gemini-2.5-flash")
# Audio transcription — Deepgram Nova-3 via OmniRoute
OMNIROUTE_AUDIO_MODEL_ID = os.getenv("OMNIROUTE_AUDIO_MODEL_ID", "deepgram/nova-3")

# Session storage
SESSION_DB_PATH = os.getenv("SESSION_DB_PATH", "tmp/vanessa.db")

# Comercial
PAYMENT_LINK = os.getenv("PAYMENT_LINK", "")
NURTURE_CONTENT_LINK = os.getenv("NURTURE_CONTENT_LINK", "")

# Webhook de confirmação de pagamento
PAYMENT_WEBHOOK_SECRET = os.getenv("PAYMENT_WEBHOOK_SECRET", "")


def validate_config() -> None:
    required = {
        "DATACRAZY_API_TOKEN": DATACRAZY_API_TOKEN,
        "DATACRAZY_INSTANCE_ID": DATACRAZY_INSTANCE_ID,
        "OMNIROUTE_API_KEY": OMNIROUTE_API_KEY,
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required env vars: {', '.join(missing)}")
