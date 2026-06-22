"""
APP_ROLE detection & constants.

Quyết định app chạy ở mode nào dựa trên ENV:
  - ADMIN: control plane + admin bot trading
  - BOT:   user bot runtime, bootstrap qua admin API

Mặc định: ADMIN (backward compatible với codebase hiện tại)
"""

import os
import re
from urllib.parse import urlparse

# ── Constants ─────────────────────────────────────────────
ROLE_ADMIN = "ADMIN"
ROLE_BOT = "BOT"

_VALID_ROLES = {ROLE_ADMIN, ROLE_BOT}

# ── Cache ─────────────────────────────────────────────────
_current_role = None


def get_app_role() -> str:
    """
    Đọc APP_ROLE từ env.
    Mặc định ADMIN nếu không set → backward compatible.
    """
    global _current_role
    if _current_role is not None:
        return _current_role

    raw = os.environ.get("APP_ROLE", ROLE_ADMIN).strip().upper()

    if raw not in _VALID_ROLES:
        print(f"[APP_ROLE WARN] Unknown APP_ROLE='{raw}', defaulting to ADMIN")
        raw = ROLE_ADMIN

    _current_role = raw
    return _current_role


def is_admin() -> bool:
    """True nếu app đang chạy ở mode ADMIN."""
    return get_app_role() == ROLE_ADMIN


def is_bot() -> bool:
    """True nếu app đang chạy ở mode BOT."""
    return get_app_role() == ROLE_BOT


def get_bot_env():
    """
    Đọc env tối thiểu cho BOT mode.
    Chỉ gọi khi is_bot() == True.

    Returns:
        dict với keys: bot_id, bot_secret, admin_endpoints, cache_path
        hoặc raise nếu thiếu env bắt buộc.
    """
    bot_id = os.environ.get("BOT_ID", "").strip()
    bot_secret = os.environ.get("BOT_SECRET", "").strip()
    admin_endpoints_raw = os.environ.get("ADMIN_ENDPOINTS", "").strip()
    cache_path = os.environ.get(
        "BOOTSTRAP_CACHE_PATH",
        os.path.expanduser("~/.botcache/bootstrap.enc")
    )
    cache_path = os.path.abspath(
        os.path.expandvars(os.path.expanduser(cache_path.strip()))
    )

    # ── Validate bắt buộc ──────────────────────────────────
    missing = []
    if not bot_id:
        missing.append("BOT_ID")
    if not bot_secret:
        missing.append("BOT_SECRET")
    if not admin_endpoints_raw:
        missing.append("ADMIN_ENDPOINTS")

    if missing:
        raise EnvironmentError(
            f"[BOT MODE] Missing required env: {', '.join(missing)}"
        )

    # ── Parse endpoints ────────────────────────────────────
    def _normalize_endpoint(raw: str) -> str:
        raw = raw.strip()
        match = re.match(r"^\[[^\]]+\]\((https?://[^)]+)\)$", raw)
        if match:
            raw = match.group(1)
        raw = raw.rstrip("/")
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        return raw

    admin_endpoints = []
    for ep in admin_endpoints_raw.split(","):
        normalized = _normalize_endpoint(ep)
        if normalized:
            admin_endpoints.append(normalized)

    if not admin_endpoints:
        raise EnvironmentError(
            "[BOT MODE] ADMIN_ENDPOINTS is set but contains no valid URLs. "
            "Use plain URLs like ADMIN_ENDPOINTS=http://host:8002"
        )

    return {
        "bot_id": bot_id,
        "bot_secret": bot_secret,
        "admin_endpoints": admin_endpoints,
        "cache_path": cache_path,
    }
