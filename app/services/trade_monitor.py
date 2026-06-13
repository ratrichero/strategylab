"""
Trade Monitor — Event-driven SL/TP check
Paper:   check price from feed, simulate close
Live:    Binance handles SL/TP orders, but we also monitor
         for position sync and edge cases
"""
from typing import Dict, Optional
from app.db.session import SessionLocal
from app.db.models import Signal
from app.services.trade_close_service import close_trade
from app.core.trading_mode import get_current_mode, TradingMode


def monitor_open_trades(price_map: Optional[Dict[str, float]] = None):
    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(Signal.status == "OPEN").all()
        if not open_trades: return

        if not price_map:
            from app.services.price_feed import get_all_current_prices
            price_map = get_all_current_prices()
        if not price_map: return

        mode = get_current_mode()

        for trade in open_trades:
            try:
                if mode == TradingMode.PAPER:
                    _check_paper(db, trade, price_map)
                else:
                    _check_live(db, trade, price_map, mode)
            except Exception as e:
                db.rollback()
                print(f"❌ Monitor [{trade.id}] {trade.symbol}: {e}")

        db.commit()


def _check_paper(db, trade, price_map):
    """Paper mode: check price vs SL/TP manually."""

    current = price_map.get(trade.symbol)
    if current is None: return

    sl = float(trade.stop_loss)
    tp = float(trade.take_profit)

    if trade.direction == "LONG":
        hit_sl = current <= sl
        hit_tp = current >= tp
    else:
        hit_sl = current >= sl
        hit_tp = current <= tp

    if hit_sl:
        close_trade(db, trade, sl, "SL")
        print(f"[PAPER CLOSE] {trade.symbol} {trade.direction} SL @ {sl:.4f}")
    elif hit_tp:
        close_trade(db, trade, tp, "TP")
        print(f"[PAPER CLOSE] {trade.symbol} {trade.direction} TP @ {tp:.4f}")


def _check_live(db, trade, price_map, mode):
    """
    Live mode: Binance handles SL/TP via conditional orders.
    Monitor syncs position status.
    
    Cases to handle:
    1. Binance SL/TP triggered → position gone → close in DB
    2. Position still open → check if we need manual close
    3. Orphan orders → cleanup
    """

    from app.services.execution_service import check_position_closed, sync_position

    # Check if Binance position is already closed
    # (SL/TP triggered on exchange)
    if check_position_closed(trade):
        current = price_map.get(trade.symbol)
        if current is None: return

        # Determine reason from price
        sl = float(trade.stop_loss)
        tp = float(trade.take_profit)

        if trade.direction == "LONG":
            if current <= sl * 1.01:
                reason = "SL"
                exit_price = sl
            elif current >= tp * 0.99:
                reason = "TP"
                exit_price = tp
            else:
                reason = "BINANCE_CLOSE"
                exit_price = current
        else:
            if current >= sl * 0.99:
                reason = "SL"
                exit_price = sl
            elif current <= tp * 1.01:
                reason = "TP"
                exit_price = tp
            else:
                reason = "BINANCE_CLOSE"
                exit_price = current

        close_trade(db, trade, exit_price, reason)
        print(f"[LIVE SYNC] {trade.symbol} {trade.direction} {reason} @ {exit_price:.4f}")
        return

    # Position still open — also do price check as safety net
    current = price_map.get(trade.symbol)
    if current is None: return

    sl = float(trade.stop_loss)
    tp = float(trade.take_profit)

    if trade.direction == "LONG":
        # If price is way past SL and Binance hasn't triggered
        if current <= sl * 0.99:
            print(f"⚠️ [LIVE SAFETY] {trade.symbol} SL should have triggered")
            close_trade(db, trade, current, "SL_SAFETY")
    else:
        if current >= sl * 1.01:
            print(f"⚠️ [LIVE SAFETY] {trade.symbol} SL should have triggered")
            close_trade(db, trade, current, "SL_SAFETY")
