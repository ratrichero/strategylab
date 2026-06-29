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
# TRADING MODE
# ============================================================

@router.get("/api/trading-mode")
async def get_mode():
    from app.core.trading_mode import get_trading_mode
    return get_trading_mode().describe()


@router.get("/api/user-stream/status")
async def user_stream_status():
    from app.services.binance_user_stream_service import get_user_stream
    return get_user_stream().get_stats()


@router.get("/api/live/health")
async def live_health():
    from app.services.live_health_service import get_live_health
    return await asyncio.to_thread(get_live_health)


@router.post("/api/user-stream/restart")
async def user_stream_restart():
    from app.services.binance_user_stream_service import restart_user_stream
    restart_user_stream()
    return {"ok": True, "message": "User stream restart requested"}


@router.post("/api/admin/backfill-exchange-close-unknown")
async def backfill_exchange_close_unknown(limit: int = 500, dry_run: bool = True):
    from app.services.exchange_close_backfill import backfill_exchange_close_unknown as run_backfill
    return await asyncio.to_thread(run_backfill, limit=limit, dry_run=dry_run)


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
            n: {
                "supported_timeframes": s.SUPPORTED_TIMEFRAMES,
                "patterns": list(s.default_pattern_thresholds().keys()),
                "description": s.STRATEGY_DESCRIPTION if hasattr(s, "STRATEGY_DESCRIPTION") else "",
            }
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

# ============================================================
# POSITION SIZE CONFIG
# ============================================================

@router.get("/api/position-size")
async def get_position_size():
    from app.services.config_service import get_runtime_config
    return get_runtime_config().get("POSITION_SIZE_CONFIG", {})


@router.put("/api/position-size")
async def update_position_size(payload: dict):
    from app.services.config_service import update_runtime_config
    update_runtime_config({"POSITION_SIZE_CONFIG": json.dumps(payload)})
    return {"status": "updated", "config": payload}


# ============================================================
# CONNECTION SETTINGS
# ============================================================

@router.get("/api/system/connections")
async def get_connections():
    import os as _os
    from app.services.config_service import (
        CONNECTION_KEYS,
        get_connection_value, get_app_config_value, mask_secret,
    )

    fields = {}

    for key in CONNECTION_KEYS:
        app_val = get_app_config_value(key, "")
        eff_val = get_connection_value(key, "")
        source = "app_config" if app_val else "env"
        fields[key] = {
            "has_value": bool(eff_val),
            "masked": mask_secret(eff_val),
            "source": source,
        }

    return {
        "override_enabled": True,
        "database_url": {
            "editable": False,
            "source": "env_only",
            "has_value": bool(_os.environ.get("DATABASE_URL", "")),
        },
        "fields": fields,
    }


@router.put("/api/system/connections")
async def update_connections(payload: dict):
    from app.services.config_service import update_runtime_config, CONNECTION_KEYS

    values = payload.get("values", {}) or {}

    data = {}
    for key in CONNECTION_KEYS:
        if key in values:
            data[key] = "" if values[key] is None else str(values[key])

    update_runtime_config(data)
    return {"status": "updated", "override_enabled": True}

@router.get("/api/binance/account")
async def binance_account(target: str = "live"):
    """
    Test kết nối Binance Futures.
    Đọc key từ app_config trước, fallback .env
    """
    import os
    from app.services.config_service import get_app_config_value

    def _get_key(db_key: str, env_key: str) -> str:
        """Ưu tiên app_config, fallback .env"""
        val = get_app_config_value(db_key, "")
        if val and val.strip():
            return val.strip()
        return os.getenv(env_key, "")

    if target == "testnet":
        api_key    = _get_key("BINANCE_TESTNET_API_KEY",    "BINANCE_TESTNET_API_KEY")
        api_secret = _get_key("BINANCE_TESTNET_API_SECRET", "BINANCE_TESTNET_API_SECRET")
        base_url   = "https://testnet.binancefuture.com"
        label      = "Testnet"
    else:
        api_key    = _get_key("BINANCE_API_KEY",    "BINANCE_API_KEY")
        api_secret = _get_key("BINANCE_API_SECRET", "BINANCE_API_SECRET")
        base_url   = "https://fapi.binance.com"
        label      = "Mainnet"

    if not api_key or not api_secret:
        return {
            "connected": False,
            "target":    target,
            "message":   f"Missing API key/secret for {label}. Check Connection tab or .env",
            "balance":   None,
        }

    try:
        from binance.um_futures import UMFutures

        client  = UMFutures(key=api_key, secret=api_secret, base_url=base_url)
        account = client.account()

        balance = 0.0
        for asset in account.get("assets", []):
            if asset["asset"] == "USDT":
                balance = float(asset["availableBalance"])
                break

        positions = []
        for p in account.get("positions", []):
            amt = float(p.get("positionAmt", 0))
            if amt != 0:
                positions.append({
                    "symbol":   p["symbol"],
                    "side":     "LONG" if amt > 0 else "SHORT",
                    "size":     abs(amt),
                    "entry":    float(p.get("entryPrice", 0)),
                    "pnl":      float(p.get("unrealizedProfit", 0)),
                    "leverage": int(p.get("leverage", 1)),
                })

        return {
            "connected":      True,
            "target":         target,
            "message":        f"Connected to Binance {label}",
            "balance":        round(balance, 2),
            "currency":       "USDT",
            "open_positions": len(positions),
            "positions":      positions[:10],
        }

    except ImportError:
        return {
            "connected": False,
            "target":    target,
            "message":   "binance-futures-connector not installed. pip install binance-futures-connector",
            "balance":   None,
        }
    except Exception as e:
        return {
            "connected": False,
            "target":    target,
            "message":   f"Connection failed: {str(e)}",
            "balance":   None,
        }
    
# ============================================================
# BTC OVERVIEW
# ============================================================

@router.get("/api/btc-overview")
async def btc_overview():
    from app.services.btc_overview import get_btc_overview
    return await asyncio.to_thread(get_btc_overview)


# ============================================================
# COINGECKO TOP MC PROXY
# ============================================================

@router.get("/api/coingecko/top-mc")
async def coingecko_top_mc(limit: int = 50):
    """
    Proxy CoinGecko top market cap.
    Trả về danh sách symbol dạng BTCUSDT, ETHUSDT...
    """
    import aiohttp

    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "market_cap_desc",
        "per_page": min(limit, 250),
        "page": 1,
        "x_cg_demo_api_key": "CG-r9KNtFCb794fJuozcK1AMr2W",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params=params) as resp:
                data = await resp.json()

        # Lọc stablecoin + map sang USDT pair
        STABLE = {"usdt", "usdc", "busd", "dai", "tusd", "usdp", "fdusd"}
        symbols = []
        for coin in data:
            sym = coin.get("symbol", "").lower()
            if sym in STABLE:
                continue
            pair = sym.upper() + "USDT"
            symbols.append({
                "symbol": pair,
                "name": coin.get("name", ""),
                "market_cap_rank": coin.get("market_cap_rank"),
            })

        return {
            "symbols": symbols,
            "count": len(symbols),
            "raw_symbols": [s["symbol"] for s in symbols],
        }

    except Exception as e:
        return {
            "symbols": [],
            "count": 0,
            "error": str(e),
        }
    
@router.post("/api/admin/cancel-all-active")
async def close_all_active():
    """
    Close tất cả signal OPEN bằng cách gọi manual_close_signal() cho từng cái.
    """
    from app.db.session import SessionLocal
    from app.db.models import Signal
    from app.services.manual_close_service import manual_close_signal

    results = {"closed": 0, "failed": 0, "errors": []}

    with SessionLocal() as db:
        open_signals = db.query(Signal).filter(Signal.status == "OPEN").all()
        ids = [s.id for s in open_signals]

    for signal_id in ids:
        try:
            result = await asyncio.to_thread(manual_close_signal, signal_id)
            if result.get("success"):
                results["closed"] += 1
            else:
                results["failed"] += 1
                results["errors"].append(f"Signal {signal_id}: {result.get('error')}")
        except Exception as e:
            results["failed"] += 1
            results["errors"].append(f"Signal {signal_id}: {str(e)}")

    if results["closed"] > 0:
        try:
            from app.services.mv_refresh import refresh_views_async
            refresh_views_async("close_all_active")
        except Exception as e:
            results["errors"].append(f"MV refresh trigger: {e}")

    return results
