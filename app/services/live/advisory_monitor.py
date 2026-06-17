"""
Live Advisory Monitor
=====================
Chạy theo loop riêng, KHÔNG phụ thuộc price callback.

Vai trò:
1. Profit Protection trigger (breakeven)
2. Anomaly detection (optional, mở rộng sau)

QUAN TRỌNG:
- Chỉ phát hiện điều kiện + phát command
- KHÔNG tự finalize signal
- KHÔNG tự close trade
"""

from typing import Optional, Dict

from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from app.services.live.protection_service import (
    is_protection_enabled,
    check_breakeven_condition,
    execute_protection_replace,
)
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
                _check_trade_advisory(db, trade, price_map)
            except Exception as e:
                db.rollback()
                print(f"[ADVISORY] {trade.symbol}: {type(e).__name__}: {e}")

        db.commit()


def _check_trade_advisory(db, trade: Signal, price_map: dict):
    """
    Check 1 trade cho profit protection.
    """
    current = price_map.get(trade.symbol)
    if current is None:
        return

    current = float(current)

    # ── Breakeven check ──────────────────────────────────
    should_trigger, new_sl = check_breakeven_condition(trade, current)

    if not should_trigger or new_sl is None:
        return

    # Lấy lock symbol để tránh đụng reconciler
    with live_symbol_lock(trade.symbol, blocking=False) as acquired:
        if not acquired:
            # Reconciler đang xử lý symbol này, bỏ qua lần này
            return

        # Tìm pending liên kết
        pending = db.query(PendingSignal).filter(
            PendingSignal.signal_id == trade.id
        ).order_by(PendingSignal.created_at.desc()).first()

        print(
            f"🛡️ [ADVISORY] {trade.symbol} hit breakeven trigger "
            f"| current={current:.4f} new_sl={new_sl:.4f}"
        )

        success = execute_protection_replace(
            db=db,
            trade=trade,
            pending=pending,
            new_sl_price=new_sl,
        )

        if success:
            # Notify
            try:
                from app.services.telegram_service import send_telegram
                send_telegram(
                    f"🛡️ <b>BREAKEVEN APPLIED</b>\n\n"
                    f"<b>Symbol:</b> {trade.symbol}\n"
                    f"<b>Direction:</b> {trade.direction}\n"
                    f"<b>Entry:</b> {float(trade.entry_price):.4f}\n"
                    f"<b>New SL:</b> {new_sl:.4f}\n"
                    f"<b>Current:</b> {current:.4f}"
                )
            except Exception:
                pass