"""Dashboard Signals API — PATCHED: unified VN date parsing"""
from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter
from app.db.async_pool import get_async_pool, serialize_records

router = APIRouter(tags=["Dashboard - Signals"])


# ── Unified date parser (same logic as signal_analysis_handler) ──

def _parse_dt(s):
    """Parse any datetime string to naive UTC datetime."""
    if not s:
        return None
    import re
    s = str(s).strip()
    s = re.sub(r'\.\d+', '', s)      # Strip milliseconds
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except:
        return None


def _parse_vn_date(s, is_end=False):
    """Parse date string with VN timezone awareness.
    
    Plain date "2026-06-15":
      - start → 2026-06-15 00:00 VN = 2026-06-14 17:00 UTC
      - end   → 2026-06-16 00:00 VN = 2026-06-15 17:00 UTC (next day, exclusive)
    
    ISO datetime "2026-06-15T00:00:00+07:00":
      - parsed directly, no +1 day for end
    """
    if not s:
        return None
    s = str(s).strip()

    # Plain date like "2026-06-15"
    if "T" not in s:
        base = _parse_dt(s + "T00:00:00+07:00")
        if is_end and base:
            return base + timedelta(days=1)
        return base

    # Full ISO datetime — parse as-is
    return _parse_dt(s)


@router.get("/api/signals")
async def get_signals(page:int=1, limit:int=50, symbol:Optional[str]=None,
    timeframe:Optional[str]=None, direction:Optional[str]=None,
    status:Optional[str]=None, pattern:Optional[str]=None,
    regime:Optional[str]=None, start_date:Optional[str]=None,
    end_date:Optional[str]=None, date_field:Optional[str]="created_at",
    min_score:Optional[float]=None, max_score:Optional[float]=None,
    strategy:Optional[str]=None, include_manual:bool=False):
    pool = await get_async_pool()
    conds = ["1=1"]; params = []; idx = 1
    for col, val in [("symbol",symbol),("timeframe",timeframe),("direction",direction),
                     ("pattern",pattern),("regime",regime),
                     ("strategy_name",strategy)]:
        if val:
            conds.append(f"{col}=${idx}"); params.append(val); idx+=1
    if status:
        conds.append(f"status=${idx}"); params.append(status); idx+=1
    dc = "exit_time" if date_field=="exit_time" else "created_at"

    # ✅ PATCHED: use _parse_vn_date for VN-aware date handling
    start_dt = _parse_vn_date(start_date, is_end=False)
    end_dt = _parse_vn_date(end_date, is_end=True)

    if start_dt:
        conds.append(f"{dc}>=${idx}"); params.append(start_dt); idx+=1
    if end_dt:
        conds.append(f"{dc}<${idx}"); params.append(end_dt); idx+=1

    if min_score is not None: conds.append(f"score>=${idx}"); params.append(min_score); idx+=1
    if max_score is not None: conds.append(f"score<=${idx}"); params.append(max_score); idx+=1
    where = " AND ".join(conds); offset = (page-1)*limit
    async with pool.acquire() as conn:
        # Use view for WIN/LOSS/MANUAL (accept 5min delay), realtime for OPEN
        if status == 'OPEN':
            # Realtime query for open signals
            count = await conn.fetchval(f"SELECT COUNT(*) FROM signals WHERE {where}", *params)
            rows = await conn.fetch(f"""
                SELECT * FROM signals
                WHERE {where}
                ORDER BY candle_time DESC
                LIMIT {limit} OFFSET {offset}
            """, *params)
        else:
            # Use view for closed trades (WIN/LOSS/MANUAL)
            view_where = where if (status or include_manual) else f"{where} AND status IN ('WIN','LOSS')"
            count = await conn.fetchval(f"SELECT COUNT(*) FROM mv_signal_performance WHERE {view_where}", *params)
            rows = await conn.fetch(f"""
                SELECT * FROM mv_signal_performance
                WHERE {view_where}
                ORDER BY candle_time DESC
                LIMIT {limit} OFFSET {offset}
            """, *params)
    return {"data": serialize_records(rows), "total": count or 0, "page": page, "limit": limit,
            "pages": ((count or 0)+limit-1)//limit}


@router.get("/api/signals/{signal_id}")
async def get_signal_detail(signal_id: int):
    pool = await get_async_pool()
    async with pool.acquire() as conn:
        sig = await conn.fetchrow("SELECT * FROM signals WHERE id=$1", signal_id)
        feat = await conn.fetchrow("SELECT * FROM signal_features WHERE signal_id=$1", signal_id)
        out = await conn.fetchrow("SELECT * FROM trade_outcome_analytics WHERE signal_id=$1", signal_id)
        dbg = await conn.fetchrow("SELECT * FROM scan_debug WHERE signal_id=$1 LIMIT 1", signal_id)
    from app.db.async_pool import serialize_record
    if not sig:
        from fastapi import HTTPException; raise HTTPException(404, "Not found")
    return {"signal": serialize_record(sig),
            "features": serialize_record(feat) if feat else None,
            "outcome": serialize_record(out) if out else None,
            "debug": serialize_record(dbg) if dbg else None}


@router.get("/api/pending-signals")
async def get_pending(page:int=1, limit:int=50, status:Optional[str]=None, symbol:Optional[str]=None):
    pool = await get_async_pool()
    conds = ["1=1"]; params = []; idx = 1
    if status: conds.append(f"status=${idx}"); params.append(status); idx+=1
    if symbol: conds.append(f"symbol=${idx}"); params.append(symbol); idx+=1
    where = " AND ".join(conds); offset = (page-1)*limit
    async with pool.acquire() as conn:
        count = await conn.fetchval(f"SELECT COUNT(*) FROM pending_signals WHERE {where}", *params)
        rows = await conn.fetch(f"SELECT * FROM pending_signals WHERE {where} ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}", *params)
    return {"data": serialize_records(rows), "total": count or 0, "page": page, "limit": limit}


@router.get("/api/engine/versions")
async def get_engine_versions():
    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT engine_version, COUNT(*) total_trades,
            COUNT(*) FILTER (WHERE status='WIN') wins,
            ROUND(100.0*COUNT(*) FILTER (WHERE status='WIN')/NULLIF(COUNT(*),0),1) winrate,
            ROUND(AVG(result_percent)::numeric,3) avg_return
            FROM signals WHERE engine_version IS NOT NULL AND status IN ('WIN','LOSS')
            GROUP BY engine_version ORDER BY engine_version
        """)
    return serialize_records(rows)
