"""
Backtest Replay — Signal Loader
=================================
Load signals thật từ DB để replay.
"""

from datetime import datetime
from typing import List, Dict, Any

from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from app.core.time_utils import ensure_utc


def load_closed_signals(
    date_from: datetime,
    date_to: datetime,
    timeframes: List[str],
    symbols: List[str],
    strategies: List[str],
    limit: int = 500,
    include_manual: bool = False,
) -> List[Dict[str, Any]]:
    """
    Load signals đã đóng (WIN/LOSS/MANUAL) trong khoảng thời gian chỉ định.
    Resolve entry_time từ pending.filled_at hoặc fallback signals.created_at.
    """
    date_from = ensure_utc(date_from)
    date_to = ensure_utc(date_to)

    results = []

    with SessionLocal() as db:
        allowed_statuses = ["WIN", "LOSS"]
        if include_manual:
            allowed_statuses.append("MANUAL")

        query = db.query(Signal).filter(
            Signal.status.in_(allowed_statuses),
            Signal.created_at >= date_from,
            Signal.created_at <= date_to,
        )

        if timeframes:
            query = query.filter(Signal.timeframe.in_(timeframes))

        if symbols:
            query = query.filter(Signal.symbol.in_(symbols))

        if strategies:
            query = query.filter(Signal.strategy_name.in_(strategies))

        query = query.order_by(Signal.created_at.asc()).limit(limit)

        signals = query.all()

        for sig in signals:
            entry_time = _resolve_entry_time(db, sig)

            entry_price = float(sig.entry_price or 0)
            stop_loss = float(sig.stop_loss or 0)

            if entry_price <= 0 or stop_loss <= 0:
                continue

            r_value = abs(entry_price - stop_loss)
            if r_value <= 0:
                continue

            if sig.direction == "LONG":
                tp_2r = entry_price + 2 * r_value
            else:
                tp_2r = entry_price - 2 * r_value

            results.append({
                "signal_id": sig.id,
                "symbol": sig.symbol,
                "timeframe": sig.timeframe,
                "strategy_name": sig.strategy_name,
                "pattern": sig.pattern,
                "direction": sig.direction,
                "entry_time": entry_time.isoformat(),
                "entry_price": entry_price,
                "initial_stop_loss": stop_loss,
                "tp_2r_price": round(tp_2r, 8),
                "r_value_abs": round(r_value, 8),
                "actual_exit_time": sig.exit_time.isoformat() if sig.exit_time else None,
                "actual_exit_price": float(sig.exit_price) if sig.exit_price else None,
                "actual_exit_reason": sig.exit_reason,
                "actual_status": sig.status,
                "actual_result_pct": float(sig.result_percent) if sig.result_percent else None,
            })

    return results


def _resolve_entry_time(db, signal: Signal) -> datetime:
    """
    Ưu tiên pending.filled_at, fallback signals.created_at.
    """
    pending = db.query(PendingSignal).filter(
        PendingSignal.signal_id == signal.id
    ).order_by(PendingSignal.created_at.desc()).first()

    if pending and pending.filled_at:
        return ensure_utc(pending.filled_at)

    return ensure_utc(signal.created_at)