"""
Bot lifecycle management.
Tất cả business logic CRUD + override + license cho bots.
"""

import json
import secrets
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.orm import Session

from app.control.models import (
    BotRegistry, BotCredential, BotAuditLog
)
from app.core.encryption import encrypt_at_rest, decrypt_at_rest
from app.auth.password import hash_password, hash_secret
from app.control.bot_db_init import validate_db_connection, init_bot_database


def generate_bot_secret() -> str:
    """Generate secure random bot secret."""
    return secrets.token_urlsafe(32)


def normalize_db_datetime(dt: Optional[datetime]) -> Optional[datetime]:
    """Store UTC-naive values because control-plane columns are DateTime without timezone."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


# ============================================================
# CREATE
# ============================================================

def create_bot(
    db: Session,
    name: str,
    slug: str,
    database_url: str,
    license_expires_at: Optional[datetime],
    dashboard_username: str,
    dashboard_password: str,
    admin_user_id: Optional[int] = None,
    description: str = "",
    notes: str = "",
) -> dict:
    """
    Tạo bot mới.

    Steps:
      1. Validate slug unique
      2. Validate DB connection
      3. Encrypt DB URL
      4. Generate bot_secret
      5. Create bot_registry record
      6. Create bot_credentials record
      7. Init bot database (tables + dashboard user + default config)
      8. Ghi audit log

    Returns:
        { bot_uuid, bot_secret, bot_id, message }
    """
    # ── Validate slug unique ────────────────────────────────
    existing = db.query(BotRegistry).filter(
        BotRegistry.slug == slug
    ).first()
    if existing:
        raise ValueError(f"Bot slug '{slug}' already exists")

    # ── Validate DB connection ──────────────────────────────
    if not validate_db_connection(database_url):
        raise ValueError(f"Cannot connect to bot database: {database_url[:30]}...")

    # ── Encrypt DB URL ──────────────────────────────────────
    db_url_encrypted = encrypt_at_rest(database_url)

    # ── Generate secret ─────────────────────────────────────
    bot_secret = generate_bot_secret()

    # ── Create bot registry ─────────────────────────────────
    bot = BotRegistry(
        name=name,
        slug=slug,
        description=description,
        database_url_encrypted=db_url_encrypted,
        status="active",
        license_started_at=normalize_db_datetime(datetime.now(timezone.utc)),
        license_expires_at=normalize_db_datetime(license_expires_at),
        dashboard_username=dashboard_username,
        notes=notes,
    )
    db.add(bot)
    db.flush()  # get bot.id

    # ── Create credential ───────────────────────────────────
    credential = BotCredential(
        bot_id=bot.id,
        secret_hash=hash_secret(bot_secret),
        is_active=True,
    )
    db.add(credential)

    # ── Init bot database ───────────────────────────────────
    print(f"\n🔧 Initializing bot database for '{slug}'...")
    init_result = init_bot_database(
        database_url=database_url,
        dashboard_username=dashboard_username,
        dashboard_password=dashboard_password,
    )

    if not init_result["success"]:
        db.rollback()
        raise ValueError(f"Bot DB init failed: {init_result['message']}")

    # ── Audit log ───────────────────────────────────────────
    audit = BotAuditLog(
        admin_user_id=admin_user_id,
        bot_id=bot.id,
        action="create_bot",
        details={
            "slug": slug,
            "name": name,
            "dashboard_username": dashboard_username,
            "tables_created": init_result.get("tables_created", []),
        }
    )
    db.add(audit)

    db.commit()
    db.refresh(bot)

    return {
        "bot_uuid": str(bot.bot_uuid),
        "bot_secret": bot_secret,
        "bot_id": bot.id,
        "message": "Bot created successfully",
    }


# ============================================================
# READ
# ============================================================

def list_bots(db: Session) -> List[dict]:
    """List tất cả bots (không trả DB URL)."""
    bots = db.query(BotRegistry).order_by(BotRegistry.created_at.desc()).all()
    return [_bot_to_dict(b) for b in bots]


def get_bot(db: Session, bot_id: int) -> Optional[dict]:
    """Get chi tiết 1 bot."""
    bot = db.query(BotRegistry).filter(BotRegistry.id == bot_id).first()
    if not bot:
        return None
    return _bot_to_dict(bot, include_detail=True)


def get_bot_by_uuid(db: Session, bot_uuid: str) -> Optional[BotRegistry]:
    """Get bot by UUID."""
    return db.query(BotRegistry).filter(
        BotRegistry.bot_uuid == bot_uuid
    ).first()


# ============================================================
# UPDATE
# ============================================================

def update_bot(
    db: Session,
    bot_id: int,
    admin_user_id: Optional[int] = None,
    **kwargs
) -> dict:
    """Update bot info (name, description, notes)."""
    bot = db.query(BotRegistry).filter(BotRegistry.id == bot_id).first()
    if not bot:
        raise ValueError("Bot not found")

    allowed_fields = {"name", "description", "notes"}
    updated = {}

    for field, value in kwargs.items():
        if field in allowed_fields and value is not None:
            setattr(bot, field, value)
            updated[field] = value

    if updated:
        audit = BotAuditLog(
            admin_user_id=admin_user_id,
            bot_id=bot.id,
            action="update_bot",
            details=updated,
        )
        db.add(audit)
        db.commit()

    return _bot_to_dict(bot)


# ============================================================
# STATUS CHANGES
# ============================================================

def activate_bot(db: Session, bot_id: int, admin_user_id: Optional[int] = None) -> dict:
    """Set bot status → active."""
    return _change_status(db, bot_id, "active", "activate_bot", admin_user_id)


def disable_bot(db: Session, bot_id: int, admin_user_id: Optional[int] = None) -> dict:
    """Set bot status → disabled."""
    return _change_status(db, bot_id, "disabled", "disable_bot", admin_user_id)


def extend_license(
    db: Session,
    bot_id: int,
    new_expires_at: datetime,
    admin_user_id: Optional[int] = None,
) -> dict:
    """Gia hạn license."""
    bot = db.query(BotRegistry).filter(BotRegistry.id == bot_id).first()
    if not bot:
        raise ValueError("Bot not found")

    old_expires = str(bot.license_expires_at) if bot.license_expires_at else None
    new_expires_at = normalize_db_datetime(new_expires_at)
    bot.license_expires_at = new_expires_at

    # Nếu đang expired mà gia hạn → auto activate
    if bot.status == "expired":
        bot.status = "active"

    audit = BotAuditLog(
        admin_user_id=admin_user_id,
        bot_id=bot.id,
        action="extend_license",
        details={
            "old_expires_at": old_expires,
            "new_expires_at": str(new_expires_at),
        }
    )
    db.add(audit)
    db.commit()

    return _bot_to_dict(bot)


# ============================================================
# OVERRIDE DB URL
# ============================================================

def override_db_url(
    db: Session,
    bot_id: int,
    new_database_url: str,
    admin_user_id: Optional[int] = None,
) -> dict:
    """
    Override DB URL cho bot.
    Validate connection trước khi lưu.
    Bot sẽ nhận DB URL mới ở lần restart sau.
    """
    bot = db.query(BotRegistry).filter(BotRegistry.id == bot_id).first()
    if not bot:
        raise ValueError("Bot not found")

    if not validate_db_connection(new_database_url):
        raise ValueError("Cannot connect to new database URL")

    bot.database_url_encrypted = encrypt_at_rest(new_database_url)
    bot.db_url_updated_at = normalize_db_datetime(datetime.now(timezone.utc))

    audit = BotAuditLog(
        admin_user_id=admin_user_id,
        bot_id=bot.id,
        action="override_db_url",
        details={"db_url_updated_at": str(bot.db_url_updated_at)},
    )
    db.add(audit)
    db.commit()

    return _bot_to_dict(bot)


# ============================================================
# ROTATE SECRET
# ============================================================

def rotate_secret(
    db: Session,
    bot_id: int,
    admin_user_id: Optional[int] = None,
) -> dict:
    """
    Rotate bot secret.
    Deactivate old credential, create new one.
    Returns new plain secret (hiển thị 1 lần).
    """
    bot = db.query(BotRegistry).filter(BotRegistry.id == bot_id).first()
    if not bot:
        raise ValueError("Bot not found")

    # Deactivate old credentials
    db.query(BotCredential).filter(
        BotCredential.bot_id == bot.id,
        BotCredential.is_active == True
    ).update({"is_active": False, "rotated_at": normalize_db_datetime(datetime.now(timezone.utc))})

    # Create new
    new_secret = generate_bot_secret()
    credential = BotCredential(
        bot_id=bot.id,
        secret_hash=hash_secret(new_secret),
        is_active=True,
    )
    db.add(credential)

    audit = BotAuditLog(
        admin_user_id=admin_user_id,
        bot_id=bot.id,
        action="rotate_secret",
        details={},
    )
    db.add(audit)
    db.commit()

    return {
        "bot_uuid": str(bot.bot_uuid),
        "new_bot_secret": new_secret,
        "message": "Secret rotated. Save the new secret — it won't be shown again.",
    }


# ============================================================
# DELETE
# ============================================================

def delete_bot(db: Session, bot_id: int, admin_user_id: Optional[int] = None) -> dict:
    """Delete bot từ registry. KHÔNG xóa bot DB."""
    bot = db.query(BotRegistry).filter(BotRegistry.id == bot_id).first()
    if not bot:
        raise ValueError("Bot not found")

    slug = bot.slug
    name = bot.name

    audit = BotAuditLog(
        admin_user_id=admin_user_id,
        bot_id=bot.id,
        action="delete_bot",
        details={"slug": slug, "name": name},
    )
    db.add(audit)

    db.delete(bot)
    db.commit()

    return {"message": f"Bot '{slug}' removed from registry. Bot database NOT deleted."}


# ============================================================
# DASHBOARD
# ============================================================

def get_dashboard_summary(db: Session) -> dict:
    """Tổng quan tất cả bots cho admin dashboard."""
    bots = db.query(BotRegistry).all()

    total = len(bots)
    active = sum(1 for b in bots if b.status == "active")
    disabled = sum(1 for b in bots if b.status == "disabled")
    expired = sum(1 for b in bots if b.status == "expired")
    online = sum(1 for b in bots if b.is_online)

    return {
        "total_bots": total,
        "active_bots": active,
        "disabled_bots": disabled,
        "expired_bots": expired,
        "online_bots": online,
        "bots": [_bot_to_dict(b) for b in bots],
    }


# ============================================================
# HELPERS
# ============================================================

def _change_status(db, bot_id, new_status, action, admin_user_id):
    bot = db.query(BotRegistry).filter(BotRegistry.id == bot_id).first()
    if not bot:
        raise ValueError("Bot not found")

    old_status = bot.status
    bot.status = new_status

    audit = BotAuditLog(
        admin_user_id=admin_user_id,
        bot_id=bot.id,
        action=action,
        details={"old_status": old_status, "new_status": new_status},
    )
    db.add(audit)
    db.commit()

    return _bot_to_dict(bot)


def _bot_to_dict(bot: BotRegistry, include_detail: bool = False) -> dict:
    d = {
        "id": bot.id,
        "bot_uuid": str(bot.bot_uuid),
        "slug": bot.slug,
        "name": bot.name,
        "status": bot.status,
        "license_started_at": str(bot.license_started_at) if bot.license_started_at else None,
        "license_expires_at": str(bot.license_expires_at) if bot.license_expires_at else None,
        "is_online": bot.is_online,
        "last_heartbeat_at": str(bot.last_heartbeat_at) if bot.last_heartbeat_at else None,
        "last_seen_version": bot.last_seen_version,
        "dashboard_username": bot.dashboard_username,
        "created_at": str(bot.created_at),
    }

    if include_detail:
        d["description"] = bot.description
        d["notes"] = bot.notes
        d["heartbeat_interval_sec"] = bot.heartbeat_interval_sec
        d["last_seen_ip"] = bot.last_seen_ip
        d["db_url_updated_at"] = str(bot.db_url_updated_at) if bot.db_url_updated_at else None

    return d