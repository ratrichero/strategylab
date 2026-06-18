"""
Profit Protection Service — LIVE
=================================
Advisory-only: phát hiện điều kiện + thực thi replace SL.
Không tự finalize signal.

HOTFIX:
- Không emergency close ngay khi replace SL fail kiểu ambiguous/recoverable
- Ưu tiên:
    1) kiểm tra xem exchange còn STOP active không
    2) nếu không còn STOP, thử restore lại old SL
    3) chỉ emergency close nếu thật sự không còn bảo vệ

NOTE:
- Retry/backoff hiện hardcode để ổn định live trước
- Sau khi ổn định sẽ chuyển sang config/spec động
"""

from datetime import timedelta
from typing import Optional, Dict, Tuple

from app.db.models import Signal, PendingSignal
from app.services.execution_service import (
    cancel_order_by_id,
    place_algo_stop_market_close_position,
    get_executor,
    get_open_algo_orders,
    get_algo_order_status,
)
from app.services.live.command_service import request_emergency_close
from app.core.time_utils import utc_now, ensure_utc


# ── Config (hardcode tạm, audit sau) ────────────────────────

PROFIT_PROTECTION_CONFIG = {
    "enabled": True,
    "mode": "breakeven",
    "trigger_r": {
        "15m": 1.0,
        "1h": 1.0,
        "4h": 1.0,
    },
    "buffer_pct": {
        "15m": 0.001,
        "1h": 0.0015,
        "4h": 0.002,
    },
    "once_only": True,
}

# HOTFIX hardcode
BREAKEVEN_RETRY_BACKOFF_SECONDS = 30


def is_protection_enabled() -> bool:
    return PROFIT_PROTECTION_CONFIG.get("enabled", False)


# ============================================================
# CHECK CONDITION
# ============================================================

def check_breakeven_condition(
    trade: Signal,
    current_price: float,
) -> Tuple[bool, Optional[float]]:
    """
    Kiểm tra xem giá đã chạy đủ R để dời SL về Break-even chưa.

    Returns:
        (should_trigger, new_sl_price)
    """
    ctx = trade.market_context or {}

    # Đã dời rồi và config yêu cầu once_only
    if ctx.get("breakeven_applied") and PROFIT_PROTECTION_CONFIG.get("once_only", True):
        return False, None

    # HOTFIX: nếu đang trong backoff retry, bỏ qua
    next_retry_at = ctx.get("breakeven_next_retry_at")
    if next_retry_at:
        try:
            if ensure_utc(__import__("datetime").datetime.fromisoformat(next_retry_at)) > utc_now():
                return False, None
        except Exception:
            pass

    entry = float(trade.entry_price or 0)
    original_sl = float(trade.stop_loss or 0)
    tf = trade.timeframe or "1h"

    if entry <= 0 or original_sl <= 0:
        return False, None

    # Khoảng cách 1R gốc
    r_distance = abs(entry - original_sl)
    if r_distance == 0:
        return False, None

    # R hiện tại
    if trade.direction == "LONG":
        current_r = (current_price - entry) / r_distance
    else:
        current_r = (entry - current_price) / r_distance

    # Ngưỡng kích hoạt
    trigger_r = PROFIT_PROTECTION_CONFIG.get("trigger_r", {}).get(tf, 1.0)

    if current_r < trigger_r:
        return False, None

    # Tính giá SL mới
    buffer_pct = PROFIT_PROTECTION_CONFIG.get("buffer_pct", {}).get(tf, 0.001)

    if trade.direction == "LONG":
        new_sl = entry * (1 + buffer_pct)
    else:
        new_sl = entry * (1 - buffer_pct)

    # Ngăn chặn dời SL ngược hoặc khi giá đang ở sai vị trí
    if trade.direction == "LONG" and new_sl >= current_price:
        return False, None
    if trade.direction == "SHORT" and new_sl <= current_price:
        return False, None

    return True, new_sl


# ============================================================
# HELPERS
# ============================================================

def _set_retry_backoff(trade: Signal, reason: str):
    ctx = dict(trade.market_context or {})
    ctx["breakeven_last_error"] = reason
    ctx["breakeven_last_attempt_at"] = utc_now().isoformat()
    ctx["breakeven_next_retry_at"] = (
        utc_now() + timedelta(seconds=BREAKEVEN_RETRY_BACKOFF_SECONDS)
    ).isoformat()
    trade.market_context = ctx


def _clear_retry_backoff(trade: Signal):
    ctx = dict(trade.market_context or {})
    ctx.pop("breakeven_last_error", None)
    ctx.pop("breakeven_last_attempt_at", None)
    ctx.pop("breakeven_next_retry_at", None)
    trade.market_context = ctx


def _find_open_stop_algo(symbol: str):
    open_algos = get_open_algo_orders(symbol) or []
    for o in open_algos:
        if str(o.get("orderType", "")).upper() == "STOP_MARKET":
            return o
    return None


def _find_open_tp_algo(symbol: str):
    open_algos = get_open_algo_orders(symbol) or []
    for o in open_algos:
        if str(o.get("orderType", "")).upper() == "TAKE_PROFIT_MARKET":
            return o
    return None


def _is_recoverable_duplicate_error(error_text: str) -> bool:
    if not error_text:
        return False
    txt = str(error_text)
    return (
        "-4130" in txt
        or "closePosition in the direction is existing" in txt
        or "open stop or take profit order" in txt
    )


def _sync_existing_protection_ids(pending: Optional[PendingSignal], symbol: str):
    if not pending:
        return

    sl = _find_open_stop_algo(symbol)
    tp = _find_open_tp_algo(symbol)

    if sl:
        pending.sl_order_id = str(sl.get("algoId", "")) or pending.sl_order_id
    if tp:
        pending.tp_order_id = str(tp.get("algoId", "")) or pending.tp_order_id


# ============================================================
# EXECUTE REPLACE
# ============================================================

def execute_protection_replace(
    db,
    trade: Signal,
    pending: Optional[PendingSignal],
    new_sl_price: float,
) -> bool:
    """
    Thực hiện replace SL trên exchange.

    Success:
        - cancel old SL
        - place new SL
        - update pending.sl_order_id
        - update trade.stop_loss
        - mark breakeven_applied

    Recoverable fail:
        - nếu exchange vẫn còn STOP active -> KHÔNG emergency close
        - nếu không còn STOP, thử restore old SL
        - nếu restore old SL thành công -> KHÔNG emergency close
        - set retry backoff

    Fatal fail:
        - nếu không còn STOP active và restore old SL cũng fail
        - gửi EMERGENCY_CLOSE command

    Returns:
        True nếu replace thành công
    """
    executor = get_executor()
    if not executor or not executor.ready:
        print(f"⚠️ [PROTECTION] Executor not ready for {trade.symbol}")
        _handle_replace_failure(db, trade, pending, "EXECUTOR_NOT_READY", try_restore=False)
        return False

    symbol = trade.symbol
    direction = trade.direction

    ctx = dict(trade.market_context or {})
    ctx["breakeven_last_attempt_at"] = utc_now().isoformat()
    trade.market_context = ctx

    old_sl_price = float(trade.stop_loss or 0)

    old_sl_id = None
    if pending:
        old_sl_id = pending.sl_order_id

    if not old_sl_id:
        exec_ctx = ctx.get("execution") or {}
        old_sl_id = exec_ctx.get("sl_order_id")

    # 1) Cancel old SL (best-effort)
    if old_sl_id:
        cancel_order_by_id(symbol, old_sl_id)
        print(f"🗑️ [PROTECTION] Cancelled old SL: {old_sl_id}")

    # 2) Place new SL
    symbol_info = executor.get_symbol_info(symbol)
    rounded_new_sl = executor.round_price(symbol, new_sl_price, symbol_info)

    try:
        new_sl_order = place_algo_stop_market_close_position(
            symbol=symbol,
            direction=direction,
            trigger_price=rounded_new_sl,
        )

        new_sl_id = str(new_sl_order.get("algoId", "")) if new_sl_order else None

        if not new_sl_id:
            print(f"❌ [PROTECTION] Place new SL returned no algoId for {symbol}")
            _handle_replace_failure(
                db, trade, pending,
                "PLACE_NEW_SL_NO_ID",
                try_restore=True,
                old_sl_price=old_sl_price
            )
            return False

    except Exception as e:
        err = f"PLACE_NEW_SL_ERROR::{e}"
        print(f"❌ [PROTECTION] Place new SL error {symbol}: {e}")
        _handle_replace_failure(
            db, trade, pending,
            err,
            try_restore=True,
            old_sl_price=old_sl_price
        )
        return False

    # 3) Success: update DB
    trade.stop_loss = rounded_new_sl

    exec_ctx = dict((trade.market_context or {}).get("execution") or {})
    exec_ctx["sl_order_id"] = new_sl_id

    ctx = dict(trade.market_context or {})
    ctx["execution"] = exec_ctx
    ctx["breakeven_applied"] = True
    ctx["breakeven_sl"] = rounded_new_sl
    ctx["breakeven_at"] = utc_now().isoformat()
    trade.market_context = ctx

    _clear_retry_backoff(trade)

    if pending:
        pending.sl_order_id = new_sl_id
        pending.stop_loss = rounded_new_sl

    db.flush()

    print(
        f"✅ [PROTECTION] Breakeven applied: {symbol} "
        f"| new_sl={rounded_new_sl} algo_id={new_sl_id}"
    )

    return True


def _handle_replace_failure(
    db,
    trade: Signal,
    pending: Optional[PendingSignal],
    reason: str,
    try_restore: bool = False,
    old_sl_price: Optional[float] = None,
):
    """
    Khi replace SL thất bại:
    1) Sync protection xem exchange còn STOP active không
    2) Nếu còn STOP active -> chỉ backoff retry, KHÔNG emergency close
    3) Nếu không còn STOP và được phép -> thử restore old SL
    4) Nếu restore fail -> emergency close
    """
    symbol = trade.symbol
    direction = trade.direction

    # Sync IDs từ exchange trước
    _sync_existing_protection_ids(pending, symbol)

    open_stop = _find_open_stop_algo(symbol)
    if open_stop:
        if pending:
            pending.sl_order_id = str(open_stop.get("algoId", "")) or pending.sl_order_id
        _set_retry_backoff(trade, reason)
        db.flush()

        print(
            f"⚠️ [PROTECTION] Replace failed but STOP still active => retry later {symbol} | {reason}"
        )
        return

    # Nếu old_sl_id còn query được trạng thái active thì cũng coi là vẫn protected
    old_sl_id = pending.sl_order_id if pending else None
    if old_sl_id:
        try:
            old_state = get_algo_order_status(old_sl_id)
            old_status = str(old_state.get("algo_status", "")).upper()
            if old_status in ("NEW", "WORKING", "PENDING"):
                _set_retry_backoff(trade, reason)
                db.flush()

                print(
                    f"⚠️ [PROTECTION] Replace failed but old SL status still active => retry later {symbol} | {reason}"
                )
                return
        except Exception:
            pass

    # Thử restore old SL nếu không còn STOP active
    if try_restore and old_sl_price and old_sl_price > 0:
        executor = get_executor()
        if executor and executor.ready:
            try:
                symbol_info = executor.get_symbol_info(symbol)
                rounded_old_sl = executor.round_price(symbol, old_sl_price, symbol_info)

                restored = place_algo_stop_market_close_position(
                    symbol=symbol,
                    direction=direction,
                    trigger_price=rounded_old_sl,
                )
                restored_id = str(restored.get("algoId", "")) if restored else None

                if restored_id:
                    if pending:
                        pending.sl_order_id = restored_id
                    trade.stop_loss = rounded_old_sl
                    _set_retry_backoff(trade, f"RESTORED_OLD_SL::{reason}")
                    db.flush()

                    print(
                        f"♻️ [PROTECTION] Restored old SL after replace fail: {symbol} "
                        f"| sl={rounded_old_sl} algo_id={restored_id}"
                    )
                    return

            except Exception as e:
                print(f"❌ [PROTECTION] Restore old SL failed {symbol}: {e}")

    # Chỉ tới đây mới emergency close
    print(f"🚨 [PROTECTION] Replace failed => EMERGENCY_CLOSE {symbol} | {reason}")

    request_emergency_close(
        symbol=symbol,
        signal_id=trade.id,
        pending_id=pending.id if pending else None,
        reason=f"PROTECTION_REPLACE_FAILED::{reason}",
    )