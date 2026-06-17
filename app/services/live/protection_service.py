"""
Profit Protection Service — LIVE
=================================
Advisory-only: phát hiện điều kiện + thực thi replace SL.
Nếu replace fail → gửi EMERGENCY_CLOSE command.
Không tự finalize signal.

Hiện tại hỗ trợ:
- mode: breakeven (dời SL về entry + buffer khi đạt trigger_r)

Mở rộng sau:
- trailing stop
- multi-level take profit
"""

from typing import Optional, Dict, Tuple

from app.db.models import Signal, PendingSignal
from app.services.execution_service import (
    cancel_order_by_id,
    place_algo_stop_market_close_position,
    get_executor,
)
from app.services.live.command_service import (
    request_emergency_close,
    CMD_PROTECTION_REPLACE,
    COMMAND_REQUESTED,
    _create_command,
)
from app.core.time_utils import utc_now


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

    Fail:
        - gửi EMERGENCY_CLOSE command
        - return False

    Returns:
        True nếu replace thành công
    """
    executor = get_executor()
    if not executor or not executor.ready:
        print(f"⚠️ [PROTECTION] Executor not ready for {trade.symbol}")
        _handle_replace_failure(db, trade, pending, "EXECUTOR_NOT_READY")
        return False

    symbol = trade.symbol
    direction = trade.direction

    # 1) Cancel old SL
    old_sl_id = None
    if pending:
        old_sl_id = pending.sl_order_id

    if not old_sl_id:
        ctx = trade.market_context or {}
        exec_ctx = ctx.get("execution") or {}
        old_sl_id = exec_ctx.get("sl_order_id")

    if old_sl_id:
        cancel_order_by_id(symbol, old_sl_id)
        print(f"🗑️ [PROTECTION] Cancelled old SL: {old_sl_id}")

    # 2) Place new SL
    symbol_info = executor.get_symbol_info(symbol)
    rounded_sl = executor.round_price(symbol, new_sl_price, symbol_info)

    try:
        new_sl_order = place_algo_stop_market_close_position(
            symbol=symbol,
            direction=direction,
            trigger_price=rounded_sl,
        )

        new_sl_id = str(new_sl_order.get("algoId", "")) if new_sl_order else None

        if not new_sl_id:
            print(f"❌ [PROTECTION] Place new SL returned no algoId for {symbol}")
            _handle_replace_failure(db, trade, pending, "PLACE_NEW_SL_NO_ID")
            return False

    except Exception as e:
        print(f"❌ [PROTECTION] Place new SL error {symbol}: {e}")
        _handle_replace_failure(db, trade, pending, f"PLACE_NEW_SL_ERROR::{e}")
        return False

    # 3) Success: update DB
    trade.stop_loss = rounded_sl

    ctx = dict(trade.market_context or {})
    exec_ctx = dict(ctx.get("execution") or {})
    exec_ctx["sl_order_id"] = new_sl_id
    ctx["execution"] = exec_ctx
    ctx["breakeven_applied"] = True
    ctx["breakeven_sl"] = rounded_sl
    ctx["breakeven_at"] = utc_now().isoformat()
    trade.market_context = ctx

    if pending:
        pending.sl_order_id = new_sl_id
        pending.stop_loss = rounded_sl

    db.flush()

    print(
        f"✅ [PROTECTION] Breakeven applied: {symbol} "
        f"| new_sl={rounded_sl} algo_id={new_sl_id}"
    )

    return True


def _handle_replace_failure(db, trade, pending, reason: str):
    """
    Khi replace SL thất bại:
    Vị thế đang trần trụi không có SL.
    Phải gửi EMERGENCY_CLOSE command.
    """
    print(f"🚨 [PROTECTION] Replace failed => EMERGENCY_CLOSE {trade.symbol} | {reason}")

    request_emergency_close(
        symbol=trade.symbol,
        signal_id=trade.id,
        pending_id=pending.id if pending else None,
        reason=f"PROTECTION_REPLACE_FAILED::{reason}",
    )