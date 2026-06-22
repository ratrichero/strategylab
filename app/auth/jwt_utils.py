"""
JWT utilities cho dashboard auth.
Token được set vào HttpOnly cookie, không gửi qua header.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt

# ── Config ────────────────────────────────────────────────────
_SECRET_KEY = None
_ALGORITHM = "HS256"
_COOKIE_NAME = "auth_token"


def _get_secret_key() -> str:
    """Lazy load JWT secret key từ env."""
    global _SECRET_KEY
    if _SECRET_KEY is None:
        _SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "").strip()
        if not _SECRET_KEY:
            # Fallback: derive từ DATABASE_URL hoặc dùng default
            # Không lý tưởng nhưng đảm bảo backward compatible
            import hashlib
            fallback_material = (
                os.environ.get("BOT_SECRET", "")
                or os.environ.get("ADMIN_MASTER_KEY", "")
                or os.environ.get("DATABASE_URL", "")
                or "default-secret-change-me"
            )
            _SECRET_KEY = hashlib.sha256(fallback_material.encode()).hexdigest()
            print("[JWT WARN] JWT_SECRET_KEY not set, using derived key. Set JWT_SECRET_KEY in env for production.")
    return _SECRET_KEY


def _get_expire_hours() -> int:
    """JWT expire time in hours."""
    try:
        return int(os.environ.get("JWT_EXPIRE_HOURS", "24"))
    except (ValueError, TypeError):
        return 24


def get_cookie_name() -> str:
    """Tên cookie chứa JWT token."""
    return _COOKIE_NAME


def create_access_token(user_id: int, username: str, role: str) -> str:
    """
    Tạo JWT access token.

    Args:
        user_id: dashboard_users.id
        username: dashboard_users.username
        role: dashboard_users.role (ADMIN, USER, VIEWER)

    Returns:
        JWT token string
    """
    now = datetime.now(timezone.utc)
    expire = now + timedelta(hours=_get_expire_hours())

    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": expire,
    }

    return jwt.encode(payload, _get_secret_key(), algorithm=_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """
    Decode và verify JWT token.

    Returns:
        payload dict nếu valid, None nếu invalid/expired
    """
    try:
        payload = jwt.decode(
            token,
            _get_secret_key(),
            algorithms=[_ALGORITHM]
        )
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None
