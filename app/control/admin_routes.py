"""
Admin Control Plane API routes.
Tất cả cần dashboard auth + role ADMIN.

Endpoints:
  GET    /admin/bots
  POST   /admin/bots
  GET    /admin/bots/:id
  PUT    /admin/bots/:id
  DELETE /admin/bots/:id
  POST   /admin/bots/:id/activate
  POST   /admin/bots/:id/disable
  POST   /admin/bots/:id/extend-license
  POST   /admin/bots/:id/override-db-url
  POST   /admin/bots/:id/rotate-secret
  GET    /admin/bots/:id/heartbeats
  GET    /admin/bots/:id/audit-logs
  GET    /admin/dashboard
"""

from datetime import datetime
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, field_validator

from app.auth.dependencies import require_admin
from app.auth.models import DashboardUser
from app.db.session import SessionLocal
from app.control import bot_manager
from app.control.models import BotHeartbeatLog, BotAuditLog

router = APIRouter(prefix="/admin", tags=["admin"])


# ── Request Models ────────────────────────────────────────────

class CreateBotRequest(BaseModel):
    name: str
    slug: str
    database_url: str
    dashboard_username: str
    dashboard_password: str
    license_expires_at: Optional[str] = None
    description: str = ""
    notes: str = ""

    @field_validator("slug")
    @classmethod
    def slug_valid(cls, v):
        v = v.strip().lower()
        if not v or len(v) < 2:
            raise ValueError("slug must be at least 2 characters")
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("slug must be alphanumeric with - or _")
        return v

    @field_validator("dashboard_username")
    @classmethod
    def username_valid(cls, v):
        if not v or len(v.strip()) < 3:
            raise ValueError("username must be at least 3 characters")
        return v.strip()

    @field_validator("dashboard_password")
    @classmethod
    def password_valid(cls, v):
        if not v or len(v) < 6:
            raise ValueError("password must be at least 6 characters")
        return v


class UpdateBotRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None


class ExtendLicenseRequest(BaseModel):
    new_expires_at: str  # ISO format datetime


class OverrideDbUrlRequest(BaseModel):
    new_database_url: str


class ResetBotDashboardPasswordRequest(BaseModel):
    new_password: str
    dashboard_username: Optional[str] = None

    @field_validator("new_password")
    @classmethod
    def password_valid(cls, v):
        if not v or len(v) < 6:
            raise ValueError("password must be at least 6 characters")
        return v

    @field_validator("dashboard_username")
    @classmethod
    def username_valid(cls, v):
        if v is None or v == "":
            return v
        if len(v.strip()) < 3:
            raise ValueError("username must be at least 3 characters")
        return v.strip()


# ── Endpoints ─────────────────────────────────────────────────

@router.get("/dashboard")
async def admin_dashboard(admin: DashboardUser = Depends(require_admin)):
    """Tổng quan tất cả bots."""
    db = SessionLocal()
    try:
        return bot_manager.get_dashboard_summary(db)
    finally:
        db.close()


@router.get("/bots")
async def list_bots(admin: DashboardUser = Depends(require_admin)):
    """List tất cả bots."""
    db = SessionLocal()
    try:
        return bot_manager.list_bots(db)
    finally:
        db.close()


@router.post("/bots")
async def create_bot(
    req: CreateBotRequest,
    admin: DashboardUser = Depends(require_admin)
):
    """
    Tạo bot mới.
    Trả về bot_uuid + bot_secret (hiển thị 1 lần duy nhất).
    """
    db = SessionLocal()
    try:
        expires_at = None
        if req.license_expires_at:
            try:
                expires_at = datetime.fromisoformat(req.license_expires_at)
            except ValueError:
                raise HTTPException(400, "Invalid license_expires_at format")

        result = bot_manager.create_bot(
            db=db,
            name=req.name,
            slug=req.slug,
            database_url=req.database_url,
            license_expires_at=expires_at,
            dashboard_username=req.dashboard_username,
            dashboard_password=req.dashboard_password,
            admin_user_id=admin.id,
            description=req.description,
            notes=req.notes,
        )
        return result

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@router.get("/bots/{bot_id}")
async def get_bot(bot_id: int, admin: DashboardUser = Depends(require_admin)):
    """Get chi tiết 1 bot."""
    db = SessionLocal()
    try:
        result = bot_manager.get_bot(db, bot_id)
        if not result:
            raise HTTPException(404, "Bot not found")
        return result
    finally:
        db.close()


@router.put("/bots/{bot_id}")
async def update_bot(
    bot_id: int,
    req: UpdateBotRequest,
    admin: DashboardUser = Depends(require_admin)
):
    """Update bot info."""
    db = SessionLocal()
    try:
        return bot_manager.update_bot(
            db, bot_id, admin_user_id=admin.id,
            name=req.name, description=req.description, notes=req.notes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()


@router.delete("/bots/{bot_id}")
async def delete_bot(bot_id: int, admin: DashboardUser = Depends(require_admin)):
    """Delete bot từ registry."""
    db = SessionLocal()
    try:
        return bot_manager.delete_bot(db, bot_id, admin_user_id=admin.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()


@router.post("/bots/{bot_id}/activate")
async def activate_bot(bot_id: int, admin: DashboardUser = Depends(require_admin)):
    """Enable bot."""
    db = SessionLocal()
    try:
        return bot_manager.activate_bot(db, bot_id, admin_user_id=admin.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()


@router.post("/bots/{bot_id}/disable")
async def disable_bot(bot_id: int, admin: DashboardUser = Depends(require_admin)):
    """Disable bot."""
    db = SessionLocal()
    try:
        return bot_manager.disable_bot(db, bot_id, admin_user_id=admin.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()


@router.post("/bots/{bot_id}/extend-license")
async def extend_license(
    bot_id: int,
    req: ExtendLicenseRequest,
    admin: DashboardUser = Depends(require_admin)
):
    """Gia hạn license."""
    db = SessionLocal()
    try:
        try:
            expires_at = datetime.fromisoformat(req.new_expires_at)
        except ValueError:
            raise HTTPException(400, "Invalid datetime format")

        return bot_manager.extend_license(
            db, bot_id, expires_at, admin_user_id=admin.id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()


@router.post("/bots/{bot_id}/override-db-url")
async def override_db_url(
    bot_id: int,
    req: OverrideDbUrlRequest,
    admin: DashboardUser = Depends(require_admin)
):
    """Override DB URL (có hiệu lực sau lần restart bot)."""
    db = SessionLocal()
    try:
        return bot_manager.override_db_url(
            db, bot_id, req.new_database_url, admin_user_id=admin.id
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()


@router.post("/bots/{bot_id}/rotate-secret")
async def rotate_secret(bot_id: int, admin: DashboardUser = Depends(require_admin)):
    """Rotate bot secret. Trả secret mới 1 lần duy nhất."""
    db = SessionLocal()
    try:
        return bot_manager.rotate_secret(db, bot_id, admin_user_id=admin.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()


@router.post("/bots/{bot_id}/reset-dashboard-password")
async def reset_bot_dashboard_password(
    bot_id: int,
    req: ResetBotDashboardPasswordRequest,
    admin: DashboardUser = Depends(require_admin)
):
    """Reset/create bot dashboard user password inside bot DB."""
    db = SessionLocal()
    try:
        return bot_manager.reset_bot_dashboard_password(
            db=db,
            bot_id=bot_id,
            dashboard_username=req.dashboard_username,
            new_password=req.new_password,
            admin_user_id=admin.id,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        db.close()


@router.get("/bots/{bot_id}/heartbeats")
async def get_heartbeats(
    bot_id: int,
    limit: int = 100,
    admin: DashboardUser = Depends(require_admin)
):
    """Lịch sử heartbeat."""
    db = SessionLocal()
    try:
        logs = db.query(BotHeartbeatLog).filter(
            BotHeartbeatLog.bot_id == bot_id
        ).order_by(
            BotHeartbeatLog.received_at.desc()
        ).limit(limit).all()

        return [
            {
                "id": log.id,
                "received_at": str(log.received_at),
                "ip_address": log.ip_address,
                "app_version": log.app_version,
                "uptime_seconds": log.uptime_seconds,
                "open_trades": log.open_trades,
                "pending_count": log.pending_count,
                "trading_mode": log.trading_mode,
                "status_returned": log.status_returned,
            }
            for log in logs
        ]
    finally:
        db.close()


@router.get("/bots/{bot_id}/audit-logs")
async def get_audit_logs(
    bot_id: int,
    limit: int = 100,
    admin: DashboardUser = Depends(require_admin)
):
    """Lịch sử thao tác admin."""
    db = SessionLocal()
    try:
        logs = db.query(BotAuditLog).filter(
            BotAuditLog.bot_id == bot_id
        ).order_by(
            BotAuditLog.created_at.desc()
        ).limit(limit).all()

        return [
            {
                "id": log.id,
                "action": log.action,
                "details": log.details,
                "admin_user_id": log.admin_user_id,
                "created_at": str(log.created_at),
            }
            for log in logs
        ]
    finally:
        db.close()