"""
Pending Engine — Dual Logic (Paper vs Live/Testnet)

RULES CHỐT:
1. PAPER:
   - local touch fill
   - prefill + OTF tại fill time
   - fill local -> Signal

2. LIVE / TESTNET:
   Phase A — PRE-PLACE:
     WAIT + exchange_order_id IS NULL
     -> OTF pass
     -> Prefill pass
     -> Reprice ONCE
     -> Round prices
     -> Place LIMIT entry
     -> Place algo SL/TP (closePosition=true, MARK_PRICE)
     -> If protection fail => rollback immediately

   Phase B — POST-PLACE:
     WAIT + exchange_order_id IS NOT NULL
     -> SYNC ONLY
     -> no repeated OTF / no repeated Prefill
     -> sync exchange_status / executed_qty / avg_fill_price
     -> create Signal on first fill
     -> update Signal if executed_qty increases
     -> pending stays WAIT while entry lifecycle still active
     -> terminal + fill > 0 => FILLED
     -> terminal + fill = 0 => CANCELLED
"""

from datetime import timedelta
from typing import Dict, Optional

from sqlalchemy import and_

from app.core.time_utils import utc_now, ensure_utc, to_vn
from app.db.session import SessionLocal
from app.db.models import PendingSignal, Signal, SignalFeature, ScanDebug
from app.core.trading_mode import get_current_mode, TradingMode

from app.services.execution_service import (
    open_position,                      # paper path
    place_limit_entry_order,           # live/testnet
    place_close_position_exit_orders,  # algo SL/TP
    get_entry_order_status,            # sync LIMIT entry
    cancel_order_by_id,                # smart cancel (normal + algo)
    cancel_entry_and_exits,            # composite cleanup
    get_open_algo_orders,              # algo orders query
    get_executor,
    OrderResult,
)

from app.services.prefill_validator import validate_before_fill
from app.services.open_trade_filter import get_open_trade_filter
from app.services.config_service import get_runtime_config
from app.services.btc_context_cache import (
    get_or_build_hourly_snapshot,
    build_event_context,
)


# ============================================================
# HEARTBEAT
# ============================================================

def _update_pending_heartbeat(db):
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
# SHARED HELPERS
# ============================================================

def _is_terminal_exchange_status(status: Optional[str]) -> bool:
    return status in ("FILLED", "CANCELED", "EXPIRED", "REJECTED")


def _calc_repriced_triplet(p: PendingSignal, reprice_pct: float):
    """
    Reprice từ bộ giá hiện tại trên pending.
    Chỉ được gọi 1 lần duy nhất (guard bằng reprice_applied).
    """
    trigger_old = float(p.trigger_price)
    sl_old = float(p.stop_loss)
    tp_old = float(p.take_profit)

    if trigger_old <= 0:
        return trigger_old, sl_old, tp_old

    if p.direction == "LONG":
        sl_pct = abs((trigger_old - sl_old) / trigger_old)
        tp_pct = abs((tp_old - trigger_old) / trigger_old)

        trigger_new = trigger_old * (1 - reprice_pct)
        sl_new = trigger_new * (1 - sl_pct)
        tp_new = trigger_new * (1 + tp_pct)
    else:
        sl_pct = abs((sl_old - trigger_old) / trigger_old)
        tp_pct = abs((trigger_old - tp_old) / trigger_old)

        trigger_new = trigger_old * (1 + reprice_pct)
        sl_new = trigger_new * (1 + sl_pct)
        tp_new = trigger_new * (1 - tp_pct)

    return trigger_new, sl_new, tp_new


def _round_triplet_for_exchange(symbol: str, trigger_price: float, stop_loss: float, take_profit: float):
    executor = get_executor()
    if not executor or not executor.ready:
        return trigger_price, stop_loss, take_profit

    symbol_info = executor.get_symbol_info(symbol)
    if not symbol_info:
        return trigger_price, stop_loss, take_profit

    trigger_price = executor.round_price(symbol, trigger_price, symbol_info)
    stop_loss     = executor.round_price(symbol, stop_loss, symbol_info)
    take_profit   = executor.round_price(symbol, take_profit, symbol_info)

    return trigger_price, stop_loss, take_profit


def _check_touch(p: PendingSignal, current: float) -> tuple[bool, float, str]:
    """
    PAPER only:
    - current snapshot
    - fallback 1m candle touch
    """
    trigger = float(p.trigger_price)

    if p.direction == "LONG" and current <= trigger:
        return True, trigger, "current_price"

    if p.direction == "SHORT" and current >= trigger:
        return True, trigger, "current_price"

    try:
        from app.services.binance_service import get_klines_closed
        df1m = get_klines_closed(p.symbol, interval="1m", limit=3)
        if df1m is not None and not df1m.empty:
            for i in [-1, -2]:
                if abs(i) > len(df1m):
                    continue
                candle = df1m.iloc[i]
                lo = float(candle["low"])
                hi = float(candle["high"])
                if lo <= trigger <= hi:
                    return True, trigger, "1m_touch"
    except Exception as e:
        print(f"[TOUCH] 1m fetch error {p.symbol}: {e}")

    return False, 0.0, "no_touch"


def _mark_rejected(db, p: PendingSignal, reason: str, details: Optional[dict] = None):
    p.status = "REJECTED"
    p.rejection_reason = reason
    p.validation_details = details
    db.commit()


def _cancel_no_fill_pending(db, p: PendingSignal, reason: str):
    p.status = "CANCELLED"
    p.rejection_reason = reason
    db.commit()
    print(f"🗑️ PENDING CANCELLED: {p.symbol} | {reason}")


def _rollback_on_protection_fail(db, p: PendingSignal, reason: str):
    """
    Protection fail policy:
    - Sync entry state
    - If no fill yet: cancel entry + exits, mark REJECTED
    - If already filled: close position immediately, cleanup, mark FILLED
    """
    print(f"⚠️ PROTECTION FAIL ROLLBACK: {p.symbol} | {reason}")

    info = get_entry_order_status(p.symbol, p.exchange_order_id)
    p.exchange_status = info.get("status", p.exchange_status)
    p.executed_qty = float(info.get("executed_qty") or p.executed_qty or 0)
    if info.get("avg_price"):
        p.avg_fill_price = float(info["avg_price"])
    p.last_exchange_sync_at = utc_now()
    db.commit()

    executed = float(p.executed_qty or 0)

    if executed <= 0:
        cancel_entry_and_exits(p)
        p.status = "REJECTED"
        p.rejection_reason = f"PROTECTION_SETUP_FAILED::{reason}"
        db.commit()
        return

    # Đã có fill -> đóng ngay position để tránh naked risk
    executor = get_executor()
    if executor and executor.ready:
        try:
            executor.cancel_all_orders(p.symbol)
        except Exception:
            pass

        try:
            from app.services.execution_service import cancel_all_algo_orders
            cancel_all_algo_orders(p.symbol)
        except Exception:
            pass

        try:
            executor.close_position(p.symbol, p.direction)
        except Exception as e:
            print(f"[ROLLBACK CLOSE] {p.symbol}: {e}")

    p.status = "FILLED"
    p.rejection_reason = f"PROTECTION_SETUP_FAILED::{reason}"
    db.commit()


# ============================================================
# PAPER FINALIZER
# ============================================================

def _finalize_paper_fill(db, p: PendingSignal, now, actual_entry, stop_loss, take_profit, exec_result, price_map):
    """
    PAPER:
    - WAIT -> FILLED ngay khi touch fill
    - create Signal / SignalFeature / link ScanDebug
    """
    updated = db.query(PendingSignal).filter(
        and_(PendingSignal.id == p.id, PendingSignal.status == "WAIT")
    ).update({"status": "FILLED", "filled_at": now})

    if updated == 0:
        return None

    snap = p.indicators_snapshot or {}
    mode = get_current_mode()

    btc_snap = get_or_build_hourly_snapshot()
    btc_price = price_map.get("BTCUSDT") if price_map else None
    entry_ctx = build_event_context(btc_snap, btc_price)

    engine_ver = (
        p.engine_version
        if p.engine_version is not None
        else snap.get("engine_version", 2.0)
    )

    signal = Signal(
        symbol=p.symbol,
        timeframe=p.timeframe,
        pattern=p.pattern,
        strategy_name=p.strategy_name,
        direction=p.direction,
        score=p.signal_score,
        entry_price=actual_entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        rsi=snap.get("rsi"),
        volume_ratio=snap.get("volume_ratio"),
        atr_ratio=snap.get("atr_ratio"),
        regime=p.regime,
        candle_time=ensure_utc(p.candle_time),
        evaluated_at=now,
        engine_version=engine_ver,
        market_context={
            "entry": entry_ctx,
            "fill": {
                "fill_price": actual_entry,
                "touch_source": "paper_limit_touch",
            },
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
    db.add(signal)
    db.flush()

    feature = SignalFeature(
        signal_id=signal.id,
        rsi=snap.get("rsi"),
        volume_ratio=snap.get("volume_ratio"),
        atr_ratio=snap.get("atr_ratio"),
        ema_distance=snap.get("ema_distance"),
        regime=p.regime,
        trend_score=p.trend_score,
        momentum_score=p.momentum_score,
        volume_score=p.volume_score,
        pattern_score=p.pattern_score,
        mtf_score=p.mtf_score,
        penalty_norm=p.penalty,
        total_score=p.signal_score,
        rr=p.rr
    )
    db.add(feature)

    if p.scan_debug_id:
        debug = db.query(ScanDebug).get(p.scan_debug_id)
        if debug:
            debug.signal_id = signal.id

    if hasattr(p, "signal_id"):
        p.signal_id = signal.id

    db.commit()

    _notify_fill(p, signal, exec_result)

    print(
        f"✅ FILLED [PAPER]: {p.symbol} {p.direction} "
        f"@ {actual_entry:.6f} | {p.strategy_name}"
    )
    return signal


# ============================================================
# LIVE SIGNAL HELPERS
# ============================================================

def _create_live_signal_from_pending(db, p: PendingSignal, now, price_map: dict):
    """
    Create Signal lần đầu khi entry order có executed_qty > 0.
    Pending local vẫn WAIT nếu entry lifecycle chưa terminal.
    """
    snap = p.indicators_snapshot or {}
    mode = get_current_mode()

    btc_snap = get_or_build_hourly_snapshot()
    btc_price = price_map.get("BTCUSDT") if price_map else None
    entry_ctx = build_event_context(btc_snap, btc_price)

    engine_ver = (
        p.engine_version
        if p.engine_version is not None
        else snap.get("engine_version", 2.0)
    )

    exec_result = OrderResult(
        success=True,
        order_id=p.exchange_order_id,
        actual_entry=float(p.avg_fill_price or p.trigger_price),
        actual_quantity=float(p.executed_qty or 0),
        mode=mode.value,
        sl_order_id=p.sl_order_id,
        tp_order_id=p.tp_order_id,
    )

    signal = Signal(
        symbol=p.symbol,
        timeframe=p.timeframe,
        pattern=p.pattern,
        strategy_name=p.strategy_name,
        direction=p.direction,
        score=p.signal_score,
        entry_price=float(p.avg_fill_price or p.trigger_price),
        stop_loss=float(p.stop_loss),
        take_profit=float(p.take_profit),
        rsi=snap.get("rsi"),
        volume_ratio=snap.get("volume_ratio"),
        atr_ratio=snap.get("atr_ratio"),
        regime=p.regime,
        candle_time=ensure_utc(p.candle_time),
        evaluated_at=now,
        engine_version=engine_ver,
        market_context={
            "entry": entry_ctx,
            "pending_id": p.id,
            "execution": {
                "mode": mode.value,
                "order_id": p.exchange_order_id,
                "quantity": float(p.executed_qty or 0),
                "entry_exchange_status": p.exchange_status,
                "sl_order_id": p.sl_order_id,
                "tp_order_id": p.tp_order_id,
            }
        },
        trading_mode=mode.value
    )
    db.add(signal)
    db.flush()

    feature = SignalFeature(
        signal_id=signal.id,
        rsi=snap.get("rsi"),
        volume_ratio=snap.get("volume_ratio"),
        atr_ratio=snap.get("atr_ratio"),
        ema_distance=snap.get("ema_distance"),
        regime=p.regime,
        trend_score=p.trend_score,
        momentum_score=p.momentum_score,
        volume_score=p.volume_score,
        pattern_score=p.pattern_score,
        mtf_score=p.mtf_score,
        penalty_norm=p.penalty,
        total_score=p.signal_score,
        rr=p.rr
    )
    db.add(feature)

    if p.scan_debug_id:
        debug = db.query(ScanDebug).get(p.scan_debug_id)
        if debug:
            debug.signal_id = signal.id

    p.signal_id = signal.id
    p.accounted_qty = float(p.executed_qty or 0)

    db.commit()

    _notify_fill(p, signal, exec_result)

    print(
        f"✅ LIVE SIGNAL CREATED: {p.symbol} {p.direction} "
        f"| qty={p.executed_qty} avg={p.avg_fill_price}"
    )
    return signal


def _update_live_signal_from_pending(db, p: PendingSignal):
    """
    Nếu entry partial tăng thêm trong lúc signal còn OPEN:
    - update entry average / quantity trong market_context
    """
    if not p.signal_id:
        return

    signal = db.query(Signal).get(p.signal_id)
    if not signal:
        return

    if signal.status != "OPEN":
        # Theo design hiện tại 1 pending = 1 signal,
        # nếu signal đã đóng thì pending đáng ra phải được finalize rồi.
        print(f"⚠️ Signal {signal.id} not OPEN while pending {p.id} still syncing")
        return

    if p.avg_fill_price:
        signal.entry_price = float(p.avg_fill_price)

    ctx = dict(signal.market_context or {})
    exec_ctx = dict(ctx.get("execution") or {})
    exec_ctx["order_id"] = p.exchange_order_id
    exec_ctx["quantity"] = float(p.executed_qty or 0)
    exec_ctx["entry_exchange_status"] = p.exchange_status
    exec_ctx["sl_order_id"] = p.sl_order_id
    exec_ctx["tp_order_id"] = p.tp_order_id
    ctx["execution"] = exec_ctx
    signal.market_context = ctx

    p.accounted_qty = float(p.executed_qty or 0)

    db.commit()

    print(
        f"🔄 LIVE SIGNAL UPDATED: {p.symbol} "
        f"| qty={p.executed_qty} avg={p.avg_fill_price}"
    )


# ============================================================
# PAPER PATH
# ============================================================

def _process_single_paper(db, p: PendingSignal, price_map: dict, now):
    if ensure_utc(p.expire_at) < now:
        p.status = "CANCELLED"
        p.rejection_reason = "EXPIRED"
        db.commit()
        return

    current = price_map.get(p.symbol)
    if current is None:
        return
    current = float(current)

    try:
        dist_pct = (current - float(p.trigger_price)) / float(p.trigger_price) * 100
        """if abs(dist_pct) < 2.0:
            print(
                f"[PENDING CHECK][PAPER] id={p.id} {p.symbol} {p.direction} "
                f"current={current:.8f} trigger={float(p.trigger_price):.8f} "
                f"dist={dist_pct:+.4f}%"
            )"""
    except Exception:
        pass

    touched, fill_price, touch_source = _check_touch(p, current)
    if not touched:
        return

    result = validate_before_fill(p, current)
    if not result.passed:
        p.status = "REJECTED"
        p.rejection_reason = result.reason
        p.validation_details = result.details
        p.filled_at = now
        db.commit()
        print(f"🚫 REJECTED [PAPER]: {p.symbol} {p.direction} | {result.reason}")
        return

    cfg = get_runtime_config()
    max_open = cfg.get("MAX_OPEN_TRADES", 10)
    current_open = db.query(Signal).filter(Signal.status == "OPEN").count()
    if current_open >= max_open:
        print(
            f"⏸️ MAX OPEN [PAPER]: {p.symbol} {p.direction} "
            f"| {current_open}/{max_open} — keep WAIT"
        )
        return

    otf = get_open_trade_filter(cfg)
    atr_ratio = None
    if p.atr_value and p.trigger_price and float(p.trigger_price) > 0:
        atr_ratio = float(p.atr_value) / float(p.trigger_price)

    otf_ok, otf_reason = otf.check(
        symbol=p.symbol,
        direction=p.direction,
        strategy_name=p.strategy_name,
        pattern=p.pattern,
        timeframe=p.timeframe,
        regime=p.regime,
        score=p.signal_score or 0,
        ml_prob=p.ml_prob,
        components={
            "trend_score": p.trend_score or 0,
            "momentum_score": p.momentum_score or 0,
            "volume_score": p.volume_score or 0,
            "pattern_score": p.pattern_score or 0,
            "mtf_score": p.mtf_score or 0,
            "penalty_norm": p.penalty or 0,
        },
        atr_ratio=atr_ratio,
        db=db
    )
    if not otf_ok:
        print(f"⏸️ FILL OTF BLOCK [PAPER]: {p.symbol} {p.direction} | {otf_reason}")
        return

    exec_result = open_position(p, price_map, fill_price=fill_price)
    if not exec_result.success:
        p.status = "REJECTED"
        p.rejection_reason = f"EXEC_FAIL::{exec_result.error}"
        db.commit()
        print(f"❌ PAPER EXEC FAIL: {p.symbol} | {exec_result.error}")
        return

    _finalize_paper_fill(
        db=db,
        p=p,
        now=now,
        actual_entry=float(exec_result.actual_entry or p.trigger_price),
        stop_loss=float(p.stop_loss),
        take_profit=float(p.take_profit),
        exec_result=exec_result,
        price_map=price_map
    )


# ============================================================
# LIVE / TESTNET PATH
# ============================================================

def _process_single_live(db, p: PendingSignal, price_map: dict, now):
    cfg = get_runtime_config()

    # --------------------------------------------------------
    # PRE-PLACE
    # --------------------------------------------------------
    if not p.exchange_order_id:
        if ensure_utc(p.expire_at) < now:
            p.status = "CANCELLED"
            p.rejection_reason = "EXPIRED_BEFORE_PLACE"
            db.commit()
            return

        # OTF pre-place: fail => keep WAIT
        otf = get_open_trade_filter(cfg)
        atr_ratio = None
        if p.atr_value and p.trigger_price and float(p.trigger_price) > 0:
            atr_ratio = float(p.atr_value) / float(p.trigger_price)

        otf_ok, _ = otf.check(
            symbol=p.symbol,
            direction=p.direction,
            strategy_name=p.strategy_name,
            pattern=p.pattern,
            timeframe=p.timeframe,
            regime=p.regime,
            score=p.signal_score or 0,
            ml_prob=p.ml_prob,
            components={
                "trend_score": p.trend_score or 0,
                "momentum_score": p.momentum_score or 0,
                "volume_score": p.volume_score or 0,
                "pattern_score": p.pattern_score or 0,
                "mtf_score": p.mtf_score or 0,
                "penalty_norm": p.penalty or 0,
            },
            atr_ratio=atr_ratio,
            db=db
        )
        if not otf_ok:
            return

        current = price_map.get(p.symbol)
        if current is None:
            return

        result = validate_before_fill(p, float(current))
        if not result.passed:
            _mark_rejected(db, p, result.reason, result.details)
            print(f"🚫 LIVE PREFILL REJECTED: {p.symbol} {p.direction} | {result.reason}")
            return

        # Reprice chỉ 1 lần duy nhất
        if not getattr(p, "reprice_applied", False):
            limit_cfg = cfg.get("LIMIT_ORDER_CONFIG", {})
            if not limit_cfg.get("enabled", True):
                reprice_pct = 0.0
            else:
                reprice_pct = (
                    limit_cfg.get("entry_reprice_pct", {}).get(p.timeframe, 0.0) or 0.0
                )

            trig_new, sl_new, tp_new = _calc_repriced_triplet(p, reprice_pct)
            trig_new, sl_new, tp_new = _round_triplet_for_exchange(
                p.symbol, trig_new, sl_new, tp_new
            )

            p.trigger_price = trig_new
            p.stop_loss = sl_new
            p.take_profit = tp_new
            p.reprice_applied = True
            db.commit()

            print(
                f"🟡 REPRICE APPLIED ONCE: {p.symbol} {p.direction} "
                f"| trigger={p.trigger_price:.10f} | sl={p.stop_loss:.10f} tp={p.take_profit:.10f}"
            )

        # Place limit entry
        exec_result = place_limit_entry_order(p)
        if not exec_result.success:
            print(f"⚠️ LIMIT PLACE FAILED: {p.symbol} | {exec_result.error}")
            return

        p.exchange_order_id = exec_result.order_id
        p.exchange_status = "NEW"
        p.placed_at = now
        p.order_quantity = exec_result.actual_quantity
        p.last_exchange_sync_at = now
        db.commit()

        # Place algo exits ngay sau entry
        exit_ids = place_close_position_exit_orders(
            p.symbol,
            p.direction,
            float(p.stop_loss),
            float(p.take_profit)
        )
        p.sl_order_id = exit_ids.get("sl_order_id")
        p.tp_order_id = exit_ids.get("tp_order_id")
        db.commit()

        # Protection fail => rollback ngay
        if not p.sl_order_id or not p.tp_order_id:
            _rollback_on_protection_fail(
                db, p,
                "algo_exit_place_failed_after_entry_place"
            )
            return

        print(
            f"🟡 LIMIT ORDER PLACED: {p.symbol} {p.direction} "
            f"@ {float(p.trigger_price):.6f} | order_id={p.exchange_order_id} "
            f"| sl_algo={p.sl_order_id} tp_algo={p.tp_order_id}"
        )
        return

    # --------------------------------------------------------
    # POST-PLACE SYNC
    # --------------------------------------------------------
    order_info = get_entry_order_status(p.symbol, p.exchange_order_id)

    p.exchange_status = order_info.get("status", p.exchange_status)
    p.executed_qty = float(order_info.get("executed_qty") or p.executed_qty or 0)
    p.avg_fill_price = (
        float(order_info.get("avg_price"))
        if order_info.get("avg_price")
        else p.avg_fill_price
    )
    if order_info.get("orig_qty"):
        p.order_quantity = float(order_info["orig_qty"])
    p.last_exchange_sync_at = now
    db.commit()

    # Local expiry while entry still active
    if ensure_utc(p.expire_at) < now and not _is_terminal_exchange_status(p.exchange_status):
        cancel_entry_and_exits(p)

        order_info = get_entry_order_status(p.symbol, p.exchange_order_id)
        p.exchange_status = order_info.get("status", p.exchange_status)
        p.executed_qty = float(order_info.get("executed_qty") or p.executed_qty or 0)
        p.avg_fill_price = (
            float(order_info.get("avg_price"))
            if order_info.get("avg_price")
            else p.avg_fill_price
        )
        p.last_exchange_sync_at = now

        if (p.executed_qty or 0) > 0:
            p.status = "FILLED"
        else:
            p.status = "CANCELLED"
            p.rejection_reason = "EXPIRED_NO_FILL"
            cancel_entry_and_exits(p)

        db.commit()

        print(
            f"🗑️ ENTRY EXPIRED: {p.symbol} "
            f"| executed={p.executed_qty} exchange_status={p.exchange_status}"
        )
        return

    # Nếu đã có fill mà chưa có algo exit IDs thì:
    # 1) check exchange xem algo orders đã tồn tại chưa
    # 2) nếu chưa có thì đặt mới
    # 3) nếu đặt thất bại => rollback protection
    if (p.executed_qty or 0) > 0 and (not p.sl_order_id or not p.tp_order_id):
        should_place = True

        try:
            existing_algo = get_open_algo_orders(p.symbol)

            has_sl = any(
                o.get("orderType") == "STOP_MARKET"
                for o in existing_algo
            )
            has_tp = any(
                o.get("orderType") == "TAKE_PROFIT_MARKET"
                for o in existing_algo
            )

            if has_sl and has_tp:
                should_place = False

                for o in existing_algo:
                    if o.get("orderType") == "STOP_MARKET" and not p.sl_order_id:
                        p.sl_order_id = str(o.get("algoId", ""))
                    if o.get("orderType") == "TAKE_PROFIT_MARKET" and not p.tp_order_id:
                        p.tp_order_id = str(o.get("algoId", ""))
                db.commit()

        except Exception as e:
            print(f"[PENDING] Check existing algo exits error {p.symbol}: {e}")

        if should_place:
            exit_ids = place_close_position_exit_orders(
                p.symbol,
                p.direction,
                float(p.stop_loss),
                float(p.take_profit)
            )
            p.sl_order_id = exit_ids.get("sl_order_id")
            p.tp_order_id = exit_ids.get("tp_order_id")
            db.commit()

            if not p.sl_order_id or not p.tp_order_id:
                _rollback_on_protection_fail(
                    db, p,
                    "missing_algo_exit_after_fill"
                )
                return

    # Delta fill handling
    executed_qty  = float(p.executed_qty or 0)
    accounted_qty = float(p.accounted_qty or 0)
    delta_qty     = executed_qty - accounted_qty

    if delta_qty > 0:
        if not p.signal_id:
            _create_live_signal_from_pending(db, p, now, price_map)
        else:
            _update_live_signal_from_pending(db, p)

    # Terminal entry lifecycle
    if _is_terminal_exchange_status(p.exchange_status):
        if (p.executed_qty or 0) > 0:
            p.status = "FILLED"
        else:
            if p.exchange_status == "REJECTED":
                p.status = "REJECTED"
                p.rejection_reason = "BINANCE::REJECTED"
            else:
                p.status = "CANCELLED"
                p.rejection_reason = f"BINANCE::{p.exchange_status}"

            cancel_entry_and_exits(p)

        db.commit()
        return


# ============================================================
# MAIN ENTRYPOINT
# ============================================================

def process_pending_signals(price_map: Optional[Dict[str, float]] = None):
    with SessionLocal() as db:
        now = utc_now()
        mode = get_current_mode()

        _update_pending_heartbeat(db)

        pendings = db.query(PendingSignal).filter(
            PendingSignal.status == "WAIT"
        ).all()

        if not pendings:
            return

        if mode == TradingMode.PAPER and not price_map:
            from app.services.binance_service import get_all_prices
            price_map = get_all_prices()

        if mode != TradingMode.PAPER and not price_map:
            try:
                from app.services.price_feed import get_all_current_prices
                price_map = get_all_current_prices()
            except Exception:
                price_map = {}

        for p in pendings:
            try:
                if mode == TradingMode.PAPER:
                    _process_single_paper(db, p, price_map or {}, now)
                else:
                    _process_single_live(db, p, price_map or {}, now)
            except Exception as e:
                db.rollback()
                print(f"❌ Pending [{p.id}] {p.symbol}: {type(e).__name__} - {e}")


# ============================================================
# NOTIFY
# ============================================================

def _notify_fill(p, signal, exec_result):
    try:
        from app.services.telegram_service import send_telegram

        rr_text = f"{p.rr:.2f}" if p.rr else "N/A"
        prob = p.ml_prob
        score_tag = " 🌟" if (p.signal_score or 0) >= 8 else ""
        conf_tag = " 🔥" if prob and prob >= 0.7 else ""
        tf_icon = {"15m": "⚡", "1h": "🕐", "4h": "🕓"}.get(p.timeframe, "🕒")

        mode_icon = {
            "PAPER": "📋",
            "TESTNET": "🧪",
            "LIVE": "💰"
        }.get(exec_result.mode, "📋")

        duration = {"15m": 15, "1h": 60, "4h": 240, "1d": 1440}.get(p.timeframe, 15)
        close_time = ensure_utc(p.candle_time) + timedelta(minutes=duration) if p.candle_time else utc_now()
        local_time = to_vn(close_time)

        entry_display = exec_result.actual_entry or p.trigger_price
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
            f"<b>Trigger:</b>   {float(p.trigger_price):.6f}\n"
            f"<b>Entry:</b>     {float(entry_display):.6f}\n"
            f"<b>SL:</b>        {float(p.stop_loss):.6f}\n"
            f"<b>TP:</b>        {float(p.take_profit):.6f}\n"
            f"<b>RR:</b>        {rr_text}"
            f"{qty_text}{lev_text}\n\n"
            f"<b>Candle:</b>    {local_time.strftime('%Y-%m-%d %H:%M:%S')} GMT+7"
        )
        send_telegram(msg)

    except Exception as e:
        print(f"[NOTIFY FILL] {e}")