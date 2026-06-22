"""Trade Close — Paper + Live/Testnet execution final"""

from app.core.time_utils import utc_now
from app.db.models import SignalFeature, PendingSignal
from app.services.outcome_service import save_trade_outcome
from app.services.btc_context_cache import (
    get_or_build_hourly_snapshot,
    build_event_context,
)
from app.core.trading_mode import get_current_mode, TradingMode
from app.services.execution_service import (
    cancel_order_by_id,
    get_entry_order_status,
)


# ============================================================
# MAIN
# ============================================================

def close_trade(db, trade, current_price, reason: str):
    """
    Close one OPEN signal.

    FINAL RULES:
    - PAPER:
        giữ nguyên logic close cũ
    - LIVE / TESTNET:
        1) close/reconcile với exchange
        2) sync final pending data
        3) cleanup sibling exits
        4) nếu pending còn remainder entry -> hủy remainder
        5) finalize pending lifecycle
    """
    if trade.status != "OPEN":
        return

    current_price = float(current_price)
    mode = get_current_mode()

    # ── Live/Testnet: try close / sync with exchange ─────────
    if mode != TradingMode.PAPER:
        from app.services.execution_service import close_position as exec_close
        exec_result = exec_close(trade, reason)
        if not exec_result.success:
            print(f"⚠️ Binance close failed: {trade.symbol} | {exec_result.error}")
            # vẫn cho phép reconcile DB sau
    else:
        exec_result = None

    # ── Reconcile pending/exchange BEFORE pnl finalize ───────
    pending = None
    if mode != TradingMode.PAPER:
        try:
            pending = _reconcile_pending_before_finalize(db, trade)
        except Exception as e:
            print(f"[PENDING RECONCILE] {e}")

    # ── Gap / exit price logic ───────────────────────────────
    if reason in ("SL", "TP"):
        theoretical = float(trade.stop_loss) if reason == "SL" else float(trade.take_profit)
        gap_pct = abs((current_price - theoretical) / theoretical * 100) if theoretical else 0

        # Nếu lệch quá mạnh so với lý thuyết -> lấy current thật
        if gap_pct > 2.0:
            exit_price = current_price
            trade.exit_reason = "GAP"
        else:
            exit_price = theoretical
            trade.exit_reason = reason
    else:
        exit_price = current_price
        trade.exit_reason = reason

    trade.exit_price = float(exit_price)

    # ── P&L using reconciled entry_price if updated ──────────
    entry = float(trade.entry_price)

    if trade.direction == "LONG":
        result = (exit_price - entry) / entry * 100 if entry else 0
    else:
        result = (entry - exit_price) / entry * 100 if entry else 0

    trade.result_percent = result
    trade.exit_time = utc_now()

    # ── Status rule: MANUAL-like reasons stay MANUAL ─────────
    if _is_manual_like_reason(reason):
        trade.status = "MANUAL"
    else:
        trade.status = "WIN" if result > 0 else "LOSS"

    # ── Print log ────────────────────────────────────────────
    icon = "🟢" if result > 0 else "🔴"
    status = trade.status
    print(
        f"{icon} [{trade.exit_reason}] {trade.symbol} {trade.direction} {trade.timeframe} "
        f"| Entry: {entry:.4f} "
        f"| Exit: {exit_price:.4f} "
        f"| P&L: {result:+.2f}% ({status}) "
        f"| Strategy: {trade.strategy_name or 'N/A'} "
        f"| Score: {float(trade.score or 0):.2f}"
    )

    # ── Exit Context ─────────────────────────────────────────
    try:
        from app.services.price_feed import get_all_current_prices
        price_map = get_all_current_prices()
        btc_price = price_map.get("BTCUSDT")
        btc_snap = get_or_build_hourly_snapshot()
        exit_ctx = build_event_context(btc_snap, btc_price)

        ctx = dict(trade.market_context or {})
        ctx["exit"] = exit_ctx
        trade.market_context = ctx
    except Exception:
        pass

    # ── Live/Testnet: finalize pending lifecycle ────────────
    if mode != TradingMode.PAPER:
        try:
            _finalize_pending_after_trade_close(db, trade, pending)
        except Exception as e:
            print(f"[PENDING FINALIZE] {e}")

    # ── Outcome Analytics ───────────────────────────────────
    feature = db.query(SignalFeature).filter(
        SignalFeature.signal_id == trade.id
    ).first()

    if feature:
        try:
            save_trade_outcome(db, trade, feature)
        except Exception as e:
            print(f"[OUTCOME] {e}")

    # ── Telegram ─────────────────────────────────────────────
    _notify_close(trade, mode)


# ============================================================
# HELPERS
# ============================================================

def _is_manual_like_reason(reason: str) -> bool:
    """
    Các reason mà business muốn giữ status = MANUAL.
    """
    if not reason:
        return False
    return reason in {
        "MANUAL",
        "KILL_SWITCH",
        "SYSTEM_CRASH",
    }


def _find_pending_for_trade(db, trade):
    """
    Tìm pending sinh ra signal này.
    Ưu tiên:
    1. pending.signal_id == trade.id
    2. fallback qua market_context.pending_id
    """
    pending = db.query(PendingSignal).filter(
        PendingSignal.signal_id == trade.id
    ).first()

    if pending:
        return pending

    try:
        ctx = trade.market_context or {}
        pending_id = ctx.get("pending_id")
        if pending_id:
            return db.query(PendingSignal).get(pending_id)
    except Exception:
        pass

    return None


def _reconcile_pending_before_finalize(db, trade):
    """
    LIVE/TESTNET only.

    Mục tiêu:
    - tìm pending/source execution của trade
    - sync executed_qty / avg_fill_price / exchange_status lần cuối
    - nếu entry average thay đổi vì partial tăng thêm trước lúc đóng,
      update lại trade.entry_price cho đúng số cuối cùng
    """
    pending = _find_pending_for_trade(db, trade)

    if not pending or not pending.exchange_order_id:
        return pending

    info = get_entry_order_status(pending.symbol, pending.exchange_order_id)

    pending.exchange_status = info.get("status", pending.exchange_status)
    pending.executed_qty = float(info.get("executed_qty") or pending.executed_qty or 0)
    pending.order_quantity = float(info.get("orig_qty") or pending.order_quantity or 0)

    if info.get("avg_price"):
        pending.avg_fill_price = float(info["avg_price"])

    pending.last_exchange_sync_at = utc_now()

    # Nếu avg fill thực tế thay đổi -> update entry của signal/trade
    if pending.avg_fill_price:
        trade.entry_price = float(pending.avg_fill_price)

    # Đồng bộ market_context.execution cho đúng số cuối
    ctx = dict(trade.market_context or {})
    exec_ctx = dict(ctx.get("execution") or {})
    exec_ctx["entry_order_id"] = pending.exchange_order_id
    exec_ctx["quantity"] = float(pending.executed_qty or exec_ctx.get("quantity") or 0)
    exec_ctx["entry_exchange_status"] = pending.exchange_status
    exec_ctx["sl_order_id"] = pending.sl_order_id
    exec_ctx["tp_order_id"] = pending.tp_order_id
    ctx["execution"] = exec_ctx
    trade.market_context = ctx

    db.flush()
    return pending


def _cleanup_signal_exit_orders(pending: PendingSignal):
    """
    Dọn sibling exits của signal đã đóng.
    Dùng explicit cancel theo order id.
    """
    if not pending:
        return

    if pending.sl_order_id:
        cancel_order_by_id(pending.symbol, pending.sl_order_id)

    if pending.tp_order_id:
        cancel_order_by_id(pending.symbol, pending.tp_order_id)


def _finalize_pending_after_trade_close(db, trade, pending):
    """
    RULE CHỐT:
    - Khi signal đóng (TP/SL/MANUAL/KILL_SWITCH),
      mọi tàn dư của signal đó phải được dọn:
        + hủy sibling exits
        + nếu remainder entry còn active -> hủy remainder
    - Sau đó pending lifecycle kết thúc:
        + có fill => FILLED
        + không fill => CANCELLED
    """
    if not pending:
        return

    # 1) Dọn exit orders cũ của signal
    _cleanup_signal_exit_orders(pending)

    # 2) Nếu pending vẫn WAIT => entry order lifecycle còn sống -> hủy remainder
    if pending.status == "WAIT" and pending.exchange_order_id:
        cancel_order_by_id(pending.symbol, pending.exchange_order_id)

        # sync lại lần cuối sau cancel
        info = get_entry_order_status(pending.symbol, pending.exchange_order_id)

        pending.exchange_status = info.get("status", pending.exchange_status)
        pending.executed_qty = float(info.get("executed_qty") or pending.executed_qty or 0)
        pending.order_quantity = float(info.get("orig_qty") or pending.order_quantity or 0)

        if info.get("avg_price"):
            pending.avg_fill_price = float(info["avg_price"])

        pending.last_exchange_sync_at = utc_now()

    # 3) Final pending local status
    if (pending.executed_qty or 0) > 0:
        pending.status = "FILLED"
    else:
        pending.status = "CANCELLED"

    db.flush()


# ============================================================
# TELEGRAM
# ============================================================

def _notify_close(trade, mode):
    try:
        from app.services.telegram_service import send_telegram

        result = float(trade.result_percent or 0)
        status = trade.status

        if status == "MANUAL":
            icon = "🛑"
            title = "Đã đóng thủ công"
            status_text = "MANUAL 🔧"
        else:
            icon = "🎉" if result > 0 else "📉"
            title = "Lệnh đã đóng"
            status_text = "WIN 🟢" if result > 0 else "LOSS 🔴"

        mode_icon = {
            "PAPER": "📋",
            "TESTNET": "🧪",
            "LIVE": "💰",
        }.get(mode.value, "📋")

        msg = (
            f"{icon} <b>{title} - {status_text}</b>\n\n"
            f"{mode_icon} <b>Chế độ:</b> {mode.value}\n"
            f"🪙 <b>Coin:</b> {trade.symbol}\n"
            f"🧩 <b>Strategy:</b> {trade.strategy_name}\n"
            f"📍 <b>Hướng:</b> {trade.direction}\n"
            f"⏱ <b>Khung:</b> {trade.timeframe}\n\n"
            f"🎯 <b>Entry:</b> {float(trade.entry_price):.4f}\n"
            f"🏁 <b>Exit:</b> {float(trade.exit_price):.4f}\n"
            f"📊 <b>Kết quả:</b> {result:+.2f}%\n"
            f"📝 <b>Lý do:</b> {trade.exit_reason}"
        )
        send_telegram(msg)

    except Exception as e:
        print(f"[CLOSE NOTIFY] {e}")

# ============================================================
# PROFIT PROTECTION (BREAK-EVEN)
# ============================================================

def apply_profit_protection(db, trade, new_sl_price: float) -> bool:
    """
    Hủy lệnh SL cũ và đặt lại lệnh SL mới (Break-even).
    Nếu lỗi, đóng Market toàn bộ vị thế ngay lập tức.
    """
    from app.services.execution_service import (
        cancel_order_by_id,
        place_algo_stop_market_close_position,
        get_executor
    )
    from app.core.trading_mode import get_current_mode

    mode = get_current_mode()
    if mode.is_paper:
        # Paper mode chỉ cần update DB
        trade.stop_loss = new_sl_price
        db.commit()
        return True

    ctx = dict(trade.market_context or {})
    exec_ctx = dict(ctx.get("execution") or {})
    old_sl_id = exec_ctx.get("sl_order_id")

    # 1. Hủy SL cũ
    if old_sl_id:
        cancel_order_by_id(trade.symbol, old_sl_id)
        print(f"🗑️ [PROFIT PROTECTION] Cancelled old SL: {old_sl_id}")

    # 2. Đặt SL mới (Algo)
    executor = get_executor()
    if not executor or not executor.ready:
        print("⚠️ [PROFIT PROTECTION] Executor not ready.")
        _emergency_close_protection(db, trade, "EXECUTOR_NOT_READY")
        return False

    symbol_info = executor.get_symbol_info(trade.symbol)
    rounded_sl = executor.round_price(trade.symbol, new_sl_price, symbol_info)

    try:
        new_sl_order = place_algo_stop_market_close_position(
            symbol=trade.symbol,
            direction=trade.direction,
            trigger_price=rounded_sl
        )

        new_sl_id = str(new_sl_order.get("algoId", "")) if new_sl_order else None

        if new_sl_id:
            # Thành công: Cập nhật DB
            trade.stop_loss = rounded_sl
            exec_ctx["sl_order_id"] = new_sl_id
            ctx["execution"] = exec_ctx
            trade.market_context = ctx
            db.commit()
            print(f"✅ [PROFIT PROTECTION] Placed NEW SL: {new_sl_id} @ {rounded_sl}")
            return True
        else:
            # Thất bại nhưng không văng Exception
            _emergency_close_protection(db, trade, "PLACE_NEW_SL_FAILED")
            return False

    except Exception as e:
        print(f"❌ [PROFIT PROTECTION] Error placing new SL: {e}")
        _emergency_close_protection(db, trade, "PLACE_NEW_SL_ERROR")
        return False


def _emergency_close_protection(db, trade, sub_reason: str):
    """
    Khi dời SL thất bại -> Vị thế đang trần trụi không có SL bảo vệ.
    Phải Market Close ngay lập tức để giữ an toàn.
    """
    print(f"🚨 [PROFIT PROTECTION EMERGENCY] Closing {trade.symbol} because {sub_reason}")
    from app.services.price_feed import get_current_price
    
    # Lấy giá để ghi log
    current_price = get_current_price(trade.symbol) or float(trade.entry_price)
    
    # Kích hoạt flow đóng lệnh chuẩn
    close_trade(db, trade, current_price, f"PROTECTION_REPLACE_FAILED::{sub_reason}")