"""
Profit Protection Service — LIVE
================================
Percent-based protection levels, đọc config từ DB (app_config).

Roles:
- Tính điều kiện trigger protection level
- Quản lý state markers trong market_context
- KHÔNG trực tiếp cancel/place exchange
- Protection replace thực thi theo 2-phase trong reconciler

Config key: PROTECTION_LEVELS_CONFIG
Format:
{
    "enabled": true,
    "timeframes": {
        "15m": {
            "levels": [
                {"trigger_pct": 0.02, "action": "move_to_entry", "buffer_pct": 0.002},
                {"trigger_pct": 0.04, "action": "move_stop_to_profit_pct", "target_profit_pct": 0.015}
            ]
        },
        "1h": { "levels": [...] },
        "4h": { "levels": [...] }
    }
}
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.db.models import Signal
from app.core.time_utils import utc_now, ensure_utc


# ── Fallback config nếu DB chưa có ──────────────────────────

_DEFAULT_PROTECTION = {
    "enabled": True,
    "timeframes": {
        "15m": {"levels": [
            {"trigger_pct": 0.02, "action": "move_to_entry", "buffer_pct": 0.002},
        ]},
        "1h": {"levels": [
            {"trigger_pct": 0.025, "action": "move_to_entry", "buffer_pct": 0.0025},
        ]},
        "4h": {"levels": [
            {"trigger_pct": 0.03, "action": "move_to_entry", "buffer_pct": 0.003},
        ]},
    }
}

# NOTE:
# hardcode tạm cho live ổn định trước
BREAKEVEN_RETRY_BACKOFF_SECONDS = 30
PROTECTION_CHANGE_COOLDOWN_SECONDS = 15


# ============================================================
# CONFIG LOADER
# ============================================================

def _get_protection_config() -> dict:
    """
    Đọc PROTECTION_LEVELS_CONFIG từ DB.
    Fallback về default nếu chưa có.
    """
    try:
        from app.services.config_service import get_runtime_config
        cfg = get_runtime_config()
        return cfg.get("PROTECTION_LEVELS_CONFIG", _DEFAULT_PROTECTION)
    except Exception:
        return _DEFAULT_PROTECTION


def is_protection_enabled() -> bool:
    return _get_protection_config().get("enabled", True)


# ============================================================
# BREAKEVEN / PROTECTION CONDITION CHECK (percent-based)
# ============================================================

def check_breakeven_condition(
    trade: Signal,
    current_price: float,
) -> Tuple[bool, Optional[float]]:
    """
    Percent-based multi-level protection check.

    Kiểm tra tất cả levels chưa apply của timeframe tương ứng.
    Trả về level cao nhất đã đạt trigger mà chưa apply.

    Returns:
        (should_trigger, new_sl_price)
    """
    ctx = trade.market_context or {}
    applied_levels = ctx.get("protection_levels_applied", [])

    cfg = _get_protection_config()
    if not cfg.get("enabled", True):
        return False, None

    # Backoff check
    next_retry_at = ctx.get("breakeven_next_retry_at")
    if next_retry_at:
        try:
            retry_dt = ensure_utc(datetime.fromisoformat(next_retry_at))
            if retry_dt > utc_now():
                return False, None
        except Exception:
            pass

    entry = float(trade.entry_price or 0)
    if entry <= 0:
        return False, None

    tf = trade.timeframe or "1h"
    tf_cfg = cfg.get("timeframes", {}).get(tf, {})
    levels = tf_cfg.get("levels", [])

    if not levels:
        return False, None

    # Sort ascending theo trigger_pct
    levels = sorted(levels, key=lambda x: float(x.get("trigger_pct", 0) or 0))

    # Current profit % (không tính leverage)
    if trade.direction == "LONG":
        current_profit_pct = (current_price - entry) / entry
    else:
        current_profit_pct = (entry - current_price) / entry

    # Tìm level cao nhất chưa apply mà đã đạt trigger
    best_level = None
    for lv in levels:
        trigger_pct = float(lv.get("trigger_pct", 0) or 0)
        level_key = f"{lv.get('action')}_{trigger_pct}"

        if level_key in applied_levels:
            continue

        if current_profit_pct >= trigger_pct:
            best_level = lv

    if not best_level:
        return False, None

    # Compute new SL price
    action = best_level.get("action", "move_to_entry")

    if action == "move_to_entry":
        buffer_pct_cfg = best_level.get("buffer_pct", 0.002)
        if isinstance(buffer_pct_cfg, dict):
            buffer_pct = float(buffer_pct_cfg.get(tf, 0.002) or 0.002)
        else:
            buffer_pct = float(buffer_pct_cfg or 0.002)

        if trade.direction == "LONG":
            new_sl = entry * (1 + buffer_pct)
        else:
            new_sl = entry * (1 - buffer_pct)

    elif action == "move_stop_to_profit_pct":
        target_profit_pct = float(best_level.get("target_profit_pct", 0) or 0)
        if trade.direction == "LONG":
            new_sl = entry * (1 + target_profit_pct)
        else:
            new_sl = entry * (1 - target_profit_pct)

    else:
        return False, None

    # Guard: SL không được vượt giá hiện tại
    if trade.direction == "LONG" and new_sl >= current_price:
        return False, None
    if trade.direction == "SHORT" and new_sl <= current_price:
        return False, None

    return True, new_sl


# ============================================================
# STATE MARKERS
# ============================================================

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
    Dùng để _ensure_protection() không auto-repair ngay trong cooldown.
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


def mark_breakeven_applied(
    trade: Signal,
    new_sl_price: float,
    new_sl_id: Optional[str] = None,
    level_key: Optional[str] = None,
):
    """
    Đánh dấu protection level đã được apply.
    Hỗ trợ multi-level: track từng level đã apply.
    """
    ctx = dict(trade.market_context or {})

    mark_protection_changed(
        trade=trade,
        sl_price=float(new_sl_price),
        sl_id=new_sl_id,
    )

    # Re-read ctx vì mark_protection_changed đã sửa
    ctx = dict(trade.market_context or {})
    ctx["breakeven_applied"] = True
    ctx["breakeven_sl"] = float(new_sl_price)
    ctx["breakeven_at"] = utc_now().isoformat()

    # Track which levels have been applied
    applied = ctx.get("protection_levels_applied", [])
    if level_key and level_key not in applied:
        applied.append(level_key)
    ctx["protection_levels_applied"] = applied

    ctx.pop("breakeven_last_error", None)
    ctx.pop("breakeven_last_attempt_at", None)
    ctx.pop("breakeven_next_retry_at", None)

    trade.market_context = ctx