from typing import Optional, Tuple, Dict, Any, Iterable
import time as _time
from sqlalchemy import text

from app.core.time_utils import utc_now, ensure_utc
from app.core.trading_mode import get_current_mode
from app.db.session import SessionLocal
from app.db.models import PendingSignal, Signal, SignalFeature, ScanDebug, ExecutionCommand
from app.services.live.capacity_service import is_exchange_terminal_status 
from app.services.execution_service import (
    cancel_order_by_id,
    place_algo_stop_market_close_position,
    place_algo_take_profit_market_close_position,
    get_executor,
)
from app.services.execution_service import get_open_algo_orders
from app.services.live.protection_service import (
    set_breakeven_retry_backoff,
    clear_breakeven_retry_backoff,
    mark_breakeven_applied,
)
from app.services.config_service import get_runtime_config
from app.services.live.capacity_service import (
    get_capacity_snapshot,
    get_new_zero_fill_cancel_candidates,
)

from app.services.live.protection_service import (
    set_breakeven_retry_backoff,
    clear_breakeven_retry_backoff,
    mark_breakeven_applied,
    mark_protection_changed,
    protection_change_cooldown_active,
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
    COMMAND_CONFIRMED,
    COMMAND_FAILED,
    get_latest_open_command,
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


def _get_open_protection_replace_command(commands):
    if not commands:
        return None

    for cmd in commands:
        if cmd.command_type == CMD_PROTECTION_REPLACE and cmd.status in (
            COMMAND_REQUESTED,
            COMMAND_SENT,
        ):
            return cmd

    return None

def _is_command_timed_out(cmd, timeout_seconds: int = 120) -> bool:
    if not cmd or not cmd.requested_at:
        return False

    try:
        age = (utc_now() - ensure_utc(cmd.requested_at)).total_seconds()
        return age > timeout_seconds
    except Exception:
        return False

def _process_protection_replace_command(db, signal: Signal, pending: Optional[PendingSignal], snapshot: SymbolSnapshot, commands):
    cmd = _get_open_protection_replace_command(commands)
    if not cmd or not signal or signal.status != "OPEN":
        return

    req = dict(cmd.request_payload or {})
    res = dict(cmd.result_payload or {})

    # Set phase mặc định
    phase = res.get("phase") or cmd.status or "REQUESTED"
    target_sl = float(req.get("new_sl_price") or 0)

    # Timeout guard
    if _is_command_timed_out(cmd, timeout_seconds=120):
        cmd.status = COMMAND_FAILED
        cmd.error_message = "TIMEOUT"
        res["phase"] = "FAILED_TIMEOUT"
        cmd.result_payload = res
        set_breakeven_retry_backoff(signal, "TIMEOUT")
        db.flush()
        return

    # Guard 1: invalid target
    if target_sl <= 0:
        cmd.status = COMMAND_FAILED
        cmd.error_message = "INVALID_TARGET_SL"
        res["phase"] = "FAILED_INVALID_TARGET"
        cmd.result_payload = res
        set_breakeven_retry_backoff(signal, "INVALID_TARGET_SL")
        db.flush()
        return

    # Guard 2: no pending linked
    if not pending:
        cmd.status = COMMAND_FAILED
        cmd.error_message = "NO_PENDING_LINKED"
        res["phase"] = "FAILED_NO_PENDING"
        cmd.result_payload = res
        set_breakeven_retry_backoff(signal, "NO_PENDING_LINKED")
        db.flush()
        return

    # Guard 3: nếu không còn position thì command này hết ý nghĩa
    if not snapshot.position.exists:
        cmd.status = COMMAND_FAILED
        cmd.error_message = "NO_POSITION"
        res["phase"] = "FAILED_NO_POSITION"
        cmd.result_payload = res
        set_breakeven_retry_backoff(signal, "NO_POSITION")
        db.flush()
        return

    # Guard 4: timeout command
    if _is_command_timed_out(cmd, timeout_seconds=120):
        cmd.status = COMMAND_FAILED
        cmd.error_message = "TIMEOUT"
        res["phase"] = "FAILED_TIMEOUT"
        cmd.result_payload = res
        set_breakeven_retry_backoff(signal, "TIMEOUT")
        db.flush()
        return

    # Sync protection IDs từ open algo hiện tại
    stop_open = _find_algo_by_type(snapshot.open_algo_orders, "STOP_MARKET")
    tp_open = _find_algo_by_type(snapshot.open_algo_orders, "TAKE_PROFIT_MARKET")

    if stop_open:
        pending.sl_order_id = str(stop_open.get("algoId", "")) or pending.sl_order_id
    if tp_open:
        pending.tp_order_id = str(tp_open.get("algoId", "")) or pending.tp_order_id

    # --------------------------------------------------------
    # Phase 1: REQUESTED -> send cancel old SL
    # --------------------------------------------------------
    if phase in ("REQUESTED", COMMAND_REQUESTED):
        old_sl_id = pending.sl_order_id or (str(stop_open.get("algoId", "")) if stop_open else None)
        old_sl_price = float(signal.stop_loss or pending.stop_loss or 0)

        if old_sl_id:
            cancel_order_by_id(signal.symbol, old_sl_id)

            cmd.status = COMMAND_SENT
            if not cmd.sent_at:
                cmd.sent_at = utc_now()

            res.update({
                "phase": "CANCEL_SENT",
                "target_sl": target_sl,
                "old_sl_id": old_sl_id,
                "old_sl_price": old_sl_price,
                "cancel_sent_at": utc_now().isoformat(),
            })
            cmd.result_payload = res
            db.flush()

            print(
                f"🛡️ [PROTECTION] Cancel sent for old SL: "
                f"{signal.symbol} | old_sl_id={old_sl_id} | target_sl={target_sl}"
            )
            return

        # Không có old SL active -> chuyển luôn sang phase CANCEL_SENT
        cmd.status = COMMAND_SENT
        if not cmd.sent_at:
            cmd.sent_at = utc_now()

        res.update({
            "phase": "CANCEL_SENT",
            "target_sl": target_sl,
            "old_sl_id": None,
            "old_sl_price": old_sl_price,
            "cancel_sent_at": utc_now().isoformat(),
        })
        cmd.result_payload = res
        db.flush()

    # --------------------------------------------------------
    # Phase 2: CANCEL_SENT -> đợi STOP cũ biến mất, rồi place new
    # --------------------------------------------------------
    phase = dict(cmd.result_payload or {}).get("phase", phase)

    if phase == "CANCEL_SENT":
        stop_open = _find_algo_by_type(snapshot.open_algo_orders, "STOP_MARKET")

        # STOP cũ vẫn còn => chờ vòng sau
        if stop_open:
            return

        executor = get_executor()
        if not executor or not executor.ready:
            cmd.status = COMMAND_FAILED
            cmd.error_message = "EXECUTOR_NOT_READY"
            res["phase"] = "FAILED_EXECUTOR_NOT_READY"
            cmd.result_payload = res
            set_breakeven_retry_backoff(signal, "EXECUTOR_NOT_READY")
            db.flush()
            return

        symbol_info = executor.get_symbol_info(signal.symbol)
        rounded_sl = executor.round_price(signal.symbol, target_sl, symbol_info)

        try:
            new_sl_order = place_algo_stop_market_close_position(
                symbol=signal.symbol,
                direction=signal.direction,
                trigger_price=rounded_sl,
            )
            new_sl_id = str(new_sl_order.get("algoId", "")) if new_sl_order else None

            if not new_sl_id:
                raise RuntimeError("PLACE_NEW_SL_NO_ID")

        except Exception as e:
            err = f"PLACE_NEW_SL_ERROR::{e}"

            # Re-check open STOP ngay sau lỗi
            latest_open_algos = get_open_algo_orders(signal.symbol) or []
            latest_stop = _find_algo_by_type(latest_open_algos, "STOP_MARKET")

            # Nếu vẫn có STOP active => chờ, không fail command
            if latest_stop:
                pending.sl_order_id = str(latest_stop.get("algoId", "")) or pending.sl_order_id
                res["last_error"] = err
                cmd.result_payload = res
                db.flush()

                print(
                    f"⚠️ [PROTECTION] Replace pending, STOP still active => wait "
                    f"{signal.symbol} | {err}"
                )
                return

            # Không còn STOP => thử restore old SL
            old_sl_price = float(res.get("old_sl_price") or signal.stop_loss or pending.stop_loss or 0)

            if old_sl_price > 0:
                try:
                    rounded_old_sl = executor.round_price(signal.symbol, old_sl_price, symbol_info)
                    restored = place_algo_stop_market_close_position(
                        symbol=signal.symbol,
                        direction=signal.direction,
                        trigger_price=rounded_old_sl,
                    )
                    restored_id = str(restored.get("algoId", "")) if restored else None

                    if restored_id:
                        pending.sl_order_id = restored_id
                        pending.stop_loss = rounded_old_sl
                        signal.stop_loss = rounded_old_sl

                        cmd.status = COMMAND_FAILED
                        cmd.error_message = err
                        res.update({
                            "phase": "RESTORED_OLD_SL",
                            "restored_sl_id": restored_id,
                            "restored_sl_price": rounded_old_sl,
                            "last_error": err,
                        })
                        cmd.result_payload = res

                        mark_protection_changed(
                            trade=signal,
                            sl_price=rounded_old_sl,
                            sl_id=restored_id,
                        )
                        
                        set_breakeven_retry_backoff(signal, err)
                        db.flush()

                        print(
                            f"♻️ [PROTECTION] Restored old SL after replace fail: "
                            f"{signal.symbol} | sl={rounded_old_sl} algo_id={restored_id}"
                        )
                        return

                except Exception as restore_e:
                    print(f"❌ [PROTECTION] Restore old SL failed {signal.symbol}: {restore_e}")

            # Fatal
            cmd.status = COMMAND_FAILED
            cmd.error_message = err
            res.update({
                "phase": "FAILED_EMERGENCY_CLOSE",
                "last_error": err,
            })
            cmd.result_payload = res

            set_breakeven_retry_backoff(signal, err)
            db.flush()

            print(f"🚨 [PROTECTION] Replace failed => EMERGENCY_CLOSE {signal.symbol} | {err}")

            request_emergency_close(
                symbol=signal.symbol,
                signal_id=signal.id,
                pending_id=pending.id,
                reason=f"PROTECTION_REPLACE_FAILED::{err}",
            )
            return

        # Success
        pending.sl_order_id = new_sl_id
        pending.stop_loss = rounded_sl
        signal.stop_loss = rounded_sl

        req_level_key = req.get("level_key")

        mark_breakeven_applied(
            signal,
            rounded_sl,
            new_sl_id,
            level_key=req_level_key,
        )
        
        clear_breakeven_retry_backoff(signal)

        cmd.status = COMMAND_CONFIRMED
        cmd.confirmed_at = utc_now()
        res.update({
            "phase": "CONFIRMED",
            "new_sl_id": new_sl_id,
            "new_sl_price": rounded_sl,
        })
        cmd.result_payload = res
        cmd.error_message = None

        db.flush()

        print(
            f"✅ [PROTECTION] Breakeven applied: {signal.symbol} "
            f"| new_sl={rounded_sl} algo_id={new_sl_id}"
        )
        _notify_breakeven_applied(signal, rounded_sl)

def _notify_breakeven_applied(signal: Signal, new_sl_price: float):
    try:
        from app.services.telegram_service import send_telegram

        send_telegram(
            f"🛡️ <b>BREAKEVEN APPLIED</b>\n\n"
            f"<b>Symbol:</b> {signal.symbol}\n"
            f"<b>Direction:</b> {signal.direction}\n"
            f"<b>Entry:</b> {float(signal.entry_price):.4f}\n"
            f"<b>New SL:</b> {float(new_sl_price):.4f}\n"
            f"<b>Signal ID:</b> {signal.id}"
        )
    except Exception as e:
        print(f"[BREAKEVEN NOTIFY] {e}")

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

            if signal and signal.status == "OPEN":
                _process_protection_replace_command(db, signal, pending, snapshot, commands)

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
            },
            "plan": {
                "initial_stop_loss": float(pending.stop_loss),
                "initial_take_profit": float(pending.take_profit),
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

    # Nếu đang có command protection replace mở, không auto chạm protection nữa
    if has_open_command(db, pending.symbol, [CMD_PROTECTION_REPLACE]):
        return

    # Nếu vừa mới có thay đổi protection, bỏ qua auto-repair trong cooldown ngắn
    # để tránh race cùng cycle / stale snapshot exchange
    if protection_change_cooldown_active(signal):
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

def _enrich_snapshot_for_close(snapshot: SymbolSnapshot, pending: Optional[PendingSignal]) -> SymbolSnapshot:
    """
    Khi position đã đóng, triggered algo orders biến mất khỏi openAlgoOrders.
    Phải query lại detail cho sl/tp order ID đã lưu trong pending
    để xác định close reason (TP hay SL).
    """
    from app.services.execution_service import get_algo_order_status
    from app.services.live.snapshot_service import AlgoSnapshot

    # Nếu snapshot đã có algo info thì dùng luôn
    if snapshot.sl_algo or snapshot.tp_algo:
        return snapshot

    if not pending:
        return snapshot

    sl_algo = None
    tp_algo = None

    # Query detail cho SL
    sl_id = pending.sl_order_id
    if sl_id:
        try:
            data = get_algo_order_status(str(sl_id))
            if data and data.get("algo_status") not in (None, "UNKNOWN", "MISSING"):
                sl_algo = AlgoSnapshot(
                    algo_id=str(sl_id),
                    algo_status=data.get("algo_status"),
                    actual_order_id=data.get("actual_order_id"),
                    actual_price=data.get("actual_price"),
                    actual_qty=data.get("actual_qty"),
                    trigger_price=data.get("trigger_price"),
                    trigger_time=data.get("trigger_time"),
                    raw=data.get("raw"),
                )
        except Exception as e:
            print(f"[CLOSE ENRICH] SL query error {sl_id}: {e}")

    # Query detail cho TP
    tp_id = pending.tp_order_id
    if tp_id:
        try:
            data = get_algo_order_status(str(tp_id))
            if data and data.get("algo_status") not in (None, "UNKNOWN", "MISSING"):
                tp_algo = AlgoSnapshot(
                    algo_id=str(tp_id),
                    algo_status=data.get("algo_status"),
                    actual_order_id=data.get("actual_order_id"),
                    actual_price=data.get("actual_price"),
                    actual_qty=data.get("actual_qty"),
                    trigger_price=data.get("trigger_price"),
                    trigger_time=data.get("trigger_time"),
                    raw=data.get("raw"),
                )
        except Exception as e:
            print(f"[CLOSE ENRICH] TP query error {tp_id}: {e}")

    # Tạo snapshot mới với algo info bổ sung
    return SymbolSnapshot(
        symbol=snapshot.symbol,
        entry=snapshot.entry,
        position=snapshot.position,
        open_normal_orders=snapshot.open_normal_orders,
        open_algo_orders=snapshot.open_algo_orders,
        sl_algo=sl_algo or snapshot.sl_algo,
        tp_algo=tp_algo or snapshot.tp_algo,
        snapshot_time=snapshot.snapshot_time,
        ok=snapshot.ok,
        error=snapshot.error,
    )

def _finalize_signal_close(db, signal: Signal, pending: Optional[PendingSignal], snapshot: SymbolSnapshot, commands):
    # Nếu snapshot không có algo info (vì triggered algo biến khỏi open list),
    # phải query lại detail cho sl/tp order đã lưu trong pending
    enriched_snapshot = _enrich_snapshot_for_close(snapshot, pending)

    reason, exit_price = _derive_close_reason(signal, pending, enriched_snapshot, commands)

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

    feature = db.query(SignalFeature).filter(
        SignalFeature.signal_id == signal.id
    ).first()

    if feature:
        try:
            _schedule_outcome_save(signal.id)
        except Exception as e:
            print(f"[LIVE OUTCOME] {e}")

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
    - Risk model:
        C_OPEN + C_NEW <= C_CONFIG + 2
    - Nếu overflow:
        chỉ hủy các NEW zero-fill newest-first
    - KHÔNG tự đóng vị thế OPEN
    """
    cfg = get_runtime_config()
    c_config = int(cfg.get("MAX_OPEN_TRADES", 10) or 10)

    with SessionLocal() as db:
        snap = get_capacity_snapshot(db, c_config)

        if not snap.cleanup_needed:
            return

        overflow = snap.overflow_count
        candidates = get_new_zero_fill_cancel_candidates(db)

    print(
        f"⚠️ LIVE HARD CAP EXCEEDED: "
        f"open={snap.c_open} new={snap.c_new} total={snap.total_risk}/{snap.max_risk} "
        f"| overflow={overflow} | cancelling newest zero-fill NEW entries"
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

                # chỉ cancel đúng NEW zero-fill
                if p.status != "WAIT":
                    db.commit()
                    continue

                if not p.exchange_order_id:
                    db.commit()
                    continue

                if float(p.executed_qty or 0) > 0:
                    db.commit()
                    continue
                 
                if is_exchange_terminal_status(p.exchange_status):
                    db.commit()
                    continue

                print(
                    f"🚫 LIVE HARD CAP CANCEL: {p.symbol} {p.direction} "
                    f"| pending={p.id} order_id={p.exchange_order_id}"
                )

                ok = cancel_order_by_id(p.symbol, p.exchange_order_id)

                if ok:
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
            f"| likely because some symbols were locked / already changed state"
        )
        