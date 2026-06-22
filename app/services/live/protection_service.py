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
"""

from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

from app.db.models import Signal
from app.core.time_utils import utc_now, ensure_utc
from app.services.retry_policy import get_retry_policy_service


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

BREAKEVEN_RETRY_BACKOFF_SECONDS = 30  # DEPRECATED: Use retry_policy service
PROTECTION_CHANGE_COOLDOWN_SECONDS = 15


# ============================================================
# CONFIG LOADER
# ============================================================

def _get_protection_config() -> dict:
    try:
        from app.services.config_service import get_runtime_config
        cfg = get_runtime_config()
        return cfg.get("PROTECTION_LEVELS_CONFIG", _DEFAULT_PROTECTION)
    except Exception:
        return _DEFAULT_PROTECTION


def is_protection_enabled() -> bool:
    return _get_protection_config().get("enabled", True)


# ============================================================
# LEVEL KEY
# ============================================================

def make_level_key(level_cfg: dict) -> str:
    """
    Stable key để track level đã apply.
    """
    action = str(level_cfg.get("action", "") or "")
    trigger_pct = float(level_cfg.get("trigger_pct", 0) or 0)

    if action == "move_to_entry":
        buffer_pct = float(level_cfg.get("buffer_pct", 0) or 0)
        return f"{action}|trigger={trigger_pct}|buffer={buffer_pct}"

    if action == "move_stop_to_profit_pct":
        target_profit_pct = float(level_cfg.get("target_profit_pct", 0) or 0)
        return f"{action}|trigger={trigger_pct}|target={target_profit_pct}"

    return f"{action}|trigger={trigger_pct}"


# ============================================================
# PROTECTION CONDITION CHECK
# ============================================================

def check_breakeven_condition(
    trade: Signal,
    current_price: float,
) -> Tuple[bool, Optional[float], Optional[str], Optional[Dict[str, Any]]]:
    """
    Percent-based multi-level protection check.

    Returns:
        (
          should_trigger: bool,
          new_sl_price: Optional[float],
          level_key: Optional[str],
          level_cfg: Optional[dict]
        )
    """
    ctx = trade.market_context or {}
    applied_levels = ctx.get("protection_levels_applied", [])

    cfg = _get_protection_config()
    if not cfg.get("enabled", True):
        return False, None, None, None

    next_retry_at = ctx.get("breakeven_next_retry_at")
    if next_retry_at:
        try:
            retry_dt = ensure_utc(datetime.fromisoformat(next_retry_at))
            if retry_dt > utc_now():
                return False, None, None, None
        except Exception:
            pass

    entry = float(trade.entry_price or 0)
    if entry <= 0:
        return False, None, None, None

    tf = trade.timeframe or "1h"
    tf_cfg = cfg.get("timeframes", {}).get(tf, {})
    levels = tf_cfg.get("levels", [])

    if not levels:
        return False, None, None, None

    levels = sorted(levels, key=lambda x: float(x.get("trigger_pct", 0) or 0))

    if trade.direction == "LONG":
        current_profit_pct = (current_price - entry) / entry
    else:
        current_profit_pct = (entry - current_price) / entry

    best_level = None
    best_level_key = None

    for lv in levels:
        trigger_pct = float(lv.get("trigger_pct", 0) or 0)
        level_key = make_level_key(lv)

        if level_key in applied_levels:
            continue

        if current_profit_pct >= trigger_pct:
            best_level = lv
            best_level_key = level_key

    if not best_level:
        return False, None, None, None

    action = best_level.get("action", "move_to_entry")

    if action == "move_to_entry":
        buffer_pct = float(best_level.get("buffer_pct", 0.002) or 0.002)
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
        return False, None, None, None

    if trade.direction == "LONG" and new_sl >= current_price:
        return False, None, None, None
    if trade.direction == "SHORT" and new_sl <= current_price:
        return False, None, None, None

    return True, new_sl, best_level_key, best_level


# ============================================================
# STATE MARKERS
# ============================================================

def set_breakeven_retry_backoff(trade: Signal, reason: str, seconds: Optional[int] = None):
    """
    Set retry backoff for breakeven protection.
    If seconds not provided, use retry policy service.
    """
    if seconds is None:
        # Use retry policy for backoff calculation
        retry_policy = get_retry_policy_service()
        decision = retry_policy.should_retry(reason or "PROTECTION_RETRY", 0)
        if decision.should_retry and decision.next_retry_at:
            backoff_seconds = (decision.next_retry_at - utc_now()).total_seconds()
        else:
            backoff_seconds = BREAKEVEN_RETRY_BACKOFF_SECONDS  # Fallback to default
    else:
        backoff_seconds = seconds
    
    ctx = dict(trade.market_context or {})
    ctx["breakeven_last_error"] = reason
    ctx["breakeven_last_attempt_at"] = utc_now().isoformat()
    ctx["breakeven_next_retry_at"] = (
        utc_now() + timedelta(seconds=backoff_seconds)
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
    """
    mark_protection_changed(
        trade=trade,
        sl_price=float(new_sl_price),
        sl_id=new_sl_id,
    )

    ctx = dict(trade.market_context or {})
    ctx["breakeven_applied"] = True
    ctx["breakeven_sl"] = float(new_sl_price)
    ctx["breakeven_at"] = utc_now().isoformat()

    applied = ctx.get("protection_levels_applied", [])
    if level_key and level_key not in applied:
        applied.append(level_key)
    ctx["protection_levels_applied"] = applied

    ctx.pop("breakeven_last_error", None)
    ctx.pop("breakeven_last_attempt_at", None)
    ctx.pop("breakeven_next_retry_at", None)

    trade.market_context = ctx