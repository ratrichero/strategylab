"""Pending Engine — Fill PendingSignal → Signal (event-driven + execution)"""
from datetime import datetime, timedelta
from typing import Dict, Optional
from sqlalchemy import and_
from app.db.session import SessionLocal
from app.db.models import PendingSignal, Signal, SignalFeature, ScanDebug
from app.services.prefill_validator import validate_before_fill
from app.services.btc_context_cache import get_or_build_hourly_snapshot, build_event_context
from app.services.signal_service import to_local_time
from app.core.trading_mode import get_current_mode, TradingMode


def process_pending_signals(price_map: Optional[Dict[str, float]] = None):
    with SessionLocal() as db:
        now = datetime.utcnow()

        expired = db.query(PendingSignal).filter(
            PendingSignal.status == "WAIT",
            PendingSignal.expire_at < now
        ).update({"status": "CANCELLED"}, synchronize_session=False)
        if expired > 0: db.commit()

        pendings = db.query(PendingSignal).filter(
            PendingSignal.status == "WAIT").all()
        if not pendings: return

        if not price_map:
            from app.services.binance_service import get_all_prices
            price_map = get_all_prices()
        if not price_map: return

        for p in pendings:
            try: _process_single(db, p, price_map, now)
            except Exception as e:
                db.rollback()
                print(f"❌ Pending [{p.id}] {p.symbol}: {e}")


def _process_single(db, p, price_map, now):
    current = price_map.get(p.symbol)
    if current is None: return

    should_fill = (
        (p.direction == "LONG"  and current <= p.trigger_price) or
        (p.direction == "SHORT" and current >= p.trigger_price)
    )
    if not should_fill: return

    # Pre-fill validation
    result = validate_before_fill(p, current)
    if not result.passed:
        updated = db.query(PendingSignal).filter(
            and_(PendingSignal.id == p.id, PendingSignal.status == "WAIT")
        ).update({
            "status": "REJECTED",
            "rejection_reason": result.reason,
            "validation_details": result.details
        })
        if updated > 0: db.commit()
        print(f"🚫 REJECTED: {p.symbol} {p.direction} | {result.reason}")
        return


     # ── MAX OPEN TRADES CHECK (điều kiện cuối cùng) ──────
    from app.services.config_service import get_runtime_config
    from app.db.models import Signal

    cfg = get_runtime_config()
    max_open = cfg.get("MAX_OPEN_TRADES", 10)

    current_open = db.query(Signal).filter(Signal.status == "OPEN").count()

    if current_open >= max_open:
        # Không fill — giữ pending ở WAIT, sẽ check lại lần sau
        print(
            f"⏸️ MAX OPEN REACHED: {p.symbol} {p.direction} "
            f"| Open: {current_open}/{max_open} — skip fill, keep WAIT"
        )
        return
    
    # Atomic fill
    updated = db.query(PendingSignal).filter(
        and_(PendingSignal.id == p.id, PendingSignal.status == "WAIT")
    ).update({"status": "FILLED", "filled_at": now})
    if updated == 0: return

    # ── Execute order ────────────────────────────────────
    from app.services.execution_service import open_position

    exec_result = open_position(p, price_map)

    if not exec_result.success:
        print(f"❌ Execution failed: {p.symbol} | {exec_result.error}")
        db.query(PendingSignal).filter(
            PendingSignal.id == p.id
        ).update({
            "status": "REJECTED",
            "rejection_reason": f"EXEC_FAIL::{exec_result.error}"
        })
        db.commit()
        return

    # ── Create Signal ────────────────────────────────────
    snap = p.indicators_snapshot or {}
    mode = get_current_mode()

    btc_snap  = get_or_build_hourly_snapshot()
    btc_price = price_map.get("BTCUSDT")
    entry_ctx = build_event_context(btc_snap, btc_price)

    actual_entry = exec_result.actual_entry or p.trigger_price

    signal = Signal(
        symbol=p.symbol, timeframe=p.timeframe, pattern=p.pattern,
        strategy_name=p.strategy_name, direction=p.direction,
        score=p.signal_score,
        entry_price=actual_entry,
        stop_loss=p.stop_loss, take_profit=p.take_profit,
        rsi=snap.get("rsi"), volume_ratio=snap.get("volume_ratio"),
        atr_ratio=snap.get("atr_ratio"), regime=p.regime,
        candle_time=p.candle_time,
        engine_version=snap.get("engine_version", 2.0),
        market_context={
            "entry": entry_ctx,
            "execution": {
                "mode": exec_result.mode,
                "order_id": exec_result.order_id,
                "quantity": exec_result.actual_quantity,
                "leverage": exec_result.leverage,
                "fee": exec_result.fee,
                "sl_order_id": exec_result.sl_order_id,
                "tp_order_id": exec_result.tp_order_id,
            }
        },
        trading_mode=mode.value
    )
    db.add(signal); db.flush()

    feature = SignalFeature(
        signal_id=signal.id, rsi=snap.get("rsi"),
        volume_ratio=snap.get("volume_ratio"), atr_ratio=snap.get("atr_ratio"),
        ema_distance=snap.get("ema_distance"), regime=p.regime,
        trend_score=p.trend_score, momentum_score=p.momentum_score,
        volume_score=p.volume_score, pattern_score=p.pattern_score,
        mtf_score=p.mtf_score, penalty_norm=p.penalty,
        total_score=p.signal_score, rr=p.rr)
    db.add(feature)

    if p.scan_debug_id:
        debug = db.query(ScanDebug).get(p.scan_debug_id)
        if debug: debug.signal_id = signal.id

    db.commit()

    _notify_fill(p, signal, exec_result)
    print(
        f"✅ FILLED: {p.symbol} {p.direction} "
        f"@ {actual_entry:.4f} | {exec_result.mode} | "
        f"{p.strategy_name}"
    )


def _notify_fill(p, signal, exec_result):
    try:
        from app.services.telegram_service import send_telegram
        rr_text  = f"{p.rr:.2f}" if p.rr else "N/A"
        prob     = p.ml_prob
        score_tag = " 🌟" if (p.signal_score or 0) >= 8 else ""
        conf_tag  = " 🔥" if prob and prob >= 0.7 else ""
        tf_icon  = {"15m":"⚡","1h":"🕐","4h":"🕓"}.get(p.timeframe,"🕒")

        mode_icon = {
            "PAPER": "📋", "TESTNET": "🧪", "LIVE": "💰"
        }.get(exec_result.mode, "📋")

        duration = {"15m":15,"1h":60,"4h":240,"1d":1440}.get(p.timeframe,15)
        close_time = p.candle_time + timedelta(minutes=duration)
        local_time = to_local_time(close_time)

        entry_display = exec_result.actual_entry or p.trigger_price
        qty_text = (
            f"\n<b>Quantity:</b> {exec_result.actual_quantity}"
            if exec_result.actual_quantity else ""
        )
        lev_text = (
            f"\n<b>Leverage:</b> {exec_result.leverage}x"
            if exec_result.leverage > 1 else ""
        )

        msg = (
            f"🚨 <b>SIGNAL {exec_result.mode}</b>{score_tag}{conf_tag}\n\n"
            f"{mode_icon} Mode: {exec_result.mode}\n"
            f"<b>Symbol:</b>    {p.symbol}\n"
            f"<b>TF:</b>        {p.timeframe} {tf_icon}\n"
            f"<b>Strategy:</b>  {p.strategy_name}\n"
            f"<b>Pattern:</b>   {p.pattern}\n"
            f"<b>Direction:</b> {p.direction}\n"
            f"<b>Regime:</b>    {p.regime}\n"
            f"<b>Score:</b>     {p.signal_score}\n\n"
            f"<b>Entry:</b>     {entry_display:.4f}\n"
            f"<b>SL:</b>        {p.stop_loss:.4f}\n"
            f"<b>TP:</b>        {p.take_profit:.4f}\n"
            f"<b>RR:</b>        {rr_text}"
            f"{qty_text}{lev_text}\n\n"
            f"<b>Candle Close:</b> {local_time.strftime('%Y-%m-%d %H:%M')} GMT+7"
        )
        send_telegram(msg)
    except Exception as e: print(f"[NOTIFY] {e}")
