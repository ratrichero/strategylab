"""
Profit Protection Service — LIVE
================================
Advisory-only:
- tính điều kiện breakeven
- quản lý backoff retry state trong market_context

IMPORTANT:
- KHÔNG trực tiếp cancel/place exchange ở đây nữa
- Protection replace thực thi theo 2-phase trong reconciler
- Advisory chỉ request command
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.db.models import Signal
from app.core.time_utils import utc_now, ensure_utc


PROFIT_PROTECTION_CONFIG = {
    "enabled": True,
    "mode": "breakeven",
    "trigger_r": {
        "15m": 1.0,
        "1h": 1.0,
        "4h": 1.0,
    },
    "buffer_pct": {
        "15m": 0.002,
        "1h": 0.0025,
        "4h": 0.003,
    },
    "once_only": True,
}

# NOTE:
# hardcode tạm cho live ổn định trước
BREAKEVEN_RETRY_BACKOFF_SECONDS = 30
PROTECTION_CHANGE_COOLDOWN_SECONDS = 15


def is_protection_enabled() -> bool:
    return PROFIT_PROTECTION_CONFIG.get("enabled", False)


def set_breakeven_retry_backoff(trade: Signal, reason: str, seconds: int = BREAKEVEN_RETRY_BACKOFF_SECONDS):
    ctx = dict(trade.market_context or {})
    ctx["breakeven_last_error"] = reason
    ctx["breakeven_last_attempt_at"] = utc_now().isoformat()
    ctx["breakeven_next_retry_at"] = (
        utc_now() + timedelta(seconds=seconds)
    ).isoformat()
    trade.market_context = ctx


def clear_breakeven_retry_backoff(trade: Signal):
    ctx = dict(trade.market_context or {})
    ctx.pop("breakeven_last_error", None)
    ctx.pop("breakeven_last_attempt_at", None)
    ctx.pop("breakeven_next_retry_at", None)
    trade.market_context = ctx


def mark_protection_changed(
    trade: Signal,
    sl_price: Optional[float] = None,
    sl_id: Optional[str] = None,
):
    """
    Đánh dấu vừa có thay đổi protection.
    Dùng để _ensure_protection() không auto-repair ngay trong vài giây tiếp theo,
    tránh race cùng cycle / stale snapshot.
    """
    ctx = dict(trade.market_context or {})
    exec_ctx = dict(ctx.get("execution") or {})

    if sl_id:
        exec_ctx["sl_order_id"] = sl_id
        ctx["protection_change_sl_id"] = sl_id

    if sl_price is not None:
        ctx["protection_change_sl_price"] = float(sl_price)

    ctx["execution"] = exec_ctx
    ctx["protection_change_at"] = utc_now().isoformat()
    trade.market_context = ctx


def protection_change_cooldown_active(
    trade: Signal,
    seconds: int = PROTECTION_CHANGE_COOLDOWN_SECONDS
) -> bool:
    ctx = trade.market_context or {}
    ts = ctx.get("protection_change_at")
    if not ts:
        return False

    try:
        changed_at = ensure_utc(datetime.fromisoformat(ts))
        age = (utc_now() - changed_at).total_seconds()
        return age < seconds
    except Exception:
        return False


def mark_breakeven_applied(trade: Signal, new_sl_price: float, new_sl_id: Optional[str] = None):
    ctx = dict(trade.market_context or {})

    mark_protection_changed(
        trade=trade,
        sl_price=float(new_sl_price),
        sl_id=new_sl_id,
    )

    ctx = dict(trade.market_context or {})
    ctx["breakeven_applied"] = True
    ctx["breakeven_sl"] = float(new_sl_price)
    ctx["breakeven_at"] = utc_now().isoformat()

    ctx.pop("breakeven_last_error", None)
    ctx.pop("breakeven_last_attempt_at", None)
    ctx.pop("breakeven_next_retry_at", None)

    trade.market_context = ctx


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

    # Nếu đã dời rồi và config yêu cầu once_only
    if ctx.get("breakeven_applied") and PROFIT_PROTECTION_CONFIG.get("once_only", True):
        return False, None

    # Nếu đang trong backoff retry
    next_retry_at = ctx.get("breakeven_next_retry_at")
    if next_retry_at:
        try:
            retry_dt = ensure_utc(datetime.fromisoformat(next_retry_at))
            if retry_dt > utc_now():
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

    trigger_r = PROFIT_PROTECTION_CONFIG.get("trigger_r", {}).get(tf, 1.0)
    if current_r < trigger_r:
        return False, None

    buffer_pct = PROFIT_PROTECTION_CONFIG.get("buffer_pct", {}).get(tf, 0.001)

    if trade.direction == "LONG":
        new_sl = entry * (1 + buffer_pct)
    else:
        new_sl = entry * (1 - buffer_pct)

    # Bảo vệ không đặt SL vượt qua giá hiện tại
    if trade.direction == "LONG" and new_sl >= current_price:
        return False, None
    if trade.direction == "SHORT" and new_sl <= current_price:
        return False, None

    return True, new_sl