"""
Live Advisory Monitor
=====================
Chạy theo loop riêng, KHÔNG phụ thuộc price callback.

Vai trò:
1. Profit Protection trigger (breakeven)
2. Anomaly detection (optional, mở rộng sau)

QUAN TRỌNG:
- Chỉ phát hiện điều kiện + request command
- KHÔNG tự finalize signal
- KHÔNG tự close trade
"""

from typing import Optional, Dict

from app.db.session import SessionLocal
from app.db.models import Signal
from app.services.live.protection_service import (
    is_protection_enabled,
    check_breakeven_condition,
)
from app.services.live.command_service import request_protection_replace
from app.services.live.locks import live_symbol_lock


def run_advisory_cycle(price_map: Optional[Dict[str, float]] = None):
    """
    Main entry point cho advisory monitor.
    Gọi từ live_advisory_loop.
    """
    if not price_map:
        try:
            from app.services.price_feed import get_all_current_prices
            price_map = get_all_current_prices()
        except Exception:
            price_map = {}

    if not price_map:
        return

    if not is_protection_enabled():
        return

    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(
            Signal.status == "OPEN"
        ).all()

        if not open_trades:
            return

        for trade in open_trades:
            try:
                _check_trade_advisory(trade, price_map)
            except Exception as e:
                print(f"[ADVISORY] {trade.symbol}: {type(e).__name__}: {e}")


def _check_trade_advisory(trade: Signal, price_map: dict):
    current = price_map.get(trade.symbol)
    if current is None:
        return

    current = float(current)

    should_trigger, new_sl = check_breakeven_condition(trade, current)

    if not should_trigger or new_sl is None:
        return

    with live_symbol_lock(trade.symbol, blocking=False) as acquired:
        if not acquired:
            return

        print(
            f"🛡️ [ADVISORY] {trade.symbol} hit breakeven trigger "
            f"| current={current:.4f} new_sl={new_sl:.4f}"
        )

        result = request_protection_replace(
            signal_id=trade.id,
            new_sl_price=float(new_sl),
        )

        if result.get("success") and not result.get("deduped"):
            print(
                f"📝 [ADVISORY] Breakeven replace requested: "
                f"{trade.symbol} | signal_id={trade.id} | new_sl={new_sl:.4f}"
            )