"""
Bot machine authentication.
Dùng cho bot runtime gọi admin API:
  - /bot/auth/activate
  - /bot/heartbeat
  - /bot/status

Auth bằng BOT_ID + BOT_SECRET (không phải dashboard login).
"""

import uuid

from fastapi import Request, HTTPException

from app.db.session import SessionLocal
from app.control.models import BotRegistry, BotCredential
from app.auth.password import verify_secret


def verify_bot_credentials(bot_id: str, bot_secret: str) -> BotRegistry:
    """
    Verify bot_id + bot_secret.

    Args:
        bot_id: bot_uuid string
        bot_secret: plain secret

    Returns:
        BotRegistry object nếu valid

    Raises:
        HTTPException 401 nếu invalid
    """
    try:
        bot_uuid = uuid.UUID(str(bot_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid bot id")

    db = SessionLocal()
    try:
        bot = db.query(BotRegistry).filter(
            BotRegistry.bot_uuid == bot_uuid
        ).first()

        if not bot:
            raise HTTPException(status_code=401, detail="Bot not found")

        # Tìm active credential
        credential = db.query(BotCredential).filter(
            BotCredential.bot_id == bot.id,
            BotCredential.is_active == True
        ).first()

        if not credential:
            raise HTTPException(status_code=401, detail="No active credential")

        if not verify_secret(bot_secret, credential.secret_hash):
            raise HTTPException(status_code=401, detail="Invalid bot secret")

        return bot

    finally:
        db.close()


def get_bot_from_request(request: Request) -> BotRegistry:
    """
    FastAPI dependency: extract + verify bot credentials từ request.
    Expect JSON body hoặc query params: bot_id, bot_secret.
    """
    # Sẽ được gọi trong route handler, không phải dependency inject
    # vì body cần await
    pass
