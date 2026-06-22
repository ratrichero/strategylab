from typing import Any, Dict, List

from sqlalchemy import text

from app.core.time_utils import utc_now
from app.core.trading_mode import TradingMode, get_current_mode
from app.db.models import ExecutionCommand, PendingSignal, Signal
from app.db.session import SessionLocal


def _safe_stats(callable_obj, default: Dict[str, Any]) -> Dict[str, Any]:
    try:
        return callable_obj()
    except Exception as e:
        out = dict(default)
        out["error"] = f"{type(e).__name__}: {e}"
        return out


def _db_snapshot() -> Dict[str, Any]:
    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(Signal.status == "OPEN").all()
        pending_wait = db.query(PendingSignal).filter(PendingSignal.status == "WAIT").all()
        pending_placed = [p for p in pending_wait if p.exchange_order_id]

        missing_protection = db.execute(text("""
            SELECT s.id, s.symbol, s.direction, p.id AS pending_id,
                   p.sl_order_id, p.tp_order_id
            FROM signals s
            LEFT JOIN pending_signals p ON p.signal_id = s.id
            WHERE s.status = 'OPEN'
              AND (
                p.id IS NULL
                OR p.sl_order_id IS NULL
                OR p.tp_order_id IS NULL
              )
            ORDER BY s.created_at DESC
            LIMIT 20
        """)).mappings().all()

        stale_pending = db.execute(text("""
            SELECT id, symbol, status, exchange_order_id, placed_at, expire_at
            FROM pending_signals
            WHERE status = 'WAIT'
              AND (
                expire_at < NOW()
                OR (exchange_order_id IS NOT NULL AND placed_at < NOW() - INTERVAL '30 minutes')
              )
            ORDER BY created_at DESC
            LIMIT 20
        """)).mappings().all()

        unknown_close_count = db.query(Signal).filter(
            Signal.exit_reason == "EXCHANGE_CLOSE_UNKNOWN"
        ).count()

        failed_commands = db.query(ExecutionCommand).filter(
            ExecutionCommand.status == "FAILED"
        ).order_by(ExecutionCommand.updated_at.desc()).limit(10).all()

        try:
            recent_events = db.execute(text("""
                SELECT event_type, symbol, order_status, execution_type, created_at
                FROM exchange_order_events
                ORDER BY created_at DESC
                LIMIT 5
            """)).mappings().all()
        except Exception:
            recent_events = []

    return {
        "open_count": len(open_trades),
        "pending_wait_count": len(pending_wait),
        "pending_placed_count": len(pending_placed),
        "open_symbols": sorted({t.symbol for t in open_trades if t.symbol}),
        "pending_symbols": sorted({p.symbol for p in pending_wait if p.symbol}),
        "missing_protection": [dict(row) for row in missing_protection],
        "missing_protection_count": len(missing_protection),
        "stale_pending": [dict(row) for row in stale_pending],
        "stale_pending_count": len(stale_pending),
        "exchange_close_unknown_count": unknown_close_count,
        "failed_commands": [
            {
                "id": cmd.id,
                "symbol": cmd.symbol,
                "command_type": cmd.command_type,
                "error_message": cmd.error_message,
                "updated_at": cmd.updated_at,
            }
            for cmd in failed_commands
        ],
        "recent_exchange_events": [dict(row) for row in recent_events],
    }


def _recent_market_alerts(limit: int = 10) -> List[Dict[str, Any]]:
    try:
        from app.services.volatility_alert_service import get_recent_persisted_alerts

        return get_recent_persisted_alerts(limit=limit, hours=24)
    except Exception as e:
        return [{"error": f"{type(e).__name__}: {e}"}]


def get_live_health() -> Dict[str, Any]:
    mode = get_current_mode()

    price_feed = _safe_stats(
        lambda: __import__("app.services.price_feed", fromlist=["get_price_feed"]).get_price_feed().get_stats(),
        {},
    )
    user_stream = _safe_stats(
        lambda: __import__("app.services.binance_user_stream_service", fromlist=["get_user_stream"]).get_user_stream().get_stats(),
        {},
    )
    db = _safe_stats(_db_snapshot, {})
    market_alerts = _recent_market_alerts(limit=10)

    issues = []
    warnings = []

    if mode != TradingMode.PAPER:
        if not price_feed.get("healthy"):
            issues.append("price_feed_unhealthy")
        if not user_stream.get("connected"):
            issues.append("user_stream_disconnected")

    if db.get("missing_protection_count", 0) > 0:
        issues.append("missing_protection")
    if db.get("stale_pending_count", 0) > 0:
        warnings.append("stale_pending")
    if db.get("exchange_close_unknown_count", 0) > 0:
        warnings.append("exchange_close_unknown_exists")
    if user_stream.get("last_error"):
        warnings.append("user_stream_last_error")
    if price_feed.get("last_error"):
        warnings.append("price_feed_last_error")

    if issues:
        status = "unhealthy"
    elif warnings:
        status = "degraded"
    else:
        status = "healthy"

    return {
        "ok": status != "unhealthy",
        "status": status,
        "mode": mode.value,
        "checked_at": utc_now(),
        "issues": issues,
        "warnings": warnings,
        "price_feed": price_feed,
        "user_stream": user_stream,
        "database": db,
        "market_alerts": market_alerts,
    }
