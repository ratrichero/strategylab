"""Async PostgreSQL pool for dashboard API queries."""
import ssl
from typing import Optional

import asyncpg

from app.db.session import get_database_url

_pool: Optional[asyncpg.Pool] = None
_pool_db_url: str = ""


async def get_async_pool() -> asyncpg.Pool:
    global _pool, _pool_db_url

    db_url = get_database_url()
    if not db_url:
        raise RuntimeError("Database is not configured")

    if _pool is not None and _pool_db_url != db_url:
        await close_async_pool()

    if _pool is None:
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
        _pool_db_url = db_url
        print("Async DB pool ready")
    return _pool


async def close_async_pool():
    global _pool, _pool_db_url
    if _pool:
        await _pool.close()
        _pool = None
        _pool_db_url = ""


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
