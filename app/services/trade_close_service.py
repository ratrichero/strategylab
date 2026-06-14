"""Trade Close — Paper + Live execution"""
from datetime import datetime
from app.db.models import SignalFeature
from app.services.outcome_service import save_trade_outcome
from app.services.btc_context_cache import get_or_build_hourly_snapshot, build_event_context
from app.core.trading_mode import get_current_mode, TradingMode
 from app.core.time_utils import utc_now


def close_trade(db, trade, current_price, reason: str):
    if trade.status != "OPEN": return
    entry = float(trade.entry_price)
    current_price = float(current_price)
    mode = get_current_mode()

    # ── Live: close on Binance ────────────────────────────
    if not mode.is_paper:
        from app.services.execution_service import close_position as exec_close
        exec_result = exec_close(trade, reason)
        if not exec_result.success:
            print(f"⚠️ Binance close failed: {trade.symbol} | {exec_result.error}")
            # Still update DB — manual reconciliation later

    # ── Gap Recovery ──────────────────────────────────────
    if reason in ("SL", "TP"):
        theoretical = float(trade.stop_loss) if reason == "SL" else float(trade.take_profit)
        gap_pct = abs((current_price - theoretical) / theoretical * 100)
        if gap_pct > 2.0:
            exit_price = current_price; trade.exit_reason = "GAP"
        else:
            exit_price = theoretical; trade.exit_reason = reason
    else:
        exit_price = current_price; trade.exit_reason = reason

    trade.exit_price = float(exit_price)

    # ── P&L ──────────────────────────────────────────────
    if trade.direction == "LONG":
        result = (exit_price - entry) / entry * 100
    else:
        result = (entry - exit_price) / entry * 100

    trade.result_percent = result
    trade.status = "WIN" if result > 0 else "LOSS"

    trade.exit_time = utc_now()

     # ── PRINT LOG ─────────────────────────────────────
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


    # ── Exit Context ──────────────────────────────────────
    try:
        from app.services.price_feed import get_all_current_prices
        price_map = get_all_current_prices()
        btc_price = price_map.get("BTCUSDT")
        btc_snap  = get_or_build_hourly_snapshot()
        exit_ctx  = build_event_context(btc_snap, btc_price)
        if trade.market_context:
            trade.market_context["exit"] = exit_ctx
        else:
            trade.market_context = {"exit": exit_ctx}
    except: pass

    # ── Outcome Analytics ─────────────────────────────────
    feature = db.query(SignalFeature).filter(
        SignalFeature.signal_id == trade.id).first()
    if feature:
        try: save_trade_outcome(db, trade, feature)
        except Exception as e: print(f"[OUTCOME] {e}")

    # ── Telegram ──────────────────────────────────────────
    _notify_close(trade, mode)


def _notify_close(trade, mode):
    try:
        from app.services.telegram_service import send_telegram
        result = float(trade.result_percent)
        icon   = "🎉" if result > 0 else "😢"
        status = "WIN 🟢" if result > 0 else "LOSS 🔴"
        mode_icon = {"PAPER":"📋","TESTNET":"🧪","LIVE":"💰"}.get(
            mode.get_mode().value, "📋")
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
            f"<b>Reason:</b>    {trade.exit_reason}")
        send_telegram(msg)
    except Exception as e: print(f"[CLOSE NOTIFY] {e}")
