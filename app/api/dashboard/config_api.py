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
    return {r["key"]: r["value"] for r in rows}

@router.put("/api/app-config")
async def update_app_config(updates: Dict[str, str]):
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
