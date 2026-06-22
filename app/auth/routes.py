"""
Auth API endpoints.
Dùng chung cho cả ADMIN và BOT dashboard.

Endpoints:
  GET  /auth/setup-status   — check cần setup lần đầu không
  POST /auth/setup          — tạo user đầu tiên (chỉ khi DB trống)
  POST /auth/login          — login, set cookie
  POST /auth/logout         — clear cookie
  GET  /auth/me             — lấy current user info
"""

from datetime import datetime, timezone
import os
from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from app.auth.models import DashboardUser
from app.auth.password import hash_password, verify_password
from app.auth.jwt_utils import create_access_token, get_cookie_name
from app.auth.dependencies import get_current_user
from app.db.session import SessionLocal
from app.core.app_role import get_app_role, ROLE_ADMIN

router = APIRouter(prefix="/auth", tags=["auth"])


# ── Request/Response Models ───────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str

    @field_validator("username", "password")
    @classmethod
    def not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError("must not be empty")
        return v.strip()


class SetupRequest(BaseModel):
    username: str
    password: str
    confirm_password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v):
        if not v or not v.strip():
            raise ValueError("username must not be empty")
        v = v.strip()
        if len(v) < 3:
            raise ValueError("username must be at least 3 characters")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v):
        if not v or len(v) < 6:
            raise ValueError("password must be at least 6 characters")
        return v


# ── Cookie helpers ────────────────────────────────────────────

def _set_auth_cookie(response: JSONResponse, token: str) -> JSONResponse:
    """Set JWT vào HttpOnly cookie."""
    secure_cookie = os.environ.get("COOKIE_SECURE", "false").strip().lower() == "true"
    response.set_cookie(
        key=get_cookie_name(),
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # True nếu dùng HTTPS
        max_age=60 * 60 * 24,  # 24h
        path="/",
    )
    return response


def _clear_auth_cookie(response: JSONResponse) -> JSONResponse:
    """Clear auth cookie."""
    response.delete_cookie(
        key=get_cookie_name(),
        path="/",
    )
    return response


# ── Endpoints ─────────────────────────────────────────────────

@router.get("/setup-status")
async def setup_status():
    """
    Check xem dashboard_users có user nào chưa.
    Nếu chưa có → cần first-visit setup.
    """
    db = SessionLocal()
    try:
        count = db.query(DashboardUser).count()
        return {"needs_setup": count == 0}
    finally:
        db.close()


@router.post("/setup")
async def setup(req: SetupRequest):
    """
    First-visit setup: tạo user đầu tiên.
    CHỈ hoạt động khi dashboard_users TRỐNG.
    Sau khi có user đầu tiên → endpoint này trả 403.
    """
    if req.password != req.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")

    db = SessionLocal()
    try:
        count = db.query(DashboardUser).count()
        if count > 0:
            raise HTTPException(
                status_code=403,
                detail="Setup already completed. Use /auth/login instead."
            )

        # Role dựa theo APP_ROLE
        role = "ADMIN" if get_app_role() == ROLE_ADMIN else "USER"

        user = DashboardUser(
            username=req.username,
            password_hash=hash_password(req.password),
            role=role,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)

        # Auto login
        token = create_access_token(user.id, user.username, user.role)

        response = JSONResponse(content={
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
            },
            "message": "Account created successfully",
        })
        return _set_auth_cookie(response, token)

    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/login")
async def login(req: LoginRequest):
    """
    Login bằng username + password.
    Set JWT vào HttpOnly cookie.
    """
    db = SessionLocal()
    try:
        user = db.query(DashboardUser).filter(
            DashboardUser.username == req.username,
            DashboardUser.is_active == True
        ).first()

        if not user or not verify_password(req.password, user.password_hash):
            raise HTTPException(status_code=401, detail="Invalid username or password")

        # Update last login
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()

        token = create_access_token(user.id, user.username, user.role)

        response = JSONResponse(content={
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
            }
        })
        return _set_auth_cookie(response, token)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@router.post("/logout")
async def logout():
    """Clear auth cookie."""
    response = JSONResponse(content={"ok": True})
    return _clear_auth_cookie(response)


@router.get("/me")
async def me(current_user: DashboardUser = Depends(get_current_user)):
    """Lấy thông tin user đang login."""
    return {
        "user": {
            "id": current_user.id,
            "username": current_user.username,
            "role": current_user.role,
            "is_active": current_user.is_active,
        },
        "app_role": get_app_role(),
    }