"""
Profit Lock Switch
==================
Auto close tất cả positions khi tổng PnL thực tế >= threshold.

PnL tính theo % thực tế (KHÔNG tính leverage):
  LONG:  pnl_pct = (current - entry) / entry * 100
  SHORT: pnl_pct = (entry - current) / entry * 100
  Tổng = sum of all OPEN trades
"""

from datetime import datetime, timedelta
from typing import Optional, Dict

from app.core.time_utils import utc_now
from app.db.session import SessionLocal
from app.db.models import Signal


_DEFAULT_CONFIG = {
    "enabled": False,
    "threshold_pct": 20,
    "min_open_trades": 3,
    "cooldown_minutes": 60,
}

_last_trigger_at: Optional[datetime] = None


def _get_config() -> dict:
    try:
        from app.services.config_service import get_runtime_config
        cfg = get_runtime_config()
        return cfg.get("PROFIT_LOCK_CONFIG", _DEFAULT_CONFIG)
    except Exception:
        return _DEFAULT_CONFIG


def check_profit_lock_condition(price_map: dict) -> bool:
    """
    Check xem có nên trigger Profit Lock không.
    Returns True nếu cần trigger.
    """
    global _last_trigger_at

    cfg = _get_config()
    if not cfg.get("enabled", False):
        return False

    threshold_pct = float(cfg.get("threshold_pct", 20))
    min_open = int(cfg.get("min_open_trades", 3))
    cooldown_min = int(cfg.get("cooldown_minutes", 60))

    if _last_trigger_at:
        elapsed = (utc_now() - _last_trigger_at).total_seconds() / 60
        if elapsed < cooldown_min:
            return False

    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(Signal.status == "OPEN").all()

        if len(open_trades) < min_open:
            return False

        total_pnl_pct = 0.0

        for trade in open_trades:
            entry = float(trade.entry_price or 0)
            if entry <= 0:
                continue

            current = price_map.get(trade.symbol)
            if current is None:
                continue

            current = float(current)

            if trade.direction == "LONG":
                pnl_pct = ((current - entry) / entry) * 100
            else:
                pnl_pct = ((entry - current) / entry) * 100

            total_pnl_pct += pnl_pct

        if total_pnl_pct >= threshold_pct:
            print(
                f"🎯 [PROFIT LOCK] Trigger! "
                f"total_pnl={total_pnl_pct:.2f}% >= threshold={threshold_pct}% "
                f"| {len(open_trades)} trades"
            )
            return True

    return False


def mark_triggered():
    global _last_trigger_at
    _last_trigger_at = utc_now()