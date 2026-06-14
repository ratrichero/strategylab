"""
Pending Engine — Fill PendingSignal → Signal
Features:
  - Touch fill: check 1m candle low/high thay vì chỉ check current price
  - Heartbeat logging
  - Atomic fill với optimistic lock
  - OTF re-check tại fill-time
  - SL/TP rebase theo actual entry
  - MAX_OPEN_TRADES check
"""
from datetime import timedelta
from typing import Dict, Optional

from sqlalchemy import and_

from app.core.time_utils import utc_now, ensure_utc
from app.db.session import SessionLocal
from app.db.models import PendingSignal, Signal, SignalFeature, ScanDebug


# ============================================================
# HEARTBEAT
# ============================================================

def _update_pending_heartbeat(db):
    """Ghi heartbeat của pending worker vào app_config."""
    try:
        from sqlalchemy import text
        now = utc_now()
        db.execute(text("""
            INSERT INTO app_config (key, value, updated_at)
            VALUES ('PENDING_WORKER_LAST_SEEN', :v, :now)
            ON CONFLICT (key)
            DO UPDATE SET value = :v, updated_at = :now
        """), {"v": now.isoformat(), "now": now})
        db.commit()
    except Exception as e:
        print(f"[PENDING HB] {e}")


# ============================================================
# TOUCH FILL — core logic
# ============================================================

def _check_touch(p: PendingSignal, current: float, price_map: dict) -> tuple[bool, float, str]:
    """
    Kiểm tra trigger có bị chạm không.

    Ưu tiên:
    1. current price đã qua trigger → fill ngay
    2. Fetch 1m candle, check low/high → touch fill
    3. Fallback: không fill

    Returns:
        (touched: bool, fill_price: float, source: str)
    """
    trigger = p.trigger_price

    # ── Level 1: current price ───────────────────────────
    if p.direction == "LONG" and current <= trigger:
        return True, trigger, "current_price"
    if p.direction == "SHORT" and current >= trigger:
        return True, trigger, "current_price"

    # ── Level 2: 1m candle touch ─────────────────────────
    try:
        from app.services.binance_service import get_klines_closed
        from app.core.time_utils import utc_now

        df1m = get_klines_closed(p.symbol, interval="1m", limit=3)

        if df1m is not None and not df1m.empty:
            # Check 2 candle gần nhất
            for i in [-1, -2]:
                if abs(i) > len(df1m):
                    continue
                candle = df1m.iloc[i]
                lo = float(candle["low"])
                hi = float(candle["high"])

                if p.direction == "LONG" and lo <= trigger <= hi:
                    return True, trigger, "1m_touch"
                if p.direction == "SHORT" and lo <= trigger <= hi:
                    return True, trigger, "1m_touch"

    except Exception as e:
        print(f"[TOUCH] 1m fetch error {p.symbol}: {e}")

    return False, 0.0, "no_touch"


# ============================================================
# REBASE SL/TP theo actual entry
# ============================================================

def _rebase_sl_tp(p: PendingSignal, actual_entry: float) -> tuple[float, float, float]:
    """
    Tính lại SL/TP từ actual_entry, giữ nguyên % risk từ trigger.

    Returns: (stop_loss, take_profit, rr)
    """
    trigger = p.trigger_price

    if trigger <= 0:
        return p.stop_loss, p.take_profit, p.rr or 2.0

    # Tính % từ trigger gốc
    sl_pct = abs((trigger - p.stop_loss) / trigger)
    tp_pct = abs((p.take_profit - trigger) / trigger)

    if p.direction == "LONG":
        stop_loss   = actual_entry * (1 - sl_pct)
        take_profit = actual_entry * (1 + tp_pct)
    else:
        stop_loss   = actual_entry * (1 + sl_pct)
        take_profit = actual_entry * (1 - tp_pct)

    rr = tp_pct / sl_pct if sl_pct > 0 else (p.rr or 2.0)

    return stop_loss, take_profit, rr


# ============================================================
# MAIN PROCESS
# ============================================================

def process_pending_signals(price_map: Optional[Dict[str, float]] = None):
    """
    Entry point — gọi mỗi tick từ price feed.
    """
    with SessionLocal() as db:
        now = utc_now()

        # ── Heartbeat ────────────────────────────────────
        _update_pending_heartbeat(db)

        # ── Cancel expired ───────────────────────────────
        expired = db.query(PendingSignal).filter(
            PendingSignal.status == "WAIT",
            PendingSignal.expire_at < now
        ).update({"status": "CANCELLED"}, synchronize_session=False)

        if expired > 0:
            db.commit()
            print(f"[PENDING] Cancelled {expired} expired")

        # ── Fetch active pending (chưa expired) ──────────
        pendings = db.query(PendingSignal).filter(
            PendingSignal.status   == "WAIT",
            PendingSignal.expire_at >= now      # ← chỉ lấy chưa expired
        ).all()

        if not pendings:
            return

        # ── Fetch price map nếu chưa có ─────────────────
        if not price_map:
            from app.services.binance_service import get_all_prices
            price_map = get_all_prices()
        if not price_map:
            return

        # ── Process từng pending ─────────────────────────
        filled = 0
        for p in pendings:
            try:
                result = _process_single(db, p, price_map, now)
                if result:
                    filled += 1
            except Exception as e:
                db.rollback()
                print(f"❌ Pending [{p.id}] {p.symbol}: {type(e).__name__} - {e}")

        if filled > 0:
            print(f"[PENDING] Filled {filled}/{len(pendings)} this cycle")


# ============================================================
# PROCESS SINGLE PENDING
# ============================================================

def _process_single(db, p: PendingSignal, price_map: dict, now) -> bool:
    """
    Returns True nếu fill thành công.
    """
    current = price_map.get(p.symbol)
    if current is None:
        return False

    current = float(current)

    # ── Touch check ──────────────────────────────────────
    touched, fill_price, touch_source = _check_touch(p, current, price_map)

    # ── Debug log (chỉ khi gần trigger) ─────────────────
    dist_pct = (current - p.trigger_price) / p.trigger_price * 100
    if abs(dist_pct) < 2.0:     # chỉ log khi trong vùng 2%
        print(
            f"[PENDING CHECK] id={p.id} {p.symbol} {p.direction} "
            f"current={current:.8f} trigger={p.trigger_price:.8f} "
            f"dist={dist_pct:+.4f}% "
            f"touched={touched} source={touch_source}"
        )

    if not touched:
        return False

    # ── Pre-fill validation ──────────────────────────────
    from app.services.prefill_validator import validate_before_fill
    result = validate_before_fill(p, current)

    if not result.passed:
        updated = db.query(PendingSignal).filter(
            and_(PendingSignal.id == p.id, PendingSignal.status == "WAIT")
        ).update({
            "status":             "REJECTED",
            "rejection_reason":   result.reason,
            "validation_details": result.details,
            "filled_at":          now,
        })
        if updated > 0:
            db.commit()
        print(f"🚫 REJECTED: {p.symbol} {p.direction} | {result.reason}")
        return False

    # ── MAX OPEN TRADES check ────────────────────────────
    from app.services.config_service import get_runtime_config
    cfg      = get_runtime_config()
    max_open = cfg.get("MAX_OPEN_TRADES", 10)

    current_open = db.query(Signal).filter(Signal.status == "OPEN").count()
    if current_open >= max_open:
        print(
            f"⏸️  MAX OPEN: {p.symbol} {p.direction} "
            f"| {current_open}/{max_open} — keep WAIT"
        )
        return False

    # ── OTF re-check tại fill-time ───────────────────────
    from app.services.open_trade_filter import get_open_trade_filter
    otf = get_open_trade_filter(cfg)

    atr_ratio = None
    if p.atr_value and p.trigger_price and float(p.trigger_price) > 0:
        atr_ratio = float(p.atr_value) / float(p.trigger_price)

    otf_ok, otf_reason = otf.check(
        symbol        = p.symbol,
        direction     = p.direction,
        strategy_name = p.strategy_name,
        pattern       = p.pattern,
        timeframe     = p.timeframe,
        regime        = p.regime,
        score         = p.signal_score or 0,
        ml_prob       = p.ml_prob,
        components    = {
            "trend_score":    p.trend_score    or 0,
            "momentum_score": p.momentum_score or 0,
            "volume_score":   p.volume_score   or 0,
            "pattern_score":  p.pattern_score  or 0,
            "mtf_score":      p.mtf_score      or 0,
            "penalty_norm":   p.penalty        or 0,
        },
        atr_ratio = atr_ratio,
        db        = db,
    )

    if not otf_ok:
        print(f"⏸️  FILL OTF BLOCK: {p.symbol} {p.direction} | {otf_reason}")
        return False

    # ── Atomic fill — optimistic lock ───────────────────
    updated = db.query(PendingSignal).filter(
        and_(PendingSignal.id == p.id, PendingSignal.status == "WAIT")
    ).update({
        "status":    "FILLED",
        "filled_at": now,
    })

    if updated == 0:
        # Race condition — đã được fill bởi process khác
        return False

    # ── Execute order ────────────────────────────────────
    from app.services.execution_service import open_position
    exec_result = open_position(p, price_map, fill_price=fill_price)

    if not exec_result.success:
        print(f"❌ Execution failed: {p.symbol} | {exec_result.error}")
        db.query(PendingSignal).filter(
            PendingSignal.id == p.id
        ).update({
            "status":           "REJECTED",
            "rejection_reason": f"EXEC_FAIL::{exec_result.error}",
        })
        db.commit()
        return False

    # ── Tính actual entry ────────────────────────────────
    actual_entry = float(exec_result.actual_entry or fill_price)

    # ── Rebase SL/TP theo actual entry ──────────────────
    stop_loss, take_profit, rr = _rebase_sl_tp(p, actual_entry)

    # ── Validate SL/TP sau rebase ────────────────────────
    # Đảm bảo SL không nằm sai phía entry
    if p.direction == "LONG" and stop_loss >= actual_entry:
        stop_loss = actual_entry * (1 - 0.02)   # fallback 2%
    if p.direction == "SHORT" and stop_loss <= actual_entry:
        stop_loss = actual_entry * (1 + 0.02)

    # ── Build market context ─────────────────────────────
    from app.services.btc_context_cache import (
        get_or_build_hourly_snapshot, build_event_context)

    btc_snap  = get_or_build_hourly_snapshot()
    btc_price = price_map.get("BTCUSDT")
    entry_ctx = build_event_context(btc_snap, btc_price)

    # ── Create Signal ────────────────────────────────────
    from app.core.trading_mode import get_current_mode
    snap = p.indicators_snapshot or {}
    mode = get_current_mode()

    signal = Signal(
        symbol         = p.symbol,
        timeframe      = p.timeframe,
        pattern        = p.pattern,
        strategy_name  = p.strategy_name,
        direction      = p.direction,
        score          = p.signal_score,
        entry_price    = actual_entry,
        stop_loss      = stop_loss,      # ← rebased
        take_profit    = take_profit,    # ← rebased
        rsi            = snap.get("rsi"),
        volume_ratio   = snap.get("volume_ratio"),
        atr_ratio      = snap.get("atr_ratio"),
        regime         = p.regime,
        candle_time    = ensure_utc(p.candle_time),
        engine_version = snap.get("engine_version", 2.0),
        engine_version = p.engine_version,
        market_context = {
            "entry": entry_ctx,
            "fill":  {
                "fill_price":  fill_price,
                "touch_source": touch_source,
            },
            "execution": {
                "mode":       exec_result.mode,
                "order_id":   exec_result.order_id,
                "quantity":   exec_result.actual_quantity,
                "leverage":   exec_result.leverage,
                "fee":        exec_result.fee,
                "sl_order_id": exec_result.sl_order_id,
                "tp_order_id": exec_result.tp_order_id,
            },
        },
        trading_mode = mode.value,
        # created_at tự động = utc_now() theo model
    )
    db.add(signal)
    db.flush()  # lấy signal.id

    # ── Signal Feature ───────────────────────────────────
    feature = SignalFeature(
        signal_id      = signal.id,
        rsi            = snap.get("rsi"),
        volume_ratio   = snap.get("volume_ratio"),
        atr_ratio      = snap.get("atr_ratio"),
        ema_distance   = snap.get("ema_distance"),
        regime         = p.regime,
        trend_score    = p.trend_score,
        momentum_score = p.momentum_score,
        volume_score   = p.volume_score,
        pattern_score  = p.pattern_score,
        mtf_score      = p.mtf_score,
        penalty_norm   = p.penalty,
        total_score    = p.signal_score,
        rr             = rr,
    )
    db.add(feature)

    # ── Link ScanDebug → Signal ──────────────────────────
    if p.scan_debug_id:
        debug = db.query(ScanDebug).get(p.scan_debug_id)
        if debug:
            debug.signal_id = signal.id

    db.commit()

    # ── Notify ───────────────────────────────────────────
    _notify_fill(p, signal, exec_result, fill_price, touch_source, stop_loss, take_profit, rr)

    print(
        f"✅ FILLED [{touch_source}]: {p.symbol} {p.direction} "
        f"trigger={p.trigger_price:.6f} "
        f"actual={actual_entry:.6f} "
        f"SL={stop_loss:.6f} TP={take_profit:.6f} "
        f"| {p.strategy_name}"
    )

    return True


# ============================================================
# NOTIFY
# ============================================================

def _notify_fill(p, signal, exec_result, fill_price, touch_source, sl, tp, rr):
    try:
        from app.services.telegram_service import send_telegram
        from app.core.time_utils import to_vn_str

        rr_text   = f"{rr:.2f}" if rr else "N/A"
        prob      = p.ml_prob
        score_tag = " 🌟" if (p.signal_score or 0) >= 8 else ""
        conf_tag  = " 🔥" if prob and prob >= 0.7 else ""
        tf_icon   = {"15m": "⚡", "1h": "🕐", "4h": "🕓"}.get(p.timeframe, "🕒")
        mode_icon = {"PAPER": "📋", "TESTNET": "🧪", "LIVE": "💰"}.get(
            exec_result.mode, "📋")
        source_icon = {"current_price": "📍", "1m_touch": "🎯"}.get(
            touch_source, "📍")

        # Candle close time hiển thị theo VN
        duration  = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(p.timeframe, 15)
        close_utc = ensure_utc(p.candle_time) + timedelta(minutes=duration) \
                    if p.candle_time else utc_now()

        qty_text = (
            f"\n<b>Quantity:</b> {exec_result.actual_quantity}"
            if exec_result.actual_quantity else ""
        )
        lev_text = (
            f"\n<b>Leverage:</b> {exec_result.leverage}x"
            if exec_result.leverage and exec_result.leverage > 1 else ""
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
            f"<b>Trigger:</b>   {p.trigger_price:.6f}\n"
            f"<b>Entry:</b>     {float(signal.entry_price):.6f} {source_icon}\n"
            f"<b>SL:</b>        {sl:.6f}\n"
            f"<b>TP:</b>        {tp:.6f}\n"
            f"<b>RR:</b>        {rr_text}"
            f"{qty_text}{lev_text}\n\n"
            f"<b>Candle:</b>    {to_vn_str(close_utc)} GMT+7"
        )
        send_telegram(msg)

    except Exception as e:
        print(f"[NOTIFY FILL] {e}")