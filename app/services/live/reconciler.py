from typing import Optional, Tuple, Dict, Any, Iterable
import time as _time
from sqlalchemy import text

from app.core.time_utils import utc_now, ensure_utc
from app.core.trading_mode import get_current_mode
from app.db.session import SessionLocal
from app.db.models import PendingSignal, Signal, SignalFeature, ScanDebug, ExecutionCommand
from app.services.execution_service import (
    cancel_order_by_id,
    place_algo_stop_market_close_position,
    place_algo_take_profit_market_close_position,
    get_executor,
)
from app.services.config_service import get_runtime_config
from app.services.live.snapshot_service import build_symbol_snapshot, SymbolSnapshot
from app.services.live.locks import live_symbol_lock
from app.services.live.command_service import (
    CMD_MANUAL_CLOSE,
    CMD_MANUAL_CANCEL_PENDING,
    CMD_KILL_SWITCH,
    CMD_EMERGENCY_CLOSE,
    CMD_PROTECTION_REPLACE,
    COMMAND_REQUESTED,
    COMMAND_SENT,
    confirm_commands_for_symbol,
    has_open_command,
    request_emergency_close,
)
from app.services.live.capacity_service import (
    get_active_live_symbols,
    get_zero_fill_resting_pending_candidates,
    is_pending_exchange_active,
)
from app.services.btc_context_cache import (
    get_or_build_hourly_snapshot,
    build_event_context,
)
from app.services.outcome_service import save_trade_outcome

# Throttle: symbol resting (chưa fill) chỉ cần reconcile mỗi 5s
_symbol_last_reconcile = {}
RESTING_RECONCILE_INTERVAL = 5.0


ENTRY_TERMINAL_STATUSES = {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}
MANUAL_LIKE_REASONS = {"MANUAL", "KILL_SWITCH", "SYSTEM_CRASH"}


def reconcile_all_active_symbols():
    with SessionLocal() as db:
        symbols = _get_active_symbols(db)

    for symbol in symbols:
        reconcile_symbol(symbol)

    # HARD-CAP enforcement:
    # Sau khi reconcile xong toàn bộ active symbols,
    # nếu số active live symbols vẫn vượt cap,
    # chủ động hủy bớt resting zero-fill entries.
    _enforce_live_hard_cap()


def reconcile_symbol(symbol: str):
    with live_symbol_lock(symbol, blocking=False) as acquired:
        if not acquired:
            return

        with SessionLocal() as db:
            pending, signal, commands = _load_aggregate(db, symbol)

            if not pending and not signal and not commands:
                return

            # ── Throttle check cho resting symbols ───────
            has_fill = pending and float(pending.executed_qty or 0) > 0
            has_position = signal and signal.status == "OPEN"
            has_commands = bool(commands)
            is_active = has_fill or has_position or has_commands

            if not is_active:
                now_ts = _time.time()
                last_ts = _symbol_last_reconcile.get(symbol, 0)
                if now_ts - last_ts < RESTING_RECONCILE_INTERVAL:
                    db.commit()
                    return
                _symbol_last_reconcile[symbol] = now_ts

            # ── Build snapshot ───────────────────────────
            # Chỉ cần algo detail khi đã có fill hoặc position
            need_algo = has_fill or has_position

            snapshot = build_symbol_snapshot(
                symbol,
                pending=pending,
                need_algo_detail=need_algo,
            )
            if not snapshot.ok:
                print(f"[LIVE RECONCILE] snapshot fail {symbol}: {snapshot.error}")
                return

            if pending and pending.exchange_order_id:
                _sync_pending_from_snapshot(db, pending, snapshot)

            if pending and float(pending.executed_qty or 0) > 0:
                if not signal:
                    signal = _create_signal_from_pending(db, pending, snapshot)
                else:
                    _update_signal_from_pending(db, signal, pending, snapshot)

            if signal and snapshot.position.exists:
                _ensure_protection(db, signal, pending, snapshot)

            if pending:
                _finalize_entry_lifecycle(db, pending, snapshot)

            if signal and signal.status == "OPEN" and not snapshot.position.exists:
                _finalize_signal_close(db, signal, pending, snapshot, commands)

            if pending and pending.status in ("CANCELLED", "FILLED", "REJECTED"):
                confirm_commands_for_symbol(
                    db,
                    symbol,
                    [CMD_MANUAL_CANCEL_PENDING],
                    result_payload={"pending_status": pending.status},
                )

            db.commit()


def _get_active_symbols(db):
    symbols = set(
        row[0] for row in db.query(PendingSignal.symbol).filter(
            PendingSignal.status == "WAIT"
        ).distinct().all()
    )

    symbols |= set(
        row[0] for row in db.query(Signal.symbol).filter(
            Signal.status == "OPEN"
        ).distinct().all()
    )

    symbols |= set(
        row[0] for row in db.query(ExecutionCommand.symbol).filter(
            ExecutionCommand.status.in_([COMMAND_REQUESTED, COMMAND_SENT])
        ).distinct().all()
    )

    return sorted(s for s in symbols if s)


def _load_aggregate(db, symbol: str):
    pending = db.query(PendingSignal).filter(
        PendingSignal.symbol == symbol,
        PendingSignal.status == "WAIT"
    ).order_by(PendingSignal.created_at.asc()).first()

    signal = db.query(Signal).filter(
        Signal.symbol == symbol,
        Signal.status == "OPEN"
    ).order_by(Signal.created_at.asc()).first()

    if not pending and signal:
        pending = db.query(PendingSignal).filter(
            PendingSignal.signal_id == signal.id
        ).order_by(PendingSignal.created_at.desc()).first()

    commands = db.query(ExecutionCommand).filter(
        ExecutionCommand.symbol == symbol,
        ExecutionCommand.status.in_([COMMAND_REQUESTED, COMMAND_SENT]),
    ).order_by(ExecutionCommand.requested_at.desc()).all()

    return pending, signal, commands


def _sync_pending_from_snapshot(db, pending: PendingSignal, snapshot: SymbolSnapshot):
    pending.exchange_status = snapshot.entry.status or pending.exchange_status
    pending.executed_qty = float(snapshot.entry.executed_qty or pending.executed_qty or 0)
    pending.order_quantity = float(snapshot.entry.orig_qty or pending.order_quantity or 0)

    if snapshot.entry.avg_fill_price:
        pending.avg_fill_price = float(snapshot.entry.avg_fill_price)

    pending.last_exchange_sync_at = snapshot.snapshot_time
    db.flush()


def _create_signal_from_pending(db, pending: PendingSignal, snapshot: SymbolSnapshot) -> Signal:
    if pending.signal_id:
        signal = db.query(Signal).get(pending.signal_id)
        if signal:
            return signal

    snap = pending.indicators_snapshot or {}
    btc_snap = get_or_build_hourly_snapshot()
    btc_price = None
    entry_ctx = build_event_context(btc_snap, btc_price)
    mode = get_current_mode()

    signal = Signal(
        symbol=pending.symbol,
        timeframe=pending.timeframe,
        pattern=pending.pattern,
        strategy_name=pending.strategy_name,
        direction=pending.direction,
        score=pending.signal_score,
        entry_price=float(pending.avg_fill_price or pending.trigger_price),
        stop_loss=float(pending.stop_loss),
        take_profit=float(pending.take_profit),
        quantity=float(pending.executed_qty or 0),
        rsi=snap.get("rsi"),
        volume_ratio=snap.get("volume_ratio"),
        atr_ratio=snap.get("atr_ratio"),
        regime=pending.regime,
        candle_time=ensure_utc(pending.candle_time),
        evaluated_at=utc_now(),
        engine_version=pending.engine_version,
        market_context={
            "entry": entry_ctx,
            "pending_id": pending.id,
            "execution": {
                "mode": mode.value,
                "order_id": pending.exchange_order_id,
                "quantity": float(pending.executed_qty or 0),
                "entry_exchange_status": pending.exchange_status,
                "sl_order_id": pending.sl_order_id,
                "tp_order_id": pending.tp_order_id,
            }
        },
        trading_mode=mode.value,
    )
    db.add(signal)
    db.flush()

    feature = SignalFeature(
        signal_id=signal.id,
        rsi=snap.get("rsi"),
        volume_ratio=snap.get("volume_ratio"),
        atr_ratio=snap.get("atr_ratio"),
        ema_distance=snap.get("ema_distance"),
        regime=pending.regime,
        trend_score=pending.trend_score,
        momentum_score=pending.momentum_score,
        volume_score=pending.volume_score,
        pattern_score=pending.pattern_score,
        mtf_score=pending.mtf_score,
        penalty_norm=pending.penalty,
        total_score=pending.signal_score,
        rr=pending.rr,
    )
    db.add(feature)

    if pending.scan_debug_id:
        debug = db.query(ScanDebug).get(pending.scan_debug_id)
        if debug:
            debug.signal_id = signal.id

    pending.signal_id = signal.id
    pending.accounted_qty = float(pending.executed_qty or 0)

    print(
        f"✅ LIVE SIGNAL CREATED: {pending.symbol} {pending.direction} "
        f"| signal_id={signal.id} qty={pending.executed_qty} avg={pending.avg_fill_price}"
    )

    db.flush()
    return signal


def _update_signal_from_pending(db, signal: Signal, pending: PendingSignal, snapshot: SymbolSnapshot):
    signal.entry_price = float(pending.avg_fill_price or signal.entry_price or pending.trigger_price)
    signal.quantity = float(pending.executed_qty or signal.quantity or 0)

    ctx = dict(signal.market_context or {})
    exec_ctx = dict(ctx.get("execution") or {})
    exec_ctx["order_id"] = pending.exchange_order_id
    exec_ctx["quantity"] = float(pending.executed_qty or 0)
    exec_ctx["entry_exchange_status"] = pending.exchange_status
    exec_ctx["sl_order_id"] = pending.sl_order_id
    exec_ctx["tp_order_id"] = pending.tp_order_id
    ctx["execution"] = exec_ctx
    signal.market_context = ctx

    pending.accounted_qty = float(pending.executed_qty or 0)
    db.flush()


def _find_algo_by_type(open_algo_orders, order_type: str):
    for o in open_algo_orders or []:
        if str(o.get("orderType", "")).upper() == order_type.upper():
            return o
    return None


def _ensure_protection(db, signal: Signal, pending: Optional[PendingSignal], snapshot: SymbolSnapshot):
    if not pending:
        return

    executor = get_executor()
    if not executor or not executor.ready:
        return

    sl_open = _find_algo_by_type(snapshot.open_algo_orders, "STOP_MARKET")
    tp_open = _find_algo_by_type(snapshot.open_algo_orders, "TAKE_PROFIT_MARKET")

    if sl_open and not pending.sl_order_id:
        pending.sl_order_id = str(sl_open.get("algoId", ""))
    if tp_open and not pending.tp_order_id:
        pending.tp_order_id = str(tp_open.get("algoId", ""))

    if sl_open is None:
        try:
            symbol_info = executor.get_symbol_info(pending.symbol)
            sl_price = executor.round_price(pending.symbol, float(pending.stop_loss), symbol_info)
            sl_resp = place_algo_stop_market_close_position(
                symbol=pending.symbol,
                direction=pending.direction,
                trigger_price=sl_price,
            )
            pending.sl_order_id = str(sl_resp.get("algoId", "")) if sl_resp else None
        except Exception as e:
            print(f"[LIVE RECONCILE] place missing SL fail {pending.symbol}: {e}")

    if tp_open is None:
        try:
            symbol_info = executor.get_symbol_info(pending.symbol)
            tp_price = executor.round_price(pending.symbol, float(pending.take_profit), symbol_info)
            tp_resp = place_algo_take_profit_market_close_position(
                symbol=pending.symbol,
                direction=pending.direction,
                trigger_price=tp_price,
            )
            pending.tp_order_id = str(tp_resp.get("algoId", "")) if tp_resp else None
        except Exception as e:
            print(f"[LIVE RECONCILE] place missing TP fail {pending.symbol}: {e}")

    if not pending.sl_order_id or not pending.tp_order_id:
        if not has_open_command(db, pending.symbol, [CMD_EMERGENCY_CLOSE]):
            print(f"🚨 PROTECTION MISSING => EMERGENCY CLOSE {pending.symbol}")
            request_emergency_close(
                symbol=pending.symbol,
                signal_id=signal.id if signal else None,
                pending_id=pending.id if pending else None,
                reason="MISSING_PROTECTION"
            )


def _finalize_entry_lifecycle(db, pending: PendingSignal, snapshot: SymbolSnapshot):
    status = str(snapshot.entry.status or pending.exchange_status or "").upper()
    executed = float(pending.executed_qty or 0)
    now = utc_now()

    # 1. Thụ động: xử lý nếu exchange đã báo terminal
    if status in ENTRY_TERMINAL_STATUSES:
        if executed > 0:
            pending.status = "FILLED"
            if pending.filled_at is None:
                pending.filled_at = now
        else:
            if status == "REJECTED":
                pending.status = "REJECTED"
                pending.rejection_reason = "BINANCE::REJECTED"
            else:
                pending.status = "CANCELLED"
                pending.rejection_reason = f"BINANCE::{status or 'CANCELED'}"
        db.flush()
        return

    # 2. Chủ động: nếu chưa terminal nhưng đã quá expire_at
    if pending.expire_at and ensure_utc(pending.expire_at) < now:

        # RISK #12 guard: chỉ gửi cancel 1 lần
        already_sent = (
            pending.last_place_error
            and "EXPIRE_CANCEL_SENT" in str(pending.last_place_error)
        )

        if not already_sent:
            print(f"⏰ LIVE ENTRY EXPIRED: {pending.symbol} | pending={pending.id} | Cancelling...")

            try:
                ok = cancel_order_by_id(pending.symbol, pending.exchange_order_id)
                if ok:
                    pending.last_place_error = "EXPIRE_CANCEL_SENT"
                    pending.last_exchange_sync_at = now
                    print(f"✅ Cancel command sent for expired entry: {pending.symbol}")
                else:
                    print(f"⚠️ Cancel command returned False for expired entry: {pending.symbol}")
            except Exception as e:
                print(f"❌ Expire cancel failed for {pending.symbol}: {e}")

            db.flush()


def _is_algo_triggered(algo) -> bool:
    if not algo:
        return False

    status = str(algo.algo_status or "").upper()

    if algo.trigger_time:
        return True

    if algo.actual_order_id:
        return True

    if algo.actual_qty and float(algo.actual_qty or 0) > 0:
        return True

    return status in {"TRIGGERED", "FILLED", "SUCCESS", "FINISHED", "EXECUTED"}


def _manual_command_reason(commands) -> Optional[Tuple[str, Optional[float]]]:
    if not commands:
        return None

    for cmd in commands:
        payload = cmd.result_payload or {}
        req = cmd.request_payload or {}

        actual_exit = payload.get("actual_exit_price")
        price_hint = payload.get("price_hint") or req.get("price_hint")

        if actual_exit is not None:
            try:
                actual_exit = float(actual_exit)
                if actual_exit <= 0:
                    actual_exit = None
            except Exception:
                actual_exit = None

        if price_hint is not None:
            try:
                price_hint = float(price_hint)
                if price_hint <= 0:
                    price_hint = None
            except Exception:
                price_hint = None

        final_price = actual_exit or price_hint

        if cmd.command_type == CMD_MANUAL_CLOSE:
            return "MANUAL", final_price

        if cmd.command_type == CMD_KILL_SWITCH:
            close_raw = payload.get("close_raw") or {}
            raw_price = None
            if isinstance(close_raw, dict):
                raw_price = float(close_raw.get("avgPrice", 0) or 0) or None
            return "KILL_SWITCH", raw_price or final_price

        if cmd.command_type == CMD_EMERGENCY_CLOSE:
            return f"EMERGENCY_CLOSE::{req.get('reason', 'UNKNOWN')}", final_price

        if cmd.command_type == CMD_PROTECTION_REPLACE:
            return f"PROTECTION_REPLACE_FAILED::{req.get('reason', 'UNKNOWN')}", final_price

    return None


def _derive_close_reason(
    signal: Signal,
    pending: Optional[PendingSignal],
    snapshot: SymbolSnapshot,
    commands
) -> Tuple[str, float]:
    cmd_reason = _manual_command_reason(commands)
    if cmd_reason:
        reason, exit_price = cmd_reason
        if exit_price and float(exit_price) > 0:
            return reason, float(exit_price)

        # HOTFIX:
        # Không fallback về entry price nữa.
        # Ưu tiên current market/mark price.
        return reason, _get_best_exit_price(signal.symbol, fallback=float(signal.entry_price or 0))

    if _is_algo_triggered(snapshot.tp_algo):
        price = (
            float(snapshot.tp_algo.actual_price)
            if snapshot.tp_algo and snapshot.tp_algo.actual_price
            else float(signal.take_profit or 0)
        )
        return "TP", price

    if _is_algo_triggered(snapshot.sl_algo):
        price = (
            float(snapshot.sl_algo.actual_price)
            if snapshot.sl_algo and snapshot.sl_algo.actual_price
            else float(signal.stop_loss or 0)
        )
        return "SL", price

    # fallback cuối cùng
    return "EXCHANGE_CLOSE_UNKNOWN", _get_best_exit_price(
        signal.symbol,
        fallback=float(signal.entry_price or 0)
    )


def _is_manual_like_reason(reason: str) -> bool:
    if not reason:
        return False
    if reason in MANUAL_LIKE_REASONS:
        return True
    return reason.startswith("EMERGENCY_CLOSE::") or reason.startswith("PROTECTION_REPLACE_FAILED::")


def _cleanup_after_close(signal: Signal, pending: Optional[PendingSignal], snapshot: SymbolSnapshot):
    if not pending:
        return

    cancel_order_by_id(signal.symbol, pending.exchange_order_id)
    cancel_order_by_id(signal.symbol, pending.sl_order_id)
    cancel_order_by_id(signal.symbol, pending.tp_order_id)

    if float(pending.executed_qty or 0) > 0:
        pending.status = "FILLED"
        if pending.filled_at is None:
            pending.filled_at = utc_now()
    else:
        pending.status = "CANCELLED"


def _notify_live_close(signal: Signal):
    try:
        from app.services.telegram_service import send_telegram

        result = float(signal.result_percent or 0)
        status = signal.status

        if status == "MANUAL":
            icon = "🛑"
            status_text = "MANUAL ⚪"
        else:
            icon = "🎉" if result > 0 else "😢"
            status_text = "WIN 🟢" if result > 0 else "LOSS 🔴"

        msg = (
            f"{icon} <b>TRADE CLOSED — {status_text}</b>\n\n"
            f"💰 Mode: LIVE\n"
            f"<b>Symbol:</b>    {signal.symbol}\n"
            f"<b>Strategy:</b>  {signal.strategy_name}\n"
            f"<b>Direction:</b> {signal.direction}\n"
            f"<b>TF:</b>        {signal.timeframe}\n\n"
            f"<b>Entry:</b>     {float(signal.entry_price):.4f}\n"
            f"<b>Exit:</b>      {float(signal.exit_price):.4f}\n"
            f"<b>Qty:</b>       {float(signal.quantity or 0):.6f}\n"
            f"<b>Result:</b>    {result:+.2f}%\n"
            f"<b>Reason:</b>    {signal.exit_reason}"
        )
        send_telegram(msg)
    except Exception as e:
        print(f"[LIVE CLOSE NOTIFY] {e}")


def _finalize_signal_close(db, signal: Signal, pending: Optional[PendingSignal], snapshot: SymbolSnapshot, commands):
    reason, exit_price = _derive_close_reason(signal, pending, snapshot, commands)

    signal.exit_reason = reason
    signal.exit_time = utc_now()
    signal.exit_price = float(exit_price)

    entry = float(signal.entry_price or 0)
    if entry > 0:
        if signal.direction == "LONG":
            result = ((float(signal.exit_price) - entry) / entry) * 100
        else:
            result = ((entry - float(signal.exit_price)) / entry) * 100
    else:
        result = 0.0

    signal.result_percent = result

    if _is_manual_like_reason(reason):
        signal.status = "MANUAL"
    else:
        signal.status = "WIN" if result > 0 else "LOSS"

    _cleanup_after_close(signal, pending, snapshot)

     # Outcome analytics: chạy deferred, không block reconcile critical path
    feature = db.query(SignalFeature).filter(
        SignalFeature.signal_id == signal.id
    ).first()

    if feature:
        _schedule_outcome_save(signal.id)

    confirm_commands_for_symbol(
        db,
        signal.symbol,
        [CMD_MANUAL_CLOSE, CMD_KILL_SWITCH, CMD_EMERGENCY_CLOSE, CMD_PROTECTION_REPLACE],
        result_payload={
            "signal_status": signal.status,
            "exit_reason": signal.exit_reason,
            "exit_price": float(signal.exit_price or 0),
        }
    )

    print(
        f"✅ LIVE SIGNAL CLOSED: {signal.symbol} "
        f"| reason={signal.exit_reason} status={signal.status} "
        f"| exit={signal.exit_price}"
    )

    _notify_live_close(signal)

import threading

# ── Deferred outcome queue ────────────────────────────────────
_outcome_queue: list = []
_outcome_queue_lock = threading.Lock()


def _schedule_outcome_save(signal_id: int):
    """
    Enqueue signal_id để save outcome sau.
    Không block reconcile loop.
    """
    with _outcome_queue_lock:
        if signal_id not in _outcome_queue:
            _outcome_queue.append(signal_id)

def _get_best_exit_price(symbol: str, fallback: Optional[float] = None) -> float:
    try:
        from app.services.price_feed import get_current_price
        px = get_current_price(symbol)
        if px is not None:
            px = float(px)
            if px > 0:
                return px
    except Exception:
        pass

    try:
        from app.services.binance_service import get_all_prices
        px = get_all_prices().get(symbol)
        if px is not None:
            px = float(px)
            if px > 0:
                return px
    except Exception:
        pass

    return float(fallback or 0)

def backfill_missing_outcomes(limit: int = 20):
    """
    Guarantee layer:
    Tìm mọi signal đã đóng nhưng chưa có outcome, rồi save bù.

    Áp dụng cho:
    - WIN
    - LOSS
    - MANUAL
    """
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT s.id
            FROM signals s
            LEFT JOIN trade_outcome_analytics t
              ON t.signal_id = s.id
            WHERE s.status IN ('WIN', 'LOSS', 'MANUAL')
              AND s.exit_time IS NOT NULL
              AND s.exit_price IS NOT NULL
              AND t.signal_id IS NULL
            ORDER BY s.exit_time DESC
            LIMIT :limit
        """), {"limit": limit}).fetchall()

        if not rows:
            return

        ids = [r[0] for r in rows]

    from app.services.outcome_service import save_trade_outcome

    for signal_id in ids:
        try:
            with SessionLocal() as db:
                signal = db.query(Signal).get(signal_id)
                if not signal:
                    continue

                feature = db.query(SignalFeature).filter(
                    SignalFeature.signal_id == signal_id
                ).first()

                # feature có thể thiếu, vẫn cho save
                save_trade_outcome(db, signal, feature)
                db.commit()

        except Exception as e:
            print(f"[OUTCOME BACKFILL] signal_id={signal_id}: {type(e).__name__}: {e}")

def run_deferred_outcomes():
    """
    Gọi từ advisory loop hoặc background task riêng.
    Drain outcome queue, fetch klines, save analytics.
    """
    with _outcome_queue_lock:
        pending_ids = list(_outcome_queue)
        _outcome_queue.clear()

    if not pending_ids:
        return

    from app.services.outcome_service import save_trade_outcome
    from app.db.models import Signal, SignalFeature

    for signal_id in pending_ids:
        try:
            with SessionLocal() as db:
                signal = db.query(Signal).get(signal_id)
                if not signal:
                    continue

                feature = db.query(SignalFeature).filter(
                    SignalFeature.signal_id == signal_id
                ).first()

                if feature:
                    save_trade_outcome(db, signal, feature)
                    db.commit()

        except Exception as e:
            print(f"[LIVE OUTCOME DEFERRED] signal_id={signal_id}: {type(e).__name__}: {e}")

def _enforce_live_hard_cap():
    """
    HARD-CAP cho LIVE:
    - Count DISTINCT active live symbols:
        + OPEN signals
        + placed WAIT pendings chưa terminal
    - Nếu vượt MAX_OPEN_TRADES:
        + chỉ hủy các resting zero-fill entries
        + ưu tiên hủy các lệnh mới nhất trước
        + KHÔNG tự đóng vị thế đang mở
    """
    cfg = get_runtime_config()
    cap = int(cfg.get("MAX_OPEN_TRADES", 10) or 10)

    with SessionLocal() as db:
        active_symbols = get_active_live_symbols(db)
        active_count = len(active_symbols)

        if active_count <= cap:
            return

        overflow = active_count - cap
        candidates = get_zero_fill_resting_pending_candidates(db)

    print(
        f"⚠️ LIVE HARD CAP EXCEEDED: active_live={active_count}/{cap} "
        f"| overflow={overflow} | trying to cancel newest zero-fill resting entries"
    )

    cancelled = 0
    touched_symbols = set()

    for item in candidates:
        if cancelled >= overflow:
            break

        if item.symbol in touched_symbols:
            continue

        with live_symbol_lock(item.symbol, blocking=False) as acquired:
            if not acquired:
                continue

            with SessionLocal() as db:
                p = (
                    db.query(PendingSignal)
                    .filter(PendingSignal.id == item.id)
                    .with_for_update()
                    .first()
                )
                if not p:
                    continue

                if not is_pending_exchange_active(p):
                    db.commit()
                    continue

                if float(p.executed_qty or 0) > 0:
                    # đã có fill thì không được hủy vì hard-cap
                    db.commit()
                    continue

                print(
                    f"🚫 LIVE HARD CAP CANCEL: {p.symbol} {p.direction} "
                    f"| pending={p.id} order_id={p.exchange_order_id}"
                )

                ok = cancel_order_by_id(p.symbol, p.exchange_order_id)

                if ok:
                    # marker tạm để nhìn log/query dễ hơn;
                    # terminal state thật sẽ do reconcile sau khi exchange xác nhận cancel
                    p.last_place_error = "CAPACITY_HARD_CAP_CANCEL_REQUESTED"
                    p.last_exchange_sync_at = utc_now()
                    db.commit()

                    cancelled += 1
                    touched_symbols.add(p.symbol)
                else:
                    db.commit()

    if cancelled < overflow:
        remaining = overflow - cancelled
        print(
            f"⚠️ LIVE HARD CAP NOT FULLY ENFORCED: "
            f"remaining_overflow={remaining} "
            f"| likely because cap is already consumed by OPEN positions "
            f"or some symbols were locked/became non-candidates"
        )

        