"""
Manual Close Service
====================
- Manual close 1 signal OPEN
- Manual cancel 1 pending WAIT
"""

from typing import Optional, Dict

from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from app.services.trade_close_service import close_trade
from app.core.trading_mode import get_current_mode, TradingMode


def manual_close_signal(signal_id: int) -> Dict:
    """
    Đóng 1 signal OPEN bằng tay.
    close_trade() sẽ lo:
    - close position
    - sync pending
    - cleanup exits + remainder
    - outcome
    - telegram
    """
    with SessionLocal() as db:
        trade = db.query(Signal).get(signal_id)

        if not trade:
            return {"success": False, "error": f"Signal {signal_id} not found"}

        if trade.status != "OPEN":
            return {"success": False, "error": f"Signal {signal_id} not OPEN (status={trade.status})"}

        current_price = _get_current_price(trade.symbol)
        if current_price is None:
            return {"success": False, "error": f"Cannot get price for {trade.symbol}"}

        try:
            close_trade(db, trade, current_price, "MANUAL")
            db.commit()

            return {
                "success":        True,
                "signal_id":      signal_id,
                "symbol":         trade.symbol,
                "direction":      trade.direction,
                "exit_price":     float(trade.exit_price) if trade.exit_price else None,
                "result_percent": float(trade.result_percent or 0),
                "status":         trade.status,
            }

        except Exception as e:
            db.rollback()
            return {"success": False, "error": f"Close error: {type(e).__name__}: {e}"}


def manual_cancel_pending(pending_id: int) -> Dict:
    """
    Cancel 1 pending WAIT bằng tay.
    LIVE/TESTNET: cancel exchange orders nếu có.
    """
    mode = get_current_mode()

    with SessionLocal() as db:
        from app.services.execution_service import (
            cancel_entry_and_exits,
            get_entry_order_status,
        )
        from app.core.time_utils import utc_now

        p = db.query(PendingSignal).get(pending_id)

        if not p:
            return {"success": False, "error": f"Pending {pending_id} not found"}

        if p.status != "WAIT":
            return {"success": False, "error": f"Pending {pending_id} not WAIT (status={p.status})"}

        # LIVE/TESTNET: cancel exchange orders
        if mode != TradingMode.PAPER and p.exchange_order_id:
            try:
                cancel_entry_and_exits(p)

                info = get_entry_order_status(p.symbol, p.exchange_order_id)
                p.executed_qty = float(info.get("executed_qty") or p.executed_qty or 0)
                p.exchange_status = info.get("status", p.exchange_status)
                if info.get("avg_price"):
                    p.avg_fill_price = float(info["avg_price"])
                p.last_exchange_sync_at = utc_now()
            except Exception as e:
                print(f"[MANUAL CANCEL] Exchange cleanup error: {e}")

        # Chốt local status
        if (p.executed_qty or 0) > 0:
            p.status = "FILLED"
            p.rejection_reason = "MANUAL_CANCEL"
        else:
            p.status = "CANCELLED"
            p.rejection_reason = "MANUAL_CANCEL"

        db.commit()

        return {
            "success":      True,
            "pending_id":   pending_id,
            "symbol":       p.symbol,
            "final_status": p.status,
            "executed_qty": p.executed_qty,
        }


def _get_current_price(symbol: str) -> Optional[float]:
    try:
        from app.services.price_feed import get_current_price
        price = get_current_price(symbol)
        if price is not None:
            return float(price)
    except Exception:
        pass

    try:
        from app.services.binance_service import get_all_prices
        return float(get_all_prices().get(symbol, 0)) or None
    except Exception:
        return None