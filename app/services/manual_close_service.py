"""
Manual Close Service
====================
- Manual close 1 signal OPEN
- Manual cancel 1 pending WAIT

PAPER: giữ nguyên logic cũ
LIVE:  dùng live/command_service -> reconciler xác nhận
"""

from typing import Optional, Dict

from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from app.services.trade_close_service import close_trade
from app.core.trading_mode import get_current_mode, TradingMode


def manual_close_signal(signal_id: int) -> Dict:
    """
    Đóng 1 signal OPEN bằng tay.

    PAPER: close_trade() trực tiếp như cũ.
    LIVE:  gửi command, reconciler sẽ finalize.
    """
    mode = get_current_mode()

    if mode != TradingMode.PAPER:
        return _manual_close_signal_live(signal_id)

    return _manual_close_signal_paper(signal_id)


def manual_cancel_pending(pending_id: int) -> Dict:
    """
    Cancel 1 pending WAIT bằng tay.

    PAPER: local cancel trực tiếp.
    LIVE:  gửi command, reconciler sẽ finalize.
    """
    mode = get_current_mode()

    if mode != TradingMode.PAPER:
        return _manual_cancel_pending_live(pending_id)

    return _manual_cancel_pending_paper(pending_id)


# ============================================================
# PAPER — giữ nguyên behavior cũ
# ============================================================

def _manual_close_signal_paper(signal_id: int) -> Dict:
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


def _manual_cancel_pending_paper(pending_id: int) -> Dict:
    with SessionLocal() as db:
        p = db.query(PendingSignal).get(pending_id)

        if not p:
            return {"success": False, "error": f"Pending {pending_id} not found"}

        if p.status != "WAIT":
            return {"success": False, "error": f"Pending {pending_id} not WAIT (status={p.status})"}

        p.status = "CANCELLED"
        p.rejection_reason = "MANUAL_CANCEL"
        db.commit()

        return {
            "success":    True,
            "pending_id": pending_id,
            "symbol":     p.symbol,
            "status":     p.status,
            "mode":       "PAPER",
        }


# ============================================================
# LIVE — delegate to command_service
# ============================================================

def _manual_close_signal_live(signal_id: int) -> Dict:
    from app.services.live.command_service import request_manual_close
    return request_manual_close(signal_id)


def _manual_cancel_pending_live(pending_id: int) -> Dict:
    from app.services.live.command_service import request_manual_cancel_pending
    return request_manual_cancel_pending(pending_id)


# ============================================================
# HELPER
# ============================================================

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