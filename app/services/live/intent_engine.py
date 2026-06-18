"""
LIVE Intent Engine
==================
Xử lý phase E0:
- pending WAIT
- exchange_order_id IS NULL

HOTFIX v1:
- Retry policy cố ý hardcode để chặn retry vô hạn trên LIVE
- Sau khi live ổn định sẽ chuyển policy này sang app_config / spec động

Policy hiện tại:
- deterministic fail -> reject ngay
- transient fail -> retry tối đa 1 lần
- backoff giữa các lần thử = 10 giây

HARD-CAP HOTFIX:
- MAX_OPEN_TRADES được hiểu là hard-cap exposure thực tế
- Count theo DISTINCT active live symbols:
    + OPEN signals
    + placed WAIT pendings chưa terminal
- Nếu đã đầy cap -> không place thêm
"""

from datetime import timedelta

from sqlalchemy import and_, or_

from app.core.time_utils import utc_now, ensure_utc
from app.db.session import SessionLocal
from app.db.models import PendingSignal
from app.services.config_service import get_runtime_config
from app.services.prefill_validator import validate_before_fill
from app.services.open_trade_filter import get_open_trade_filter
from app.services.execution_service import (
    place_limit_entry_order,
    get_executor,
)
from app.services.live.locks import live_symbol_lock
from app.services.live.capacity_service import get_active_live_symbol_count
from app.services.price_feed import get_all_current_prices


# ============================================================
# HARD-CODED RETRY POLICY (HOTFIX v1)
# NOTE:
# - Intent retry hiện cố ý hardcode
# - Sau khi live ổn định sẽ chuyển sang app_config / spec động
# ============================================================

MAX_PLACE_RETRIES = 1
RETRY_BACKOFF_SECONDS = 10


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
    p.last_place_error = error_msg

    # deterministic = reject ngay
    if _is_deterministic_error(error_msg):
        _reject_place_failure(db, p, error_msg)
        return

    max_total_attempts = 1 + MAX_PLACE_RETRIES
    attempts = int(p.place_attempt_count or 0)

    # nếu đã hết quota retry -> reject
    if attempts >= max_total_attempts:
        p.status = "REJECTED"
        p.rejection_reason = f"ENTRY_FAIL_RETRY_EXHAUSTED::{error_msg}"
        p.next_retry_at = None
        db.commit()

        print(
            f"🚫 LIVE ENTRY RETRY EXHAUSTED: {p.symbol} {p.direction} "
            f"| pending={p.id} attempts={attempts}/{max_total_attempts} "
            f"| error={error_msg}"
        )
        return

    # transient fail -> schedule retry
    p.next_retry_at = now + timedelta(seconds=RETRY_BACKOFF_SECONDS)
    db.commit()

    print(
        f"⚠️ LIVE ENTRY TRANSIENT FAIL: {p.symbol} {p.direction} "
        f"| pending={p.id} attempts={attempts}/{max_total_attempts} "
        f"| retry_at={p.next_retry_at.isoformat()} "
        f"| error={error_msg}"
    )


def process_live_pending_intents():
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

        if p.exchange_order_id:
            db.commit()
            return

        if p.next_retry_at and ensure_utc(p.next_retry_at) > now:
            db.commit()
            return

        if ensure_utc(p.expire_at) < now:
            p.status = "CANCELLED"
            p.rejection_reason = "EXPIRED_BEFORE_PLACE"
            p.next_retry_at = None
            db.commit()
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

        # HARD-CAP gate #1: check sớm để tránh làm prefill/sizing vô ích
        max_open = int(cfg.get("MAX_OPEN_TRADES", 10) or 10)
        active_live_count = get_active_live_symbol_count(db)
        if active_live_count >= max_open:
            print(
                f"⛔ LIVE HARD CAP BLOCK: {p.symbol} {p.direction} "
                f"| pending={p.id} active_live={active_live_count}/{max_open}"
            )
            db.commit()
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
                # Không tự bind mù vì chưa có clientOrderId entry.
                # Tránh spin liên tục bằng backoff nhẹ.
                p.last_place_error = "DUPLICATE_OPEN_LIMIT_DETECTED"
                p.next_retry_at = now + timedelta(seconds=RETRY_BACKOFF_SECONDS)
                db.commit()

                print(
                    f"⚠️ LIVE ENTRY DUPLICATE GUARD: {p.symbol} {p.direction} "
                    f"| pending={p.id} retry_at={p.next_retry_at.isoformat()}"
                )
                return

        # HARD-CAP gate #2: check lại ngay trước khi place thật
        active_live_count = get_active_live_symbol_count(db)
        if active_live_count >= max_open:
            print(
                f"⛔ LIVE HARD CAP BLOCK BEFORE PLACE: {p.symbol} {p.direction} "
                f"| pending={p.id} active_live={active_live_count}/{max_open}"
            )
            db.commit()
            return

        # Từ đây mới tính là 1 place attempt thực sự
        _record_place_attempt(p, now)
        db.flush()

        exec_result = place_limit_entry_order(p)

        if not exec_result.success:
            error_msg = exec_result.error or "UNKNOWN_PLACE_ERROR"
            _schedule_place_retry_or_reject(db, p, error_msg, now)
            return

        p.exchange_order_id = exec_result.order_id
        p.exchange_status = "NEW"
        p.placed_at = now
        p.order_quantity = exec_result.actual_quantity
        p.last_exchange_sync_at = now

        # success -> clear retry control
        p.next_retry_at = None
        p.last_place_error = None

        db.commit()

        print(
            f"🟡 LIVE ENTRY PLACED: {p.symbol} {p.direction} "
            f"| pending={p.id} order_id={p.exchange_order_id} "
            f"| attempts={p.place_attempt_count}"
        )