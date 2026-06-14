"""Trade Close — Paper + Live execution"""
from app.core.time_utils import utc_now
from app.db.models import SignalFeature, PendingSignal
from app.services.outcome_service import save_trade_outcome
from app.services.btc_context_cache import get_or_build_hourly_snapshot, build_event_context
from app.core.trading_mode import get_current_mode, TradingMode
from app.services.execution_service import (
    get_entry_order_status,
    cancel_order_by_id,
)


def close_trade(db, trade, current_price, reason: str):
    """
    Close 1 signal/trade.

    RULE mới:
    - PAPER: giữ nguyên logic cũ
    - LIVE/TESTNET:
        + close position
        + sync final pending/exchange info
        + hủy remainder entry nếu còn
        + cleanup sibling exit orders
        + finalize pending lifecycle
    """
    if trade.status != "OPEN":
        return

    entry = float(trade.entry_price)
    current_price = float(current_price)
    mode = get_current_mode()

    # ── Live/Testnet: close on Binance ─────────────────────
    if not mode.is_paper:
        from app.services.execution_service import close_position as exec_close
        exec_result = exec_close(trade, reason)
        if not exec_result.success:
            print(f"⚠️ Binance close failed: {trade.symbol} | {exec_result.error}")
            # vẫn cho phép DB update, reconciliation sau
    else:
        exec_result = None

    # ── Reconcile pending/exchange BEFORE final pnl ────────
    pending = None
    if not mode.is_paper:
        try:
            pending = _reconcile_pending_before_finalize(db, trade)
        except Exception as e:
            print(f"[PENDING RECONCILE] {e}")

    # ── Gap Recovery ───────────────────────────────────────
    if reason in ("SL", "TP"):
        theoretical = float(trade.stop_loss) if reason == "SL" else float(trade.take_profit)
        gap_pct = abs((current_price - theoretical) / theoretical * 100) if theoretical else 0
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

    # ── P&L ────────────────────────────────────────────────
    # entry_price có thể đã được reconcile/update nếu pending partial fill tăng thêm trước close
    entry = float(trade.entry_price)

    if trade.direction == "LONG":
        result = (exit_price - entry) / entry * 100 if entry else 0
    else:
        result = (entry - exit_price) / entry * 100 if entry else 0

    trade.result_percent = result
    trade.status = "WIN" if result > 0 else "LOSS"
    trade.exit_time = utc_now()

    # ── Print log ──────────────────────────────────────────
    icon = "🟢" if result > 0 else "🔴"
    status = "WIN" if result > 0 else "LOSS"
    print(
        f"{icon} [{trade.exit_reason}] {trade.symbol} {trade.direction} {trade.timeframe} "
        f"| Entry: {entry:.4f} "
        f"| Exit: {exit_price:.4f} "
        f"| P&L: {result:+.2f}% ({status}) "
        f"| Strategy: {trade.strategy_name or 'N/A'} "
        f"| Score: {float(trade.score or 0):.2f}"
    )

    # ── Exit Context ───────────────────────────────────────
    try:
        from app.services.price_feed import get_all_current_prices
        price_map = get_all_current_prices()
        btc_price = price_map.get("BTCUSDT")
        btc_snap = get_or_build_hourly_snapshot()
        exit_ctx = build_event_context(btc_snap, btc_price)
        if trade.market_context:
            trade.market_context["exit"] = exit_ctx
        else:
            trade.market_context = {"exit": exit_ctx}
    except Exception:
        pass

    # ── Live/Testnet: finalize pending lifecycle ───────────
    if not mode.is_paper:
        try:
            _finalize_pending_after_trade_close(db, trade, pending)
        except Exception as e:
            print(f"[PENDING FINALIZE] {e}")

    # ── Outcome Analytics ──────────────────────────────────
    feature = db.query(SignalFeature).filter(
        SignalFeature.signal_id == trade.id
    ).first()

    if feature:
        try:
            save_trade_outcome(db, trade, feature)
        except Exception as e:
            print(f"[OUTCOME] {e}")

    # ── Telegram ───────────────────────────────────────────
    _notify_close(trade, mode)


# ============================================================
# PENDING RECONCILIATION HELPERS
# ============================================================

def _reconcile_pending_before_finalize(db, trade):
    """
    LIVE/TESTNET only.

    Mục tiêu:
    - tìm pending sinh ra trade này
    - sync lại executed_qty / avg_fill_price / exchange_status lần cuối
    - nếu có late partial fill trước lúc close, update lại entry_price của signal
    - giữ cho số liệu cuối cùng của trade là số liệu thực tế nhất có thể
    """
    pending = db.query(PendingSignal).filter(
        PendingSignal.signal_id == trade.id
    ).first()

    if not pending or not pending.exchange_order_id:
        return pending

    info = get_entry_order_status(pending.symbol, pending.exchange_order_id)

    pending.exchange_status = info.get("status", pending.exchange_status)
    pending.executed_qty = float(info.get("executed_qty") or pending.executed_qty or 0)
    if info.get("avg_price"):
        pending.avg_fill_price = float(info["avg_price"])
    pending.last_exchange_sync_at = utc_now()

    # Nếu avg fill thực tế đã thay đổi vì partial tăng thêm trước lúc đóng trade
    if pending.avg_fill_price:
        trade.entry_price = float(pending.avg_fill_price)

    # Cập nhật lại quantity thực tế trong market_context.execution
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


def _finalize_pending_after_trade_close(db, trade, pending):
    """
    RULE CHỐT:
    - Khi signal đóng (TP/SL/MANUAL/KILL_SWITCH),
      nếu pending còn remainder entry đang active => hủy remainder đó
    - cleanup sibling exits cũ
    - pending lifecycle kết thúc:
        + có fill => FILLED
        + không fill => CANCELLED

    Đây là chính sách "Xóa cờ làm lại".
    """
    if not pending:
        return

    # 1) Dọn sibling exits (nếu còn)
    # Vì signal đã đóng, mọi exit order của signal cũ phải dọn đi
    if pending.sl_order_id:
        cancel_order_by_id(pending.symbol, pending.sl_order_id)
    if pending.tp_order_id:
        cancel_order_by_id(pending.symbol, pending.tp_order_id)

    # 2) Nếu pending vẫn WAIT tức là entry order lifecycle chưa terminal -> hủy remainder entry
    if pending.status == "WAIT" and pending.exchange_order_id:
        cancel_order_by_id(pending.symbol, pending.exchange_order_id)

        # sync lại 1 lần nữa sau cancel
        info = get_entry_order_status(pending.symbol, pending.exchange_order_id)
        pending.exchange_status = info.get("status", pending.exchange_status)
        pending.executed_qty = float(info.get("executed_qty") or pending.executed_qty or 0)
        if info.get("avg_price"):
            pending.avg_fill_price = float(info["avg_price"])
        pending.last_exchange_sync_at = utc_now()

    # 3) Final local pending state
    if (pending.executed_qty or 0) > 0:
        pending.status = "FILLED"
    else:
        pending.status = "CANCELLED"

    db.flush()


# ============================================================
# TELEGRAM NOTIFY
# ============================================================

def _notify_close(trade, mode):
    try:
        from app.services.telegram_service import send_telegram
        result = float(trade.result_percent)
        icon = "🎉" if result > 0 else "😢"
        status = "WIN 🟢" if result > 0 else "LOSS 🔴"
        mode_icon = {
            "PAPER": "📋",
            "TESTNET": "🧪",
            "LIVE": "💰"
        }.get(mode.get_mode().value, "📋")

        msg = (
            f"{icon} <b>TRADE CLOSED — {status}</b>\n\n"
            f"{mode_icon} Mode: {mode.get_mode().value}\n"
            f"<b>Symbol:</b>    {trade.symbol}\n"
            f"<b>Strategy:</b>  {trade.strategy_name}\n"
            f"<b>Direction:</b> {trade.direction}\n"
            f"<b>TF:</b>        {trade.timeframe}\n\n"
            f"<b>Entry:</b>     {float(trade.entry_price):.4f}\n"
            f"<b>Exit:</b>      {float(trade.exit_price):.4f}\n"
            f"<b>Result:</b>    {result:+.2f}%\n"
            f"<b>Reason:</b>    {trade.exit_reason}"
        )
        send_telegram(msg)
    except Exception as e:
        print(f"[CLOSE NOTIFY] {e}")