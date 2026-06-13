# app/api/system.py
# Tất cả endpoints hệ thống: engine status, trading mode, 
# strategies, OTF, scan-debug, kill-switch, admin

import json
import asyncio
from datetime import datetime, timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/api/engine/status")
async def engine_status():
    from app.services.price_feed import get_price_feed
    from app.core.trading_mode import get_trading_mode
    from app.services.config_service import get_runtime_config

    cfg = get_runtime_config()
    return {
        "version": cfg.get("ENGINE_VERSION", "5.0"),
        "trading_mode": get_trading_mode().describe(),
        "price_feed": get_price_feed().get_stats(),
        "scheduler_on": cfg.get("ENABLE_SCHEDULER", True),
        "monitor_on": cfg.get("ENABLE_MONITOR", True),
        "active_strategies": cfg.get("ACTIVE_STRATEGIES", "candlestick"),
        "top_limit": cfg.get("TOP_LIMIT", 200),
        "max_open_trades": cfg.get("MAX_OPEN_TRADES", 10),
    }


@router.get("/api/price-feed/status")
async def price_feed_status():
    from app.services.price_feed import get_price_feed
    return get_price_feed().get_stats()


@router.get("/api/trading-mode")
async def get_mode():
    from app.core.trading_mode import get_trading_mode
    return get_trading_mode().describe()


@router.put("/api/trading-mode")
async def set_mode(payload: dict):
    from app.services.config_service import update_runtime_config
    from app.core.trading_mode import get_trading_mode
    mode = payload.get("mode", "PAPER").upper()
    if mode not in ["PAPER", "TESTNET", "LIVE"]:
        raise HTTPException(400, "Invalid mode")
    update_runtime_config({"TRADING_MODE": mode})
    get_trading_mode().invalidate_cache()
    return {"status": "updated", "mode": mode,
            "warning": "LIVE uses real money!" if mode == "LIVE" else None}


@router.get("/api/strategies")
async def list_strategies():
    from app.strategies.registry import list_all, _REGISTRY
    from app.services.config_service import get_runtime_config
    cfg = get_runtime_config()
    active = [s.strip() for s in cfg.get("ACTIVE_STRATEGIES", "candlestick").split(",")]
    return {"all": list_all(), "active": active,
            "details": {n: {"supported_timeframes": s.SUPPORTED_TIMEFRAMES}
                        for n, s in _REGISTRY.items()}}


@router.put("/api/strategies/active")
async def update_strategies(payload: dict):
    from app.services.config_service import update_runtime_config
    strategies = payload.get("strategies", ["candlestick"])
    update_runtime_config({"ACTIVE_STRATEGIES": ",".join(strategies)})
    return {"status": "updated", "active": strategies}


@router.get("/api/open-trade-filter")
async def get_otf():
    from app.services.config_service import get_runtime_config
    return get_runtime_config().get("OPEN_TRADE_FILTER", {"enabled": False})


@router.put("/api/open-trade-filter")
async def update_otf(payload: dict):
    from app.services.config_service import update_runtime_config
    update_runtime_config({"OPEN_TRADE_FILTER": json.dumps(payload)})
    return {"status": "updated"}


@router.get("/api/open-trade-filter/status")
async def otf_status():
    from app.db.session import SessionLocal
    from app.db.models import Signal, PendingSignal
    from sqlalchemy import text

    today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=7)

    with SessionLocal() as db:
        open_count = db.query(Signal).filter(Signal.status == "OPEN").count()
        pending_count = db.query(PendingSignal).filter(PendingSignal.status == "WAIT").count()
        tf_rows = db.execute(text(
            "SELECT timeframe, COUNT(*) cnt FROM signals WHERE status='OPEN' GROUP BY timeframe"
        )).fetchall()
        today_r = db.execute(text(
            "SELECT COUNT(*) total, "
            "COUNT(*) FILTER (WHERE status='WIN') wins, "
            "COUNT(*) FILTER (WHERE status='LOSS') losses, "
            "SUM(result_percent) FILTER (WHERE status IN ('WIN','LOSS')) pnl "
            "FROM signals WHERE exit_time >= :today"
        ), {"today": today}).fetchone()
        streak_rows = db.execute(text(
            "SELECT status FROM signals WHERE status IN ('WIN','LOSS') ORDER BY exit_time DESC LIMIT 10"
        )).fetchall()

    loss_streak = 0
    for r in streak_rows:
        if r[0] == "LOSS":
            loss_streak += 1
        else:
            break

    return {
        "open_trades": open_count,
        "pending_trades": pending_count,
        "per_timeframe": {r[0]: r[1] for r in tf_rows},
        "today": {"total": today_r[0] or 0, "wins": today_r[1] or 0,
                  "losses": today_r[2] or 0, "pnl_pct": float(today_r[3] or 0)},
        "current_loss_streak": loss_streak,
    }


@router.get("/api/scan-debug")
async def get_scan_debug(
    page: int = 1, limit: int = 50,
    passed_score: Optional[bool] = None,
    block_reason: Optional[str] = None,
    symbol: Optional[str] = None,
):
    from app.db.async_pool import get_async_pool, serialize_records
    pool = await get_async_pool()
    conds = ["1=1"]; params = []; idx = 1
    if passed_score is not None:
        conds.append(f"passed_score = ${idx}"); params.append(passed_score); idx += 1
    if block_reason:
        conds.append(f"block_reason LIKE ${idx}"); params.append(f"%{block_reason}%"); idx += 1
    if symbol:
        conds.append(f"symbol = ${idx}"); params.append(symbol); idx += 1
    where = " AND ".join(conds)
    offset = (page - 1) * limit
    async with pool.acquire() as conn:
        count = await conn.fetchval(f"SELECT COUNT(*) FROM scan_debug WHERE {where}", *params)
        rows = await conn.fetch(
            f"SELECT * FROM scan_debug WHERE {where} ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}",
            *params)
    return {"data": serialize_records(rows), "total": count or 0, "page": page, "limit": limit}


@router.get("/api/scan-debug/block-reasons")
async def get_block_reasons():
    from app.db.async_pool import get_async_pool, serialize_records
    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT block_reason, COUNT(*) as count, "
            "ROUND(AVG(total_score)::numeric, 3) as avg_score "
            "FROM scan_debug WHERE block_reason IS NOT NULL "
            "GROUP BY block_reason ORDER BY count DESC")
    return serialize_records(rows)


@router.post("/api/admin/refresh-views")
async def refresh_views():
    from app.services.mv_refresh import _do_refresh
    await asyncio.to_thread(_do_refresh)
    return {"status": "refreshed"}


@router.post("/api/admin/cancel-all-pending")
async def cancel_pending():
    from app.db.session import SessionLocal
    from app.db.models import PendingSignal
    with SessionLocal() as db:
        count = db.query(PendingSignal).filter(
            PendingSignal.status == "WAIT"
        ).update({"status": "CANCELLED", "rejection_reason": "admin_api_cancel"})
        db.commit()
    return {"cancelled": count}


@router.post("/api/admin/kill-switch")
async def kill_switch():
    from app.db.session import SessionLocal
    from app.db.models import Signal, PendingSignal

    results = {"pending_cancelled": 0, "trades_closed": 0}
    with SessionLocal() as db:
        pending_count = db.query(PendingSignal).filter(
            PendingSignal.status == "WAIT"
        ).update({"status": "CANCELLED", "rejection_reason": "KILL_SWITCH"})
        results["pending_cancelled"] = pending_count

        open_trades = db.query(Signal).filter(Signal.status == "OPEN").all()
        for trade in open_trades:
            trade.status = "MANUAL"
            trade.exit_reason = "KILL_SWITCH"
            trade.exit_time = datetime.utcnow()
            results["trades_closed"] += 1
        db.commit()

    print(f"🚨 KILL SWITCH: {results['pending_cancelled']} pending, {results['trades_closed']} trades")
    return {"status": "killed", **results}