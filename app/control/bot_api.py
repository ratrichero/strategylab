"""
Bot machine-to-admin API endpoints.
Auth bằng BOT_ID + BOT_SECRET (không phải dashboard login).

Endpoints:
  POST /bot/auth/activate   — bot startup, nhận DB URL + license
  POST /bot/heartbeat       — periodic check-in
  GET  /bot/status          — check license status
"""

import json
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional

from app.db.session import SessionLocal
from app.control.models import BotRegistry, BotHeartbeatLog
from app.control.bot_auth import verify_bot_credentials
from app.core.encryption import encrypt_for_transport

router = APIRouter(prefix="/bot", tags=["bot-machine"])


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _db_now() -> datetime:
    return _utc_now().replace(tzinfo=None)


def _as_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_expired(dt: Optional[datetime]) -> bool:
    expires_at = _as_utc(dt)
    return bool(expires_at and _utc_now() > expires_at)


def _parse_bot_uuid(bot_id: str):
    try:
        return uuid.UUID(str(bot_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid bot id")


# ── Request Models ────────────────────────────────────────────

class ActivateRequest(BaseModel):
    bot_id: str
    bot_secret: str
    app_version: Optional[str] = None


class HeartbeatRequest(BaseModel):
    bot_id: str
    bot_secret: str
    app_version: Optional[str] = None
    uptime_seconds: Optional[int] = None
    trading_mode: Optional[str] = None
    open_trades: Optional[int] = None
    pending_count: Optional[int] = None


class StatusRequest(BaseModel):
    bot_id: str
    bot_secret: str


# ── Endpoints ─────────────────────────────────────────────────

@router.post("/auth/activate")
async def bot_activate(req: ActivateRequest, request: Request):
    """
    Bot startup: verify credentials, trả DB URL + license info.
    DB URL được encrypt cho transport bằng bot_secret.
    """
    bot = verify_bot_credentials(req.bot_id, req.bot_secret)

    db = SessionLocal()
    try:
        # Reload bot trong session này
        bot = db.query(BotRegistry).filter(
            BotRegistry.bot_uuid == _parse_bot_uuid(req.bot_id)
        ).first()

        if not bot:
            raise HTTPException(status_code=401, detail="Bot not found")

        # Check status
        allowed = bot.status == "active"

        # Check license expiry
        license_expired = False
        if _is_expired(bot.license_expires_at):
            license_expired = True
            if bot.status == "active":
                bot.status = "expired"
                db.commit()

        # Decrypt DB URL + re-encrypt cho transport
        from app.core.encryption import decrypt_at_rest
        plain_db_url = decrypt_at_rest(bot.database_url_encrypted)
        transport_db_url = encrypt_for_transport(plain_db_url, req.bot_secret)

        # Admin endpoints override
        admin_endpoints = None
        if bot.admin_endpoints_override:
            try:
                admin_endpoints = json.loads(bot.admin_endpoints_override)
            except (json.JSONDecodeError, TypeError):
                admin_endpoints = None

        # Update last seen
        bot.last_seen_ip = request.client.host if request.client else None
        bot.last_seen_version = req.app_version
        bot.last_heartbeat_at = _db_now()
        bot.is_online = True
        db.commit()

        status = bot.status
        if license_expired and status == "active":
            status = "expired"

        return {
            "allowed": allowed and not license_expired,
            "status": status,
            "database_url": transport_db_url,
            "license_expires_at": str(bot.license_expires_at) if bot.license_expires_at else None,
            "admin_endpoints": admin_endpoints,
            "heartbeat_interval_sec": bot.heartbeat_interval_sec or 60,
        }

    finally:
        db.close()


@router.post("/heartbeat")
async def bot_heartbeat(req: HeartbeatRequest, request: Request):
    """
    Periodic heartbeat từ bot runtime.
    Nhận status + license + endpoints mới.
    """
    bot = verify_bot_credentials(req.bot_id, req.bot_secret)

    db = SessionLocal()
    try:
        bot = db.query(BotRegistry).filter(
            BotRegistry.bot_uuid == _parse_bot_uuid(req.bot_id)
        ).first()

        if not bot:
            raise HTTPException(status_code=401, detail="Bot not found")

        # Check license expiry
        if _is_expired(bot.license_expires_at):
            if bot.status == "active":
                bot.status = "expired"

        # Check db_url changed
        db_url_changed = False
        if bot.db_url_updated_at and bot.last_heartbeat_at:
            if _as_utc(bot.db_url_updated_at) > _as_utc(bot.last_heartbeat_at):
                db_url_changed = True

        # Update heartbeat
        client_ip = request.client.host if request.client else None
        bot.last_heartbeat_at = _db_now()
        bot.last_seen_ip = client_ip
        bot.last_seen_version = req.app_version
        bot.is_online = True

        # Log heartbeat
        log = BotHeartbeatLog(
            bot_id=bot.id,
            ip_address=client_ip,
            app_version=req.app_version,
            uptime_seconds=req.uptime_seconds,
            open_trades=req.open_trades,
            pending_count=req.pending_count,
            trading_mode=req.trading_mode,
            status_returned=bot.status,
        )
        db.add(log)
        db.commit()

        # Admin endpoints override
        admin_endpoints = None
        if bot.admin_endpoints_override:
            try:
                admin_endpoints = json.loads(bot.admin_endpoints_override)
            except (json.JSONDecodeError, TypeError):
                admin_endpoints = None

        return {
            "status": bot.status,
            "license_expires_at": str(bot.license_expires_at) if bot.license_expires_at else None,
            "admin_endpoints": admin_endpoints,
            "db_url_changed": db_url_changed,
        }

    finally:
        db.close()


@router.get("/status")
async def bot_status(bot_id: str, bot_secret: str):
    """Quick status check."""
    bot = verify_bot_credentials(bot_id, bot_secret)

    db = SessionLocal()
    try:
        bot = db.query(BotRegistry).filter(
            BotRegistry.bot_uuid == _parse_bot_uuid(bot_id)
        ).first()

        if not bot:
            raise HTTPException(status_code=401, detail="Bot not found")

        return {
            "status": bot.status,
            "license_expires_at": str(bot.license_expires_at) if bot.license_expires_at else None,
            "is_online": bot.is_online,
        }
    finally:
        db.close()
