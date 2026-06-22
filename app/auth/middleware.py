"""
Auth middleware cho FastAPI.
Chặn mọi request chưa auth, trừ whitelist.

Dùng approach: route-level dependency thay vì global middleware,
để dễ whitelist và linh hoạt hơn.
"""

import os

from fastapi import Request, HTTPException
from app.auth.jwt_utils import decode_token, get_cookie_name


# ── Whitelist paths không cần auth ────────────────────────────
AUTH_WHITELIST_PREFIXES = [
    "/auth/",           # login, setup, setup-status
    "/health",          # health check
    "/bot/auth/",       # bot machine auth (activate)
    "/bot/heartbeat",   # bot heartbeat
    "/bot/status",      # bot status check
]

# Static files
AUTH_WHITELIST_EXACT = [
    "/",
    "/favicon.ico",
]


def is_public_path(path: str) -> bool:
    expose_docs = os.environ.get("EXPOSE_API_DOCS", "false").strip().lower() == "true"
    if expose_docs and path in {"/docs", "/openapi.json", "/redoc"}:
        return True

    """Check path có nằm trong whitelist không."""
    # Exact match
    if path in AUTH_WHITELIST_EXACT:
        return True

    # Prefix match
    for prefix in AUTH_WHITELIST_PREFIXES:
        if path.startswith(prefix):
            return True

    # Static assets
    if path.startswith("/assets/"):
        return True

    # SPA routes (non-API paths) — serve index.html
    if not path.startswith("/api/") and not path.startswith("/admin/") and not path.startswith("/scan"):
        return True

    return False


def require_auth_from_cookie(request: Request) -> dict:
    """
    Check auth từ cookie.
    Dùng trong middleware hoặc dependency.

    Returns:
        JWT payload dict

    Raises:
        HTTPException 401 nếu không có cookie / token invalid
    """
    cookie_name = get_cookie_name()
    token = request.cookies.get(cookie_name)

    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token expired or invalid")

    return payload