"""
Trade Monitor — Event-driven SL/TP check

PAPER:
  - check price from feed
  - simulate close locally

LIVE / TESTNET:
  - Binance handles entry / TP / SL on exchange
  - monitor chỉ sync position status và xử lý edge cases
  - close_trade() sẽ lo cleanup remainder entry + sibling exits
"""

from typing import Dict, Optional

from app.db.session import SessionLocal
from app.db.models import Signal
from app.services.trade_close_service import close_trade
from app.core.trading_mode import get_current_mode, TradingMode


# ============================================================
# MAIN
# ============================================================

def monitor_open_trades(price_map: Optional[Dict[str, float]] = None):
    """
    Monitor all OPEN signals.

    PAPER:
      - local check current vs SL/TP

    LIVE / TESTNET:
      - sync exchange position status
      - nếu position gone -> close local signal
      - nếu position vẫn còn nhưng giá vượt sâu qua SL -> safety close
    """
    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(Signal.status == "OPEN").all()
        if not open_trades:
            return

        if not price_map:
            from app.services.price_feed import get_all_current_prices
            price_map = get_all_current_prices()

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


# ============================================================
# PAPER MODE
# ============================================================

def _check_paper(db, trade, price_map):
    """
    Paper mode: check current price vs SL/TP manually.
    """
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


# ============================================================
# LIVE / TESTNET MODE
# ============================================================

def _check_live_testnet(db, trade, price_map, mode):
    """
    LIVE / TESTNET monitor logic.

    LIFECYCLE MỚI:
    - pending_engine lo sync entry order / partial fill / create-update signal
    - trade_monitor chỉ nhìn signal OPEN + position thật trên exchange
    - khi position đóng xong:
        close_trade() sẽ lo reconcile pending, cleanup exits,
        cancel remainder entry nếu còn, finalize pending lifecycle
    """
    from app.services.execution_service import check_position_closed

    current = price_map.get(trade.symbol)
    if current is None:
        return
    current = float(current)

    # 1) Position đã bị exchange đóng rồi?
    #    (TP/SL/manual/external close)
    if check_position_closed(trade):
        reason, exit_price = _infer_exchange_close_reason(trade, current)
        close_trade(db, trade, exit_price, reason)
        print(
            f"[LIVE SYNC] {trade.symbol} {trade.direction} "
            f"{reason} @ {exit_price:.4f}"
        )
        return

    # 2) Position vẫn còn mở — safety net
    _check_live_safety_net(db, trade, current)


# ============================================================
# LIVE HELPERS
# ============================================================

def _infer_exchange_close_reason(trade, current_price: float):
    """
    Suy luận reason khi exchange position đã biến mất.

    Vì exchange có thể đã đóng bởi TP/SL, nhưng local chỉ nhìn thấy:
      - position size = 0
      - current price hiện tại
    Nên ta suy luận mềm:
      - gần SL => SL
      - gần TP => TP
      - còn lại => BINANCE_CLOSE
    """
    sl = float(trade.stop_loss)
    tp = float(trade.take_profit)
    current = float(current_price)

    # Tolerance mềm để bắt trường hợp giá đã chạy qua một chút
    # hoặc current snapshot đến chậm
    sl_tol = 0.01   # 1%
    tp_tol = 0.01   # 1%

    if trade.direction == "LONG":
        if current <= sl * (1 + sl_tol):
            return "SL", sl
        elif current >= tp * (1 - tp_tol):
            return "TP", tp
        else:
            return "BINANCE_CLOSE", current
    else:
        if current >= sl * (1 - sl_tol):
            return "SL", sl
        elif current <= tp * (1 + tp_tol):
            return "TP", tp
        else:
            return "BINANCE_CLOSE", current


def _check_live_safety_net(db, trade, current: float):
    """
    Safety net cho LIVE/TESTNET.

    Trong điều kiện bình thường:
      - Binance tự lo SL/TP
    Nhưng nếu vì lý do nào đó:
      - giá đã xuyên sâu qua SL
      - mà position vẫn chưa đóng
    thì bot sẽ chủ động close để bảo vệ tài khoản.

    Lưu ý:
      - close_trade() bên dưới sẽ gọi execution_service.close_position()
      - và sau đó cleanup remainder entry / pending lifecycle đúng rule mới
    """
    sl = float(trade.stop_loss)
    tp = float(trade.take_profit)

    if trade.direction == "LONG":
        # Safety close nếu giá đã đi sâu dưới SL mà Binance chưa close
        if current <= sl * 0.995:
            print(f"⚠️ [LIVE SAFETY] {trade.symbol} LONG below SL deeply, force close")
            close_trade(db, trade, current, "SL_SAFETY")
    else:
        if current >= sl * 1.005:
            print(f"⚠️ [LIVE SAFETY] {trade.symbol} SHORT above SL deeply, force close")
            close_trade(db, trade, current, "SL_SAFETY")