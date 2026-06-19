"""
Core Config
===========
- BINANCE_BASE: constant cho binance_service.py
- Getter functions: dùng cho runtime override khi cần
- Backward-compatible constants: chỉ đọc env thuần để tránh circular import
"""

import os
import app.core.env_bootstrap

# ── Constant giữ nguyên ──────────────────────────────────────
BINANCE_BASE = os.getenv("BINANCE_BASE", "https://fapi.binance.com")

# DATABASE_URL KHÔNG xử lý ở đây
# DATABASE_URL chỉ nên đọc trong app/db/session.py


# ── Getter functions ─────────────────────────────────────────

def get_telegram_token() -> str:
    """
    Runtime getter:
    Có thể dùng DB override qua config_service nếu cần.
    Không nên gọi ở import-time của module nền tảng.
    """
    from app.services.config_service import get_connection_value
    return (
        get_connection_value("TELEGRAM_BOT_TOKEN", "")
        or os.getenv("TELEGRAM_TOKEN", "")
    )


def get_telegram_chat_id() -> str:
    """
    Hiện giữ env-only như cũ.
    Nếu sau này cần override qua DB thì nâng cấp sau.
    """
    return os.getenv("TELEGRAM_CHAT_ID", "")


def get_groq_api_key() -> str:
    from app.services.config_service import get_connection_value
    return get_connection_value("GROQ_API_KEY", "")


def get_gemini_api_key() -> str:
    from app.services.config_service import get_connection_value
    return get_connection_value("GEMINI_API_KEY", "")


# ── Backward-compatible constants ────────────────────────────
# QUAN TRỌNG:
# - Chỉ đọc ENV thuần
# - KHÔNG gọi get_connection_value / DB ở import-time
# - Mục tiêu: tránh circular import cho các module cũ

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
GROQ_API_KEY     = os.getenv("GROQ_API_KEY", "")
GEMINI_API_KEY   = os.getenv("GEMINI_API_KEY", "")