"""
Dynamic DB session cho BOT mode.
Admin mode vẫn dùng session.py hiện tại, không đổi.

Cho phép set engine runtime (sau khi bot nhận DB URL từ admin).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from typing import Optional


_bot_engine = None
_BotSessionLocal = None


def create_bot_engine(database_url: str, **kwargs):
    """
    Tạo engine cho bot DB.
    Gọi 1 lần khi bot startup thành công.
    """
    global _bot_engine, _BotSessionLocal

    _bot_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        **kwargs
    )
    _BotSessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=_bot_engine
    )

    return _bot_engine


def get_bot_session():
    """
    Lấy session cho bot DB.
    Raise nếu chưa init.
    """
    if _BotSessionLocal is None:
        raise RuntimeError(
            "Bot DB not initialized. "
            "Call create_bot_engine() first."
        )
    return _BotSessionLocal()


def get_bot_engine():
    """Lấy engine cho bot DB."""
    return _bot_engine


def is_bot_db_ready() -> bool:
    """Check bot DB đã init chưa."""
    return _bot_engine is not None