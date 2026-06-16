"""Async PostgreSQL pool cho Dashboard API queries"""
import ssl, os
from typing import Optional
import asyncpg

_pool: Optional[asyncpg.Pool] = None


async def get_async_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        db_url = os.getenv("DATABASE_URL", "")

        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE

        _pool = await asyncpg.create_pool(
            db_url,
            ssl=ssl_ctx,
            min_size=2,
            max_size=10,
            command_timeout=60,
            server_settings={
                "timezone": "UTC",
                "search_path": "public",
            },
        )
        print("✅ Async DB pool ready")
    return _pool


async def close_async_pool():
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


def serialize_record(record) -> dict:
    import decimal
    from datetime import datetime, date
    out = {}
    for key in record.keys():
        val = record[key]
        if isinstance(val, decimal.Decimal):
            out[key] = float(val)
        elif isinstance(val, (datetime, date)):
            out[key] = val.isoformat()
        else:
            out[key] = val
    return out


def serialize_records(records) -> list:
    return [serialize_record(r) for r in records]
