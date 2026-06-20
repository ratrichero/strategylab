"""
Backtest Replay — Signal Loader
=================================
Load signals thật từ DB để replay.

IMPORTANT:
- initial_stop_loss và initial_take_profit phải lấy từ pending_signals
  vì signals.stop_loss có thể đã bị protection replace mutate.
- Nếu không có pending link, fallback signals.stop_loss nhưng đánh dấu.
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
    directions: List[str] = None,
    patterns: List[str] = None,
    regimes: List[str] = None,
    limit: int = 500,
    include_manual: bool = False,
) -> List[Dict[str, Any]]:
    """
    Load signals đã đóng (WIN/LOSS/MANUAL).
    Resolve:
    - entry_time từ pending.filled_at hoặc fallback signals.created_at
    - initial_stop_loss từ pending.stop_loss gốc (trước protection mutate)
    - initial_take_profit từ pending.take_profit gốc
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

        if directions:
            query = query.filter(Signal.direction.in_(directions))
        if patterns:
            query = query.filter(Signal.pattern.in_(patterns))
        if regimes:
            query = query.filter(Signal.regime.in_(regimes))

        query = query.order_by(Signal.created_at.asc()).limit(limit)

        signals = query.all()

        for sig in signals:
            entry_time, initial_sl, initial_tp, sl_source = _resolve_initial_params(db, sig)

            entry_price = float(sig.entry_price or 0)

            if entry_price <= 0 or initial_sl <= 0:
                continue

            r_value = abs(entry_price - initial_sl)
            if r_value <= 0:
                continue

            # Validate: initial stop phải ở phía risk đúng
            if sig.direction == "LONG" and initial_sl >= entry_price:
                continue
            if sig.direction == "SHORT" and initial_sl <= entry_price:
                continue

            if sig.direction == "LONG":
                tp_2r = entry_price + 2 * r_value
            else:
                tp_2r = entry_price - 2 * r_value

            # Nếu có TP gốc từ pending thì dùng, không thì tính từ R
            if initial_tp and initial_tp > 0:
                tp_2r = initial_tp

            results.append({
                "signal_id": sig.id,
                "symbol": sig.symbol,
                "timeframe": sig.timeframe,
                "strategy_name": sig.strategy_name,
                "pattern": sig.pattern,
                "direction": sig.direction,
                "entry_time": entry_time.isoformat(),
                "entry_price": entry_price,
                "initial_stop_loss": round(initial_sl, 8),
                "tp_2r_price": round(tp_2r, 8),
                "r_value_abs": round(r_value, 8),
                "sl_source": sl_source,
                "actual_exit_time": sig.exit_time.isoformat() if sig.exit_time else None,
                "actual_exit_price": float(sig.exit_price) if sig.exit_price else None,
                "actual_exit_reason": sig.exit_reason,
                "actual_status": sig.status,
                "actual_result_pct": float(sig.result_percent) if sig.result_percent else None,
            })

    return results


def _resolve_initial_params(db, signal: Signal):
    """
    Resolve:
    1. entry_time: pending.filled_at > signals.created_at
    2. initial_stop_loss: pending gốc (chưa bị protection mutate)
    3. initial_take_profit: pending gốc
    4. sl_source: "pending" hoặc "signal_fallback"

    IMPORTANT:
    - signals.stop_loss có thể đã bị dời bởi protection replace
    - pending_signals giữ giá trị ban đầu (hoặc sau reprice nhưng trước protection)
    """
    pending = db.query(PendingSignal).filter(
        PendingSignal.signal_id == signal.id
    ).order_by(PendingSignal.created_at.desc()).first()

    # Entry time
    if pending and pending.filled_at:
        entry_time = ensure_utc(pending.filled_at)
    else:
        entry_time = ensure_utc(signal.created_at)

    # Initial stop/tp từ pending
    if pending:
        # Lấy từ pending — đây là giá trị trước protection replace
        # Vì protection replace chỉ sửa signals.stop_loss, không sửa pending.stop_loss gốc
        #
        # NHƯNG: nếu pending.stop_loss cũng đã bị code cũ update
        # thì ta cần check thêm
        pending_sl = float(pending.stop_loss or 0)
        pending_tp = float(pending.take_profit or 0)
        entry_price = float(signal.entry_price or 0)

        # Validate pending stop ở phía risk đúng
        if signal.direction == "LONG" and pending_sl > 0 and pending_sl < entry_price:
            return entry_time, pending_sl, pending_tp, "pending"

        if signal.direction == "SHORT" and pending_sl > 0 and pending_sl > entry_price:
            return entry_time, pending_sl, pending_tp, "pending"

        # Nếu pending stop cũng đã mutate (hiếm), thử tìm từ market_context
        ctx = signal.market_context or {}
        plan = ctx.get("plan", {})
        plan_sl = float(plan.get("initial_stop_loss", 0) or 0)
        plan_tp = float(plan.get("initial_take_profit", 0) or 0)

        if plan_sl > 0:
            return entry_time, plan_sl, plan_tp, "market_context_plan"

        # Cuối cùng fallback pending dù sai
        if pending_sl > 0:
            return entry_time, pending_sl, pending_tp, "pending_unvalidated"

    # Fallback signal (có thể sai nếu đã bị protection mutate)
    sig_sl = float(signal.stop_loss or 0)
    sig_tp = float(signal.take_profit or 0)

    return entry_time, sig_sl, sig_tp, "signal_fallback"