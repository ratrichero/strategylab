"""
Trade Monitor — Event-driven SL/TP check & Profit Protection (Break-Even)
"""

from typing import Dict, Optional
from app.db.session import SessionLocal
from app.db.models import Signal
from app.services.trade_close_service import close_trade, apply_profit_protection
from app.core.trading_mode import get_current_mode, TradingMode

# --- CẤU HÌNH HARDCODE CHO PROFIT PROTECTION ---
PROFIT_PROTECTION_CONFIG = {
    "enabled": True,
    "mode": "breakeven",
    "trigger_r": {
        "15m": 1.0,
        "1h": 1.0,
        "4h": 1.0
    },
    "buffer_pct": {
        "15m": 0.001,
        "1h": 0.0015,
        "4h": 0.002
    },
    "once_only": True
}
# -----------------------------------------------

def monitor_open_trades(price_map: Optional[Dict[str, float]] = None):
    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(Signal.status == "OPEN").all()
        if not open_trades:
            return

        if not price_map:
            try:
                from app.services.price_feed import get_all_current_prices
                price_map = get_all_current_prices()
            except Exception:
                price_map = {}

        if not price_map:
            return

        mode = get_current_mode()

        for trade in open_trades:
            try:
                if mode == TradingMode.PAPER:
                    _check_paper(db, trade, price_map)
                else:
                    _check_live_testnet(db, trade, price_map, mode)
            except Exception as e:
                db.rollback()
                print(f"❌ Monitor [{trade.id}] {trade.symbol}: {type(e).__name__} - {e}")

        db.commit()


def _check_paper(db, trade, price_map):
    current = price_map.get(trade.symbol)
    if current is None:
        return

    current = float(current)
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


def _check_live_testnet(db, trade, price_map, mode):
    from app.services.execution_service import check_position_closed

    current = price_map.get(trade.symbol)
    if current is None:
        return
    current = float(current)

    # 1) Position đã bị exchange đóng rồi?
    if check_position_closed(trade):
        reason, exit_price = _infer_exchange_close_reason(trade, current)
        close_trade(db, trade, exit_price, reason)
        print(f"[LIVE SYNC] {trade.symbol} {trade.direction} {reason} @ {exit_price:.4f}")
        return

    # 2) Kiểm tra Break-even / Profit Protection
    if PROFIT_PROTECTION_CONFIG.get("enabled", False):
        _check_profit_protection(db, trade, current)

    # 3) Safety net
    _check_live_safety_net(db, trade, current)


def _check_profit_protection(db, trade, current_price: float):
    """
    Kiểm tra xem giá đã chạy đủ R để dời SL về Break-even chưa.
    """
    ctx = trade.market_context or {}
    # Nếu đã dời SL rồi và config yêu cầu once_only -> bỏ qua
    if ctx.get("breakeven_applied") and PROFIT_PROTECTION_CONFIG.get("once_only", True):
        return

    entry = float(trade.entry_price)
    original_sl = float(trade.stop_loss)
    tf = trade.timeframe

    if entry <= 0 or original_sl <= 0:
        return

    # Tính khoảng cách 1R gốc
    r_distance = abs(entry - original_sl)
    if r_distance == 0:
        return

    # Tính R hiện tại đang đạt được
    if trade.direction == "LONG":
        current_r = (current_price - entry) / r_distance
    else:
        current_r = (entry - current_price) / r_distance

    # Lấy ngưỡng kích hoạt từ config
    trigger_r = PROFIT_PROTECTION_CONFIG.get("trigger_r", {}).get(tf, 1.0)
    
    # Nếu giá chạy đạt mốc R yêu cầu -> Tiến hành dời SL
    if current_r >= trigger_r:
        buffer_pct = PROFIT_PROTECTION_CONFIG.get("buffer_pct", {}).get(tf, 0.001)
        
        # Tính giá SL mới (Hòa vốn + phí/buffer)
        if trade.direction == "LONG":
            new_sl = entry * (1 + buffer_pct)
        else:
            new_sl = entry * (1 - buffer_pct)
        
        # Ngăn chặn việc dời SL ngược hoặc dời khi giá đang ở sai vị trí
        if trade.direction == "LONG" and new_sl >= current_price:
            return
        if trade.direction == "SHORT" and new_sl <= current_price:
            return

        print(f"🛡️ [PROFIT PROTECTION] {trade.symbol} hit {current_r:.2f}R. Moving SL to Break-even.")
        
        # Gọi sang Trade Close Service để xử lý dời lệnh trên sàn
        success = apply_profit_protection(db, trade, new_sl)
        
        # Đánh dấu đã dời vào market_context
        if success:
            ctx["breakeven_applied"] = True
            trade.market_context = ctx
            db.commit()


def _infer_exchange_close_reason(trade, current_price: float):
    sl = float(trade.stop_loss)
    tp = float(trade.take_profit)
    current = float(current_price)

    sl_tol = 0.01   # 1%
    tp_tol = 0.01   # 1%

    if trade.direction == "LONG":
        if current <= sl * (1 + sl_tol): return "SL", sl
        elif current >= tp * (1 - tp_tol): return "TP", tp
        else: return "BINANCE_CLOSE", current
    else:
        if current >= sl * (1 - sl_tol): return "SL", sl
        elif current <= tp * (1 + tp_tol): return "TP", tp
        else: return "BINANCE_CLOSE", current


def _check_live_safety_net(db, trade, current: float):
    sl = float(trade.stop_loss)
    if trade.direction == "LONG":
        if current <= sl * 0.995:
            print(f"⚠️ [LIVE SAFETY] {trade.symbol} LONG below SL deeply, force close")
            close_trade(db, trade, current, "SL_SAFETY")
    else:
        if current >= sl * 1.005:
            print(f"⚠️ [LIVE SAFETY] {trade.symbol} SHORT above SL deeply, force close")
            close_trade(db, trade, current, "SL_SAFETY")