# app/api/system.py
# Tất cả endpoints hệ thống: engine status, trading mode,
# strategies, OTF, scan-debug, kill-switch, admin

import json
import asyncio
from datetime import timedelta
from typing import Optional
from fastapi import APIRouter, HTTPException

from app.core.time_utils import utc_now, vn_now, vn_day_to_utc_range

router = APIRouter()


# ============================================================
# ENGINE STATUS
# ============================================================

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


# ============================================================
# PRICE FEED
# ============================================================

@router.get("/api/price-feed/status")
async def price_feed_status():
    from app.services.price_feed import get_price_feed
    return get_price_feed().get_stats()


# ============================================================
# TRADING MODE
# ============================================================

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
    return {
        "status": "updated",
        "mode": mode,
        "warning": "LIVE uses real money!" if mode == "LIVE" else None
    }


# ============================================================
# STRATEGIES
# ============================================================

@router.get("/api/strategies")
async def list_strategies():
    from app.strategies.registry import list_all, _REGISTRY
    from app.services.config_service import get_runtime_config
    cfg = get_runtime_config()
    active = [s.strip() for s in cfg.get("ACTIVE_STRATEGIES", "candlestick").split(",")]
    return {
        "all": list_all(),
        "active": active,
        "details": {
            n: {"supported_timeframes": s.SUPPORTED_TIMEFRAMES}
            for n, s in _REGISTRY.items()
        }
    }


@router.put("/api/strategies/active")
async def update_strategies(payload: dict):
    from app.services.config_service import update_runtime_config
    strategies = payload.get("strategies", ["candlestick"])
    update_runtime_config({"ACTIVE_STRATEGIES": ",".join(strategies)})
    return {"status": "updated", "active": strategies}


# ============================================================
# OPEN TRADE FILTER
# ============================================================

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

    # Dùng VN day range chuyển sang UTC để query đúng
    today_start_utc, _ = vn_day_to_utc_range(vn_now().date().isoformat())

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
        ), {"today": today_start_utc}).fetchone()
        streak_rows = db.execute(text(
            "SELECT status FROM signals "
            "WHERE status IN ('WIN','LOSS') "
            "ORDER BY exit_time DESC LIMIT 10"
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
        "today": {
            "total": today_r[0] or 0,
            "wins": today_r[1] or 0,
            "losses": today_r[2] or 0,
            "pnl_pct": float(today_r[3] or 0),
        },
        "current_loss_streak": loss_streak,
    }


# ============================================================
# SCAN DEBUG
# ============================================================

@router.get("/api/scan-debug")
async def get_scan_debug(
    page: int = 1,
    limit: int = 50,
    passed_score: Optional[bool] = None,
    block_reason: Optional[str] = None,
    symbol: Optional[str] = None,
):
    from app.db.async_pool import get_async_pool, serialize_records
    pool = await get_async_pool()
    conds = ["1=1"]
    params = []
    idx = 1
    if passed_score is not None:
        conds.append(f"passed_score = ${idx}")
        params.append(passed_score)
        idx += 1
    if block_reason:
        conds.append(f"block_reason LIKE ${idx}")
        params.append(f"%{block_reason}%")
        idx += 1
    if symbol:
        conds.append(f"symbol = ${idx}")
        params.append(symbol)
        idx += 1
    where = " AND ".join(conds)
    offset = (page - 1) * limit
    async with pool.acquire() as conn:
        count = await conn.fetchval(
            f"SELECT COUNT(*) FROM scan_debug WHERE {where}", *params
        )
        rows = await conn.fetch(
            f"SELECT * FROM scan_debug WHERE {where} "
            f"ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}",
            *params
        )
    return {
        "data": serialize_records(rows),
        "total": count or 0,
        "page": page,
        "limit": limit,
    }


@router.get("/api/scan-debug/block-reasons")
async def get_block_reasons():
    from app.db.async_pool import get_async_pool, serialize_records
    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT block_reason, COUNT(*) as count, "
            "ROUND(AVG(total_score)::numeric, 3) as avg_score "
            "FROM scan_debug WHERE block_reason IS NOT NULL "
            "GROUP BY block_reason ORDER BY count DESC"
        )
    return serialize_records(rows)


# ============================================================
# ADMIN — REFRESH VIEWS
# ============================================================

@router.post("/api/admin/refresh-views")
async def refresh_views():
    from app.services.mv_refresh import _do_refresh
    await asyncio.to_thread(_do_refresh)
    return {"status": "refreshed"}


# ============================================================
# ADMIN — CANCEL ALL PENDING
# ============================================================

@router.post("/api/admin/cancel-all-pending")
async def cancel_all_pending():
    """
    Cancel tất cả pending WAIT.

    PAPER: chỉ update DB.
    LIVE/TESTNET: cancel exchange orders trước, rồi update DB.
    """
    from app.core.trading_mode import get_current_mode, TradingMode
    from app.db.session import SessionLocal
    from app.db.models import PendingSignal
    from app.services.execution_service import cancel_entry_and_exits, get_entry_order_status

    mode = get_current_mode()
    now = utc_now()
    results = {"cancelled": 0, "filled": 0, "errors": []}

    with SessionLocal() as db:
        pendings = db.query(PendingSignal).filter(
            PendingSignal.status == "WAIT"
        ).all()

        for p in pendings:
            try:
                # LIVE/TESTNET: dọn exchange trước
                if mode != TradingMode.PAPER and p.exchange_order_id:
                    cancel_entry_and_exits(p)

                    info = get_entry_order_status(p.symbol, p.exchange_order_id)
                    p.executed_qty = float(info.get("executed_qty") or p.executed_qty or 0)
                    p.exchange_status = info.get("status", p.exchange_status)
                    if info.get("avg_price"):
                        p.avg_fill_price = float(info["avg_price"])
                    p.last_exchange_sync_at = now

                # Chốt local status
                if (p.executed_qty or 0) > 0:
                    p.status = "FILLED"
                    p.rejection_reason = "ADMIN_CANCEL"
                    results["filled"] += 1
                else:
                    p.status = "CANCELLED"
                    p.rejection_reason = "ADMIN_CANCEL"
                    results["cancelled"] += 1

            except Exception as e:
                results["errors"].append(f"[{p.id}] {p.symbol}: {e}")

        db.commit()

    return results


# ============================================================
# ADMIN — KILL SWITCH
# ============================================================

@router.post("/api/admin/kill-switch")
async def kill_switch():
    """
    Emergency: dọn sạch toàn bộ hệ thống.

    PAPER:
      - Pending WAIT -> CANCELLED
      - Signal OPEN -> MANUAL (KILL_SWITCH)

    LIVE / TESTNET:
      1. Cancel ALL exchange orders
      2. Pause ngắn
      3. Close ALL exchange positions
      4. Sync pending final
      5. Signal OPEN -> MANUAL (KILL_SWITCH)
      6. Audit log + telegram notify
    """
    from app.services.kill_switch_service import execute_kill_switch
    result = await asyncio.to_thread(execute_kill_switch)
    return result


# ============================================================
# MANUAL CLOSE / CANCEL
# ============================================================

@router.post("/api/signals/{signal_id}/close")
async def close_signal_manual(signal_id: int):
    """
    Manual close 1 signal OPEN.
    Bot sẽ:
    - close position trên exchange (live/testnet)
    - hủy remainder entry nếu còn
    - cleanup exit orders
    - update số liệu cuối cùng
    """
    from app.services.manual_close_service import manual_close_signal
    result = await asyncio.to_thread(manual_close_signal, signal_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@router.post("/api/pending/{pending_id}/cancel")
async def cancel_pending_manual(pending_id: int):
    """
    Manual cancel 1 pending WAIT.
    Nếu có exchange order -> hủy luôn.
    """
    from app.services.manual_close_service import manual_cancel_pending
    result = await asyncio.to_thread(manual_cancel_pending, pending_id)
    if not result["success"]:
        raise HTTPException(status_code=400, detail=result["error"])
    return result