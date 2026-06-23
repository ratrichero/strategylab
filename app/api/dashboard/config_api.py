from typing import Any, Dict
from fastapi import APIRouter, HTTPException
from app.db.async_pool import get_async_pool
import json

router = APIRouter(tags=["Dashboard - Config"])

@router.get("/api/app-config")
async def get_app_config():
    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM app_config ORDER BY key")
    config = {r["key"]: r["value"] for r in rows}

    for key in [
        "DATABASE_URL",
        "CONNECTION_OVERRIDE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_TOKEN",
    ]:
        config.pop(key, None)

    from app.core.app_role import is_bot
    if is_bot():
        config.pop("DASHBOARD_API_KEY", None)

    return config

@router.put("/api/app-config")
async def update_app_config(updates: Dict[str, str]):
    blocked_global = {
        "DATABASE_URL",
        "CONNECTION_OVERRIDE",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_TOKEN",
    }
    forbidden_global = sorted(k for k in updates if k in blocked_global)
    if forbidden_global:
        raise HTTPException(403, f"These keys are env-only: {', '.join(forbidden_global)}")

    from app.core.app_role import is_bot
    if is_bot():
        blocked_keys = {
            "DASHBOARD_API_KEY",
        }
        forbidden = sorted(k for k in updates if k in blocked_keys)
        if forbidden:
            raise HTTPException(403, f"BOT role cannot update: {', '.join(forbidden)}")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        for k, v in updates.items():
            await conn.execute(
                "INSERT INTO app_config (key, value, updated_at) "
                "VALUES ($1, $2, NOW()) "
                "ON CONFLICT (key) DO UPDATE SET value=$2, updated_at=NOW()",
                k, str(v))
    try:
        from app.services.config_service import get_runtime_config
        get_runtime_config(force_reload=True)
    except: pass
    return {"status": "ok", "updated": list(updates.keys())}

@router.post("/api/query-lab/execute")
async def execute_query(body: Dict[str, Any]):
    sql = body.get("sql", "").strip()
    if not sql.lower().startswith("select"):
        raise HTTPException(400, "Only SELECT allowed")
    forbidden = ["insert","update","delete","drop","truncate","alter","create"]
    for kw in forbidden:
        if f" {kw} " in f" {sql.lower()} ":
            raise HTTPException(400, f"Forbidden: {kw}")
    pool = await get_async_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql)
        import decimal
        from datetime import datetime, date
        def safe(r):
            out = {}
            for k in r.keys():
                v = r[k]
                if isinstance(v, decimal.Decimal): out[k] = float(v)
                elif isinstance(v, (datetime, date)): out[k] = v.isoformat()
                else: out[k] = v
            return out
        return {"data": [safe(r) for r in rows], "row_count": len(rows)}
    except Exception as e:
        raise HTTPException(400, str(e))

# ← CHANGED: thêm endpoint cho bot dashboard hiển thị license info
@router.get("/api/bot-license-info")
async def bot_license_info():
    """
    Trả license info cho bot dashboard.
    Chỉ có ý nghĩa khi APP_ROLE=BOT.
    ADMIN mode trả empty.
    """
    from app.core.app_role import is_bot, get_app_role

    if not is_bot():
        return {
            "app_role": get_app_role(),
            "license": None,
        }

    try:
        from app.bot_runtime.runtime import get_bot_runtime
        runtime = get_bot_runtime()
        return {
            "app_role": get_app_role(),
            "license": runtime.get_license_info(),
        }
    except Exception as e:
        return {
            "app_role": get_app_role(),
            "license": None,
            "error": str(e),
        }

@router.get("/api/app-role")
async def get_app_role_info():
    """Trả APP_ROLE hiện tại."""
    from app.core.app_role import get_app_role
    return {"app_role": get_app_role()}
