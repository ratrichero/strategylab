"""
SQLAlchemy models cho Control Plane.
Các bảng này chỉ tồn tại trong Admin DB.

Tables:
  - bot_registry:        quản lý bot + DB URL encrypted
  - bot_credentials:     bot secret hash (rotatable)
  - bot_heartbeat_logs:  heartbeat history
  - bot_audit_logs:      admin action history

Note:
  - AdminUser đã được thay bằng DashboardUser (app/auth/models.py)
  - BotAuditLog.admin_user_id FK sang dashboard_users.id
"""

from sqlalchemy import (
    Column, Integer, String, Text, Boolean, DateTime,
    ForeignKey, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid

from app.db.session import Base


class BotRegistry(Base):
    __tablename__ = "bot_registry"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_uuid = Column(
        UUID(as_uuid=True), unique=True, nullable=False,
        default=uuid.uuid4
    )
    slug = Column(String(50), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    description = Column(Text, nullable=True)

    # DB URL (encrypted at rest bằng ADMIN_MASTER_KEY)
    database_url_encrypted = Column(Text, nullable=False)
    db_url_updated_at = Column(DateTime, nullable=True)

    # Status: active, disabled, expired
    status = Column(String(20), default="active")

    # License
    license_started_at = Column(DateTime, nullable=True)
    license_expires_at = Column(DateTime, nullable=True)

    # Heartbeat
    heartbeat_interval_sec = Column(Integer, default=60)
    last_heartbeat_at = Column(DateTime, nullable=True)
    last_seen_ip = Column(String(45), nullable=True)
    last_seen_version = Column(String(20), nullable=True)
    is_online = Column(Boolean, default=False)

    # Admin endpoints override (gửi cho bot khi sync)
    # Lưu dạng JSON text thay vì ARRAY để tương thích tốt hơn
    admin_endpoints_override = Column(Text, nullable=True)  # JSON array string

    # Bot dashboard credentials (username cho bot dashboard login)
    # Password hash lưu trong bot DB (dashboard_users table)
    dashboard_username = Column(String(100), nullable=True)

    # Metadata
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


# Indexes cho bot_registry
Index("idx_bot_registry_status", BotRegistry.status)
Index("idx_bot_registry_uuid", BotRegistry.bot_uuid)


class BotCredential(Base):
    __tablename__ = "bot_credentials"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(
        Integer,
        ForeignKey("bot_registry.id", ondelete="CASCADE"),
        nullable=False
    )
    secret_hash = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, server_default=func.now())
    rotated_at = Column(DateTime, nullable=True)


class BotHeartbeatLog(Base):
    __tablename__ = "bot_heartbeat_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    bot_id = Column(
        Integer,
        ForeignKey("bot_registry.id", ondelete="CASCADE"),
        nullable=False
    )
    received_at = Column(DateTime, server_default=func.now())
    ip_address = Column(String(45), nullable=True)
    app_version = Column(String(20), nullable=True)
    uptime_seconds = Column(Integer, nullable=True)
    open_trades = Column(Integer, nullable=True)
    pending_count = Column(Integer, nullable=True)
    trading_mode = Column(String(20), nullable=True)
    status_returned = Column(String(20), nullable=True)
    extra = Column(JSONB, nullable=True)


# Indexes cho heartbeat_logs
Index("idx_heartbeat_bot_id", BotHeartbeatLog.bot_id)
Index("idx_heartbeat_time", BotHeartbeatLog.received_at)


class BotAuditLog(Base):
    __tablename__ = "bot_audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    # ← CHANGED: FK trỏ sang dashboard_users thay vì admin_users
    admin_user_id = Column(
        Integer,
        ForeignKey("dashboard_users.id"),
        nullable=True
    )
    bot_id = Column(
        Integer,
        ForeignKey("bot_registry.id"),
        nullable=True
    )
    action = Column(String(50), nullable=False)
    # Possible actions:
    #   create_bot, disable_bot, activate_bot,
    #   extend_license, override_db_url,
    #   rotate_secret, delete_bot,
    #   emergency_access
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(45), nullable=True)
    created_at = Column(DateTime, server_default=func.now())


# Indexes cho audit_logs
Index("idx_audit_bot_id", BotAuditLog.bot_id)