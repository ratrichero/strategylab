from dotenv import load_dotenv

load_dotenv()

"""
Core Config
===========
- BINANCE_BASE: constant cho binance_service.py
- Getter functions: dùng cho runtime override
- Backward-compatible constants: để code cũ không vỡ
"""

import os

# ── Constant giữ nguyên ──────────────────────────────────────
BINANCE_BASE = os.getenv("BINANCE_BASE", "https://fapi.binance.com")

# DATABASE_URL KHÔNG xử lý ở đây
# DATABASE_URL chỉ nên đọc trong app/db/session.py


# ── Getter functions ─────────────────────────────────────────

def get_telegram_token() -> str:
    from app.services.config_service import get_connection_value
    return (
        get_connection_value("TELEGRAM_BOT_TOKEN", "")
        or os.getenv("TELEGRAM_TOKEN", "")
    )


def get_telegram_chat_id() -> str:
    # Chat ID hiện chưa override qua DB, cứ giữ env
    return os.getenv("TELEGRAM_CHAT_ID", "")


def get_groq_api_key() -> str:
    from app.services.config_service import get_connection_value
    return get_connection_value("GROQ_API_KEY", "")


def get_gemini_api_key() -> str:
    from app.services.config_service import get_connection_value
    return get_connection_value("GEMINI_API_KEY", "")


# ── Backward-compatible constants ────────────────────────────
# Để các file cũ import kiểu:
#   from app.core.config import TELEGRAM_TOKEN, TELEGRAM_CHAT_ID
# vẫn không bị vỡ

TELEGRAM_TOKEN   = get_telegram_token()
TELEGRAM_CHAT_ID = get_telegram_chat_id()
GROQ_API_KEY     = get_groq_api_key()
GEMINI_API_KEY   = get_gemini_api_key()