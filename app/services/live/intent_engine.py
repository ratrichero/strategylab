"""
LIVE Intent Engine
==================
Xử lý phase E0:
- pending WAIT
- exchange_order_id IS NULL

HOTFIX:
- Retry policy hardcode để chặn retry vô hạn trên LIVE
- HARD CAP BLOCK dùng backoff để không spam loop/log

IMPORTANT:
- expire_at phải được check TRƯỚC next_retry_at
- place gate dùng capacity model:
    C_OPEN + C_NEW <= C_CONFIG + 2
  và block nếu:
    C_OPEN >= C_CONFIG
    OR
    C_OPEN + C_NEW >= C_CONFIG + 2
"""

from datetime import timedelta

from sqlalchemy import and_, or_

from app.core.time_utils import utc_now, ensure_utc
from app.db.session import SessionLocal
from app.db.models import ExecutionCommand, PendingSignal
from app.services.config_service import get_runtime_config
from app.services.prefill_validator import validate_before_fill
from app.services.open_trade_filter import get_open_trade_filter
from app.services.execution_service import (
    get_entry_order_by_client_id,
    place_limit_entry_order,
    get_executor,
)
from app.services.live.locks import live_symbol_lock
from app.services.live.capacity_service import (
    get_capacity_snapshot,
    get_capacity_snapshot_locked,
    should_block_new_entry,
)
from app.services.price_feed import get_all_current_prices
from app.services.retry_policy import get_retry_policy_service


MAX_PLACE_RETRIES = 1  # DEPRECATED: Use retry_policy service
RETRY_BACKOFF_SECONDS = 10  # DEPRECATED: Use retry_policy service
HARD_CAP_BLOCK_BACKOFF_SECONDS = 60
ENTRY_BLOCKING_COMMANDS = ("KILL_SWITCH", "PROFIT_LOCK")
OPEN_COMMAND_STATUSES = ("REQUESTED", "SENT")


DETERMINISTIC_ERRORS = [
    "SET_LEVERAGE_FAILED",
    "Qty too small",
    "Actual notional too small",
    "Low balance",
    "Margin is insufficient",
    "Leverage",
    "Exceeded the maximum allowable position at current leverage",
]


def _is_deterministic_error(error_msg: str) -> bool:
    if not error_msg:
        return False
    return any(pattern in error_msg for pattern in DETERMINISTIC_ERRORS)


def _calc_repriced_triplet(p: PendingSignal, reprice_pct: float):
    trigger_old = float(p.trigger_price)
    sl_old = float(p.stop_loss)
    tp_old = float(p.take_profit)

    if trigger_old <= 0:
        return trigger_old, sl_old, tp_old

    if p.direction == "LONG":
        sl_pct = abs((trigger_old - sl_old) / trigger_old)
        tp_pct = abs((tp_old - trigger_old) / trigger_old)
        trigger_new = trigger_old * (1 - reprice_pct)
        sl_new = trigger_new * (1 - sl_pct)
        tp_new = trigger_new * (1 + tp_pct)
    else:
        sl_pct = abs((sl_old - trigger_old) / trigger_old)
        tp_pct = abs((trigger_old - tp_old) / trigger_old)
        trigger_new = trigger_old * (1 + reprice_pct)
        sl_new = trigger_new * (1 + sl_pct)
        tp_new = trigger_new * (1 - tp_pct)

    return trigger_new, sl_new, tp_new


def _round_triplet_for_exchange(symbol, trigger_price, stop_loss, take_profit):
    executor = get_executor()
    if not executor or not executor.ready:
        return trigger_price, stop_loss, take_profit

    symbol_info = executor.get_symbol_info(symbol)
    if not symbol_info:
        return trigger_price, stop_loss, take_profit

    trigger_price = executor.round_price(symbol, trigger_price, symbol_info)
    stop_loss     = executor.round_price(symbol, stop_loss, symbol_info)
    take_profit   = executor.round_price(symbol, take_profit, symbol_info)

    return trigger_price, stop_loss, take_profit


def _lock_pending_row(db, pending_id: int) -> PendingSignal:
    return (
        db.query(PendingSignal)
        .filter(PendingSignal.id == pending_id)
        .with_for_update()
        .one()
    )


def _has_entry_blocking_command(db, symbol: str) -> bool:
    return db.query(ExecutionCommand.id).filter(
        ExecutionCommand.symbol == symbol,
        ExecutionCommand.command_type.in_(ENTRY_BLOCKING_COMMANDS),
        ExecutionCommand.status.in_(OPEN_COMMAND_STATUSES),
    ).first() is not None


def _entry_client_order_id(pending_id: int) -> str:
    return f"QRL_ENTRY_{pending_id}"[:36]


def _relink_existing_entry_order(db, p: PendingSignal, now) -> bool:
    client_order_id = p.client_order_id or _entry_client_order_id(p.id)
    order = get_entry_order_by_client_id(p.symbol, client_order_id)
    if not order:
        return False

    order_id = order.get("orderId")
    if not order_id:
        return False

    p.exchange_order_id = str(order_id)
    p.client_order_id = client_order_id
    p.exchange_status = str(order.get("status") or "UNKNOWN")
    p.placed_at = p.placed_at or now
    p.order_quantity = float(order.get("origQty", 0) or p.order_quantity or 0)
    p.executed_qty = float(order.get("executedQty", 0) or p.executed_qty or 0)
    avg_price = float(order.get("avgPrice", 0) or 0)
    if avg_price > 0:
        p.avg_fill_price = avg_price
    p.last_exchange_sync_at = now
    p.next_retry_at = None
    p.last_place_error = None
    db.commit()
    print(
        f"🔗 LIVE ENTRY RELINKED: {p.symbol} {p.direction} "
        f"| pending={p.id} order_id={p.exchange_order_id}"
    )
    return True


def _record_place_attempt(p: PendingSignal, now):
    p.place_attempt_count = int(p.place_attempt_count or 0) + 1
    p.last_place_attempt_at = now


def _reject_place_failure(db, p: PendingSignal, error_msg: str):
    p.status = "REJECTED"
    p.rejection_reason = f"ENTRY_FAIL::{error_msg}"
    p.last_place_error = error_msg
    p.next_retry_at = None
    db.commit()

    print(
        f"🚫 LIVE ENTRY REJECTED: {p.symbol} {p.direction} "
        f"| pending={p.id} attempts={p.place_attempt_count} "
        f"| error={error_msg}"
    )


def _schedule_place_retry_or_reject(db, p: PendingSignal, error_msg: str, now):
    """Use retry policy service để determine retry behavior."""
    retry_policy = get_retry_policy_service()
    
    # Failed attempt count already recorded for this pending.
    current_attempt = int(p.place_attempt_count or 0)
    
    # Get retry decision from policy service
    decision = retry_policy.should_retry(error_msg, current_attempt)
    
    p.last_place_error = error_msg
    
    if not decision.should_retry:
        # Reject the pending signal
        p.status = "REJECTED"
        p.rejection_reason = f"ENTRY_FAIL::{decision.error_type.upper()}::{error_msg}"
        p.next_retry_at = None
        db.commit()
        
        print(
            f"🚫 LIVE ENTRY REJECTED: {p.symbol} {p.direction} "
            f"| pending={p.id} attempts={decision.retry_count}/{decision.max_retries} "
            f"| error_type={decision.error_type} reason={decision.reason} "
            f"| error={error_msg}"
        )
        return
    
    # Schedule retry
    p.next_retry_at = decision.next_retry_at
    db.commit()
    
    print(
        f"⚠️ LIVE ENTRY RETRY SCHEDULED: {p.symbol} {p.direction} "
        f"| pending={p.id} attempts={decision.retry_count}/{decision.max_retries} "
        f"| retry_at={p.next_retry_at.isoformat()} "
        f"| error_type={decision.error_type} reason={decision.reason} "
        f"| error={error_msg}"
    )


def process_live_pending_intents():
    try:
        from app.core.app_role import is_bot
        if is_bot():
            from app.bot_runtime.runtime_gate import get_runtime_gate
            if get_runtime_gate().is_monitor_only():
                return
    except Exception:
        pass

    cfg = get_runtime_config(force_reload=True)
    price_map = get_all_current_prices() or {}
    now = utc_now()

    with SessionLocal() as db:
        pendings = db.query(PendingSignal).filter(
            and_(
                PendingSignal.status == "WAIT",
                PendingSignal.exchange_order_id == None,  # noqa: E711
                or_(
                    PendingSignal.next_retry_at == None,   # noqa: E711
                    PendingSignal.next_retry_at <= now
                )
            )
        ).order_by(PendingSignal.created_at.asc()).all()

    for p in pendings:
        with live_symbol_lock(p.symbol, blocking=False) as acquired:
            if not acquired:
                continue
            try:
                _process_one_pending_intent(p.id, price_map, cfg)
            except Exception as e:
                print(f"[LIVE INTENT] Pending {p.id}/{p.symbol}: {type(e).__name__}: {e}")


def _process_one_pending_intent(pending_id: int, price_map, cfg):
    now = utc_now()

    with SessionLocal() as db:
        p = _lock_pending_row(db, pending_id)

        if p.status != "WAIT":
            db.commit()
            return

        # Nếu đã có order trên exchange thì intent phase hết quyền
        if p.exchange_order_id:
            db.commit()
            return

        # QUAN TRỌNG: expire phải check trước retry gate
        if _has_entry_blocking_command(db, p.symbol):
            p.status = "CANCELLED"
            p.rejection_reason = "ENTRY_BLOCKED_BY_LIVE_COMMAND"
            p.next_retry_at = None
            db.commit()
            return

        if ensure_utc(p.expire_at) < now:
            p.status = "CANCELLED"
            p.rejection_reason = "EXPIRED_BEFORE_PLACE"
            p.next_retry_at = None
            db.commit()
            return

        if p.next_retry_at and ensure_utc(p.next_retry_at) > now:
            db.commit()
            return

        if _relink_existing_entry_order(db, p, now):
            return

        otf = get_open_trade_filter(cfg.get("OPEN_TRADE_FILTER"))
        atr_ratio = None
        if p.atr_value and p.trigger_price and float(p.trigger_price) > 0:
            atr_ratio = float(p.atr_value) / float(p.trigger_price)

        otf_ok, otf_reason = otf.check(
            symbol=p.symbol,
            direction=p.direction,
            strategy_name=p.strategy_name,
            pattern=p.pattern,
            timeframe=p.timeframe,
            regime=p.regime,
            score=p.signal_score or 0,
            ml_prob=p.ml_prob,
            components={
                "trend_score": p.trend_score or 0,
                "momentum_score": p.momentum_score or 0,
                "volume_score": p.volume_score or 0,
                "pattern_score": p.pattern_score or 0,
                "mtf_score": p.mtf_score or 0,
                "penalty_norm": p.penalty or 0,
            },
            atr_ratio=atr_ratio,
            db=db,
            exclude_pending_id=p.id,
        )
        if not otf_ok:
            db.commit()
            return

        max_open = int(cfg.get("MAX_OPEN_TRADES", 10) or 10)
        # Serialize capacity placement checks with a PostgreSQL advisory lock.
        cap = get_capacity_snapshot_locked(db, max_open)

        if should_block_new_entry(cap):
            p.last_place_error = "HARD_CAP_BLOCK"
            p.next_retry_at = now + timedelta(seconds=HARD_CAP_BLOCK_BACKOFF_SECONDS)
            db.commit()

            """print(
                f"⛔ LIVE HARD CAP BLOCK: {p.symbol} {p.direction} "
                f"| pending={p.id} open={cap.c_open} new={cap.c_new} "
                f"| total={cap.total_risk}/{cap.max_risk} "
                f"| retry_at={p.next_retry_at.isoformat()}"
            )"""
            return

        current = price_map.get(p.symbol)
        if current is None:
            db.commit()
            return

        result = validate_before_fill(p, float(current))
        if not result.passed:
            p.status = "REJECTED"
            p.rejection_reason = result.reason
            p.validation_details = result.details
            p.next_retry_at = None
            db.commit()
            return

        if not getattr(p, "reprice_applied", False):
            limit_cfg = cfg.get("LIMIT_ORDER_CONFIG", {})
            if not limit_cfg.get("enabled", True):
                reprice_pct = 0.0
            else:
                reprice_pct = (
                    limit_cfg.get("entry_reprice_pct", {}).get(p.timeframe, 0.0) or 0.0
                )

            trig_new, sl_new, tp_new = _calc_repriced_triplet(p, reprice_pct)
            trig_new, sl_new, tp_new = _round_triplet_for_exchange(
                p.symbol, trig_new, sl_new, tp_new
            )

            p.trigger_price = trig_new
            p.stop_loss = sl_new
            p.take_profit = tp_new
            p.reprice_applied = True
            db.flush()

        executor = get_executor()
        if executor and executor.ready:
            existing_normal = executor.get_open_orders(p.symbol)
            expected_side = "BUY" if p.direction == "LONG" else "SELL"
            has_live_entry = any(
                str(o.get("type", "")).upper() == "LIMIT"
                and str(o.get("side", "")).upper() == expected_side
                for o in (existing_normal or [])
            )
            if has_live_entry:
                p.last_place_error = "DUPLICATE_OPEN_LIMIT_DETECTED"
                # Increment attempt count for duplicate guard
                _record_place_attempt(p, now)
                
                # Use retry policy for duplicate guard as well
                retry_policy = get_retry_policy_service()
                decision = retry_policy.should_retry("DUPLICATE_OPEN_LIMIT_DETECTED", int(p.place_attempt_count or 0))
                
                if decision.should_retry:
                    p.next_retry_at = decision.next_retry_at
                    db.commit()
                    print(
                        f"⚠️ LIVE ENTRY DUPLICATE GUARD: {p.symbol} {p.direction} "
                        f"| pending={p.id} retry_at={p.next_retry_at.isoformat()}"
                    )
                else:
                    # Reject when retry exhausted
                    p.status = "REJECTED"
                    p.rejection_reason = f"DUPLICATE_GUARD_RETRY_EXHAUSTED::attempts={decision.retry_count}"
                    p.next_retry_at = None
                    db.commit()
                    print(
                        f"🚫 LIVE ENTRY DUPLICATE GUARD REJECTED: {p.symbol} {p.direction} "
                        f"| pending={p.id} attempts={decision.retry_count}"
                    )
                return

        # Removed duplicate capacity check - now using single atomic check above
        _record_place_attempt(p, now)
        db.flush()

        exec_result = place_limit_entry_order(p)

        if not exec_result.success:
            error_msg = exec_result.error or "UNKNOWN_PLACE_ERROR"
            _schedule_place_retry_or_reject(db, p, error_msg, now)
            return

        # Record success for circuit breaker
        retry_policy = get_retry_policy_service()
        retry_policy.record_success()

        p.exchange_order_id = exec_result.order_id
        p.client_order_id = exec_result.client_order_id or _entry_client_order_id(p.id)
        p.exchange_status = "NEW"
        p.placed_at = now
        p.order_quantity = exec_result.actual_quantity
        p.last_exchange_sync_at = now

        p.next_retry_at = None
        p.last_place_error = None

        db.commit()

        print(
            f"🟡 LIVE ENTRY PLACED: {p.symbol} {p.direction} "
            f"| pending={p.id} order_id={p.exchange_order_id} "
            f"| attempts={p.place_attempt_count}"
        )
