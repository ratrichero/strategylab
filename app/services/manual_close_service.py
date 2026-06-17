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

    Yêu cầu:
    - LIVE/TESTNET: phải verify order trên exchange thực sự đã không còn active
    - Chỉ khi verify OK mới update local status
    """
    mode = get_current_mode()

    with SessionLocal() as db:
        from app.services.execution_service import (
            cancel_entry_and_exits,
            get_entry_order_status,
            get_open_orders,
            get_open_algo_orders,
        )
        from app.core.time_utils import utc_now

        p = db.query(PendingSignal).get(pending_id)

        if not p:
            return {"success": False, "error": f"Pending {pending_id} not found"}

        if p.status != "WAIT":
            return {"success": False, "error": f"Pending {pending_id} not WAIT (status={p.status})"}

        # PAPER mode: chỉ local cancel
        if mode == TradingMode.PAPER:
            p.status = "CANCELLED"
            p.rejection_reason = "MANUAL_CANCEL"
            db.commit()
            return {
                "success": True,
                "pending_id": pending_id,
                "symbol": p.symbol,
                "final_status": p.status,
                "executed_qty": p.executed_qty,
                "mode": "PAPER",
            }

        # ── LIVE / TESTNET ──────────────────────────────────
        try:
            # 1) Gửi lệnh cancel
            cancel_entry_and_exits(p)

            # 2) Sync entry status cuối cùng
            info = get_entry_order_status(p.symbol, p.exchange_order_id)
            p.executed_qty = float(info.get("executed_qty") or p.executed_qty or 0)
            p.exchange_status = info.get("status", p.exchange_status)
            if info.get("avg_price"):
                p.avg_fill_price = float(info["avg_price"])
            p.last_exchange_sync_at = utc_now()

            # 3) Verify exchange side:
            #    entry order còn active không?
            entry_still_active = False
            algo_still_active = False

            # Verify normal orders
            try:
                normal_orders = get_open_orders(p.symbol)
                if p.exchange_order_id:
                    entry_still_active = any(
                        str(o.get("orderId")) == str(p.exchange_order_id)
                        for o in (normal_orders or [])
                    )
            except Exception:
                normal_orders = []

            # Verify algo orders
            try:
                algo_orders = get_open_algo_orders(p.symbol)
                algo_ids = {str(p.sl_order_id or ""), str(p.tp_order_id or "")}
                algo_still_active = any(
                    str(o.get("algoId")) in algo_ids
                    for o in (algo_orders or [])
                )
            except Exception:
                algo_orders = []

            # 4) Nếu entry vẫn active -> cancel thất bại
            if entry_still_active:
                db.rollback()
                return {
                    "success": False,
                    "error": f"Exchange entry order still active for {p.symbol}. Cancel not confirmed.",
                    "pending_id": pending_id,
                    "symbol": p.symbol,
                    "exchange_status": p.exchange_status,
                }

            # 5) Nếu đã có fill thì pending kết thúc dưới dạng FILLED
            #    nếu chưa fill thì mới là CANCELLED
            if (p.executed_qty or 0) > 0:
                p.status = "FILLED"
                p.rejection_reason = "MANUAL_CANCEL"
            else:
                p.status = "CANCELLED"
                p.rejection_reason = "MANUAL_CANCEL"

            db.commit()

            return {
                "success": True,
                "pending_id": pending_id,
                "symbol": p.symbol,
                "final_status": p.status,
                "executed_qty": p.executed_qty,
                "exchange_status": p.exchange_status,
                "algo_still_active": algo_still_active,
                "mode": mode.value,
            }

        except Exception as e:
            db.rollback()
            return {
                "success": False,
                "error": f"Cancel error: {type(e).__name__}: {e}"
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