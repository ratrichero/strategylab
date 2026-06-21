from typing import Optional, Iterable, Dict, Any

from app.core.time_utils import utc_now
from app.db.session import SessionLocal
from app.db.models import ExecutionCommand, Signal, PendingSignal
from app.services.execution_service import (
    close_position as exec_close_position,
    cancel_entry_and_exits,
    cancel_all_algo_orders,
    get_executor,
    list_open_positions,
)


COMMAND_REQUESTED = "REQUESTED"
COMMAND_SENT = "SENT"
COMMAND_CONFIRMED = "CONFIRMED"
COMMAND_FAILED = "FAILED"

CMD_MANUAL_CLOSE = "MANUAL_CLOSE"
CMD_MANUAL_CANCEL_PENDING = "MANUAL_CANCEL_PENDING"
CMD_KILL_SWITCH = "KILL_SWITCH"
CMD_PROTECTION_REPLACE = "PROTECTION_REPLACE"
CMD_EMERGENCY_CLOSE = "EMERGENCY_CLOSE"
CMD_PROFIT_LOCK = "PROFIT_LOCK"


def _get_price_hint(symbol: str) -> Optional[float]:
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

    return None

def _create_command(
    db,
    *,
    symbol: str,
    command_type: str,
    pending_id: Optional[int] = None,
    signal_id: Optional[int] = None,
    request_payload: Optional[Dict[str, Any]] = None,
) -> ExecutionCommand:
    cmd = ExecutionCommand(
        symbol=symbol,
        command_type=command_type,
        status=COMMAND_REQUESTED,
        pending_id=pending_id,
        signal_id=signal_id,
        requested_at=utc_now(),
        request_payload=request_payload,
    )
    db.add(cmd)
    db.flush()
    return cmd


def get_latest_open_command(
    db,
    symbol: str,
    command_types: Optional[Iterable[str]] = None,
):
    q = db.query(ExecutionCommand).filter(
        ExecutionCommand.symbol == symbol,
        ExecutionCommand.status.in_([COMMAND_REQUESTED, COMMAND_SENT]),
    )

    if command_types:
        q = q.filter(ExecutionCommand.command_type.in_(list(command_types)))

    return q.order_by(ExecutionCommand.requested_at.desc()).first()


def has_open_command(
    db,
    symbol: str,
    command_types: Optional[Iterable[str]] = None,
) -> bool:
    return get_latest_open_command(db, symbol, command_types) is not None


def confirm_commands_for_symbol(
    db,
    symbol: str,
    command_types: Iterable[str],
    result_payload: Optional[Dict[str, Any]] = None,
):
    cmds = db.query(ExecutionCommand).filter(
        ExecutionCommand.symbol == symbol,
        ExecutionCommand.command_type.in_(list(command_types)),
        ExecutionCommand.status.in_([COMMAND_REQUESTED, COMMAND_SENT]),
    ).all()

    now = utc_now()
    for cmd in cmds:
        cmd.status = COMMAND_CONFIRMED
        cmd.confirmed_at = now
        if result_payload:
            cmd.result_payload = result_payload


def request_manual_close(signal_id: int) -> Dict[str, Any]:
    with SessionLocal() as db:
        trade = db.query(Signal).get(signal_id)
        if not trade:
            return {"success": False, "error": f"Signal {signal_id} not found"}

        if trade.status != "OPEN":
            return {"success": False, "error": f"Signal {signal_id} not OPEN (status={trade.status})"}

        pending = db.query(PendingSignal).filter(
            PendingSignal.signal_id == trade.id
        ).order_by(PendingSignal.created_at.desc()).first()

        price_hint = _get_price_hint(trade.symbol)

        cmd = _create_command(
            db,
            symbol=trade.symbol,
            command_type=CMD_MANUAL_CLOSE,
            pending_id=pending.id if pending else None,
            signal_id=trade.id,
            request_payload={
                "reason": "MANUAL",
                "price_hint": price_hint,
            },
        )
        db.commit()
        db.refresh(cmd)

        try:
            result = exec_close_position(trade, "MANUAL")
            actual_exit = result.actual_entry if (result.actual_entry and result.actual_entry > 0) else None

            cmd.status = COMMAND_SENT if result.success else COMMAND_FAILED
            cmd.sent_at = utc_now()
            cmd.result_payload = {
                "success": result.success,
                "order_id": result.order_id,
                "actual_exit_price": actual_exit,
                "price_hint": price_hint,
                "fee": result.fee,
                "mode": result.mode,
            }
            cmd.error_message = result.error
            db.commit()

            return {
                "success": result.success,
                "command_id": cmd.id,
                "symbol": trade.symbol,
                "status": cmd.status,
                "error": result.error,
            }
        except Exception as e:
            db.rollback()
            with SessionLocal() as db2:
                fresh = db2.query(ExecutionCommand).get(cmd.id)
                if fresh:
                    fresh.status = COMMAND_FAILED
                    fresh.error_message = f"{type(e).__name__}: {e}"
                    db2.commit()
            return {
                "success": False,
                "command_id": cmd.id,
                "symbol": trade.symbol,
                "status": COMMAND_FAILED,
                "error": f"{type(e).__name__}: {e}",
            }


def request_manual_cancel_pending(pending_id: int) -> Dict[str, Any]:
    with SessionLocal() as db:
        pending = db.query(PendingSignal).get(pending_id)
        if not pending:
            return {"success": False, "error": f"Pending {pending_id} not found"}

        if pending.status != "WAIT":
            return {"success": False, "error": f"Pending {pending_id} not WAIT (status={pending.status})"}

        # Chưa place lên exchange -> local còn là truth
        if not pending.exchange_order_id and float(pending.executed_qty or 0) <= 0:
            pending.status = "CANCELLED"
            pending.rejection_reason = "MANUAL_CANCEL"
            db.commit()
            return {
                "success": True,
                "pending_id": pending.id,
                "symbol": pending.symbol,
                "status": "CANCELLED",
                "mode": "LOCAL_PRE_PLACE",
            }

        cmd = _create_command(
            db,
            symbol=pending.symbol,
            command_type=CMD_MANUAL_CANCEL_PENDING,
            pending_id=pending.id,
            signal_id=pending.signal_id,
            request_payload={"reason": "MANUAL_CANCEL_PENDING"},
        )
        db.commit()
        db.refresh(cmd)

        try:
            cancel_entry_and_exits(pending)

            cmd.status = COMMAND_SENT
            cmd.sent_at = utc_now()
            cmd.result_payload = {
                "cancel_requested": True,
                "exchange_order_id": pending.exchange_order_id,
                "sl_order_id": pending.sl_order_id,
                "tp_order_id": pending.tp_order_id,
            }
            db.commit()

            return {
                "success": True,
                "command_id": cmd.id,
                "pending_id": pending.id,
                "symbol": pending.symbol,
                "status": cmd.status,
            }
        except Exception as e:
            db.rollback()
            with SessionLocal() as db2:
                fresh = db2.query(ExecutionCommand).get(cmd.id)
                if fresh:
                    fresh.status = COMMAND_FAILED
                    fresh.error_message = f"{type(e).__name__}: {e}"
                    db2.commit()
            return {
                "success": False,
                "command_id": cmd.id,
                "pending_id": pending.id,
                "symbol": pending.symbol,
                "status": COMMAND_FAILED,
                "error": f"{type(e).__name__}: {e}",
            }


def request_emergency_close(symbol: str, signal_id: Optional[int], pending_id: Optional[int], reason: str) -> Dict[str, Any]:
    with SessionLocal() as db:
        if has_open_command(db, symbol, [CMD_EMERGENCY_CLOSE]):
            existing = get_latest_open_command(db, symbol, [CMD_EMERGENCY_CLOSE])
            return {
                "success": True,
                "symbol": symbol,
                "command_id": existing.id if existing else None,
                "status": existing.status if existing else COMMAND_SENT,
                "deduped": True,
            }

        trade = None
        if signal_id:
            trade = db.query(Signal).get(signal_id)

        price_hint = _get_price_hint(symbol)

        cmd = _create_command(
            db,
            symbol=symbol,
            command_type=CMD_EMERGENCY_CLOSE,
            pending_id=pending_id,
            signal_id=signal_id,
            request_payload={
                "reason": reason,
                "price_hint": price_hint,
            },
        )
        db.commit()
        db.refresh(cmd)

        try:
            if trade:
                result = exec_close_position(trade, f"EMERGENCY_CLOSE::{reason}")
                actual_exit = result.actual_entry if (result.actual_entry and result.actual_entry > 0) else None
                success = result.success
                payload = {
                    "success": result.success,
                    "order_id": result.order_id,
                    "actual_exit_price": actual_exit,
                    "price_hint": price_hint,
                    "fee": result.fee,
                    "mode": result.mode,
                }
                err = result.error
            else:
                executor = get_executor()
                success = False
                payload = {
                    "price_hint": price_hint,
                }
                err = "No trade found for emergency close"
                if executor and executor.ready:
                    pos = executor.get_position_info(symbol)
                    if pos:
                        executor.cancel_all_orders(symbol)
                        cancel_all_algo_orders(symbol)
                        result = executor.close_position(symbol, pos["direction"])
                        success = result is not None
                        payload["raw"] = result
                        err = None if success else "Executor close_position returned None"

            cmd.status = COMMAND_SENT if success else COMMAND_FAILED
            cmd.sent_at = utc_now()
            cmd.result_payload = payload
            cmd.error_message = err
            db.commit()

            return {
                "success": success,
                "symbol": symbol,
                "command_id": cmd.id,
                "status": cmd.status,
                "error": err,
            }
        except Exception as e:
            db.rollback()
            with SessionLocal() as db2:
                fresh = db2.query(ExecutionCommand).get(cmd.id)
                if fresh:
                    fresh.status = COMMAND_FAILED
                    fresh.error_message = f"{type(e).__name__}: {e}"
                    db2.commit()
            return {
                "success": False,
                "symbol": symbol,
                "command_id": cmd.id,
                "status": COMMAND_FAILED,
                "error": f"{type(e).__name__}: {e}",
            }


def request_kill_switch_all() -> Dict[str, Any]:
    with SessionLocal() as db:
        active_symbols = set(
            row[0] for row in db.query(PendingSignal.symbol).filter(
                PendingSignal.status == "WAIT"
            ).distinct().all()
        )
        active_symbols |= set(
            row[0] for row in db.query(Signal.symbol).filter(
                Signal.status == "OPEN"
            ).distinct().all()
        )

        local_cancelled = db.query(PendingSignal).filter(
            PendingSignal.status == "WAIT",
            PendingSignal.exchange_order_id == None,  # noqa: E711
        ).update({
            "status": "CANCELLED",
            "rejection_reason": "KILL_SWITCH_LOCAL_CANCEL",
            "next_retry_at": None,
        }, synchronize_session=False)
        db.commit()

    exchange_positions = list_open_positions()
    active_symbols |= set(p.get("symbol") for p in exchange_positions if p.get("symbol"))

    result = {
        "success": True,
        "symbols": sorted(active_symbols),
        "commands": [],
        "errors": [],
        "local_pending_cancelled": int(local_cancelled or 0),
    }

    executor = get_executor()
    if not executor or not executor.ready:
        return {
            "success": False,
            "error": "Executor not ready",
            "symbols": [],
            "commands": [],
            "local_pending_cancelled": int(local_cancelled or 0),
        }

    for symbol in sorted(active_symbols):
        with SessionLocal() as db:
            pending = db.query(PendingSignal).filter(
                PendingSignal.symbol == symbol,
                PendingSignal.status == "WAIT"
            ).order_by(PendingSignal.created_at.desc()).first()

            signal = db.query(Signal).filter(
                Signal.symbol == symbol,
                Signal.status == "OPEN"
            ).order_by(Signal.created_at.desc()).first()

            cmd = _create_command(
                db,
                symbol=symbol,
                command_type=CMD_KILL_SWITCH,
                pending_id=pending.id if pending else None,
                signal_id=signal.id if signal else None,
                request_payload={"reason": "KILL_SWITCH"},
            )
            db.commit()
            db.refresh(cmd)

            try:
                executor.cancel_all_orders(symbol)
                cancel_all_algo_orders(symbol)

                pos = executor.get_position_info(symbol)
                payload = {
                    "cancel_all_orders": True,
                    "cancel_all_algo_orders": True,
                    "had_position": bool(pos),
                }

                success = True
                if pos:
                    close_result = executor.close_position(symbol, pos["direction"])
                    payload["close_raw"] = close_result
                    success = close_result is not None

                cmd.status = COMMAND_SENT if success else COMMAND_FAILED
                cmd.sent_at = utc_now()
                cmd.result_payload = payload
                db.commit()

                result["commands"].append({
                    "command_id": cmd.id,
                    "symbol": symbol,
                    "status": cmd.status,
                })

                if not success:
                    result["success"] = False
                    result["errors"].append(f"{symbol}: close_position returned None")

            except Exception as e:
                db.rollback()
                with SessionLocal() as db2:
                    fresh = db2.query(ExecutionCommand).get(cmd.id)
                    if fresh:
                        fresh.status = COMMAND_FAILED
                        fresh.error_message = f"{type(e).__name__}: {e}"
                        db2.commit()

                result["success"] = False
                result["errors"].append(f"{symbol}: {type(e).__name__}: {e}")

    return result

def request_protection_replace(signal_id: int, new_sl_price: float, level_key: Optional[str] = None, level_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    with SessionLocal() as db:
        trade = db.query(Signal).get(signal_id)
        if not trade:
            return {"success": False, "error": f"Signal {signal_id} not found"}

        if trade.status != "OPEN":
            return {"success": False, "error": f"Signal {signal_id} not OPEN (status={trade.status})"}

        pending = db.query(PendingSignal).filter(
            PendingSignal.signal_id == trade.id
        ).order_by(PendingSignal.created_at.desc()).first()

        if not pending:
            return {"success": False, "error": f"No pending linked for signal {signal_id}"}

        if new_sl_price is None or float(new_sl_price) <= 0:
            return {"success": False, "error": "Invalid new_sl_price"}

        existing = get_latest_open_command(db, trade.symbol, [CMD_PROTECTION_REPLACE])
        if existing:
            return {
                "success": True,
                "symbol": trade.symbol,
                "signal_id": trade.id,
                "command_id": existing.id,
                "status": existing.status,
                "deduped": True,
            }

        cmd = _create_command(
            db,
            symbol=trade.symbol,
            command_type=CMD_PROTECTION_REPLACE,
            pending_id=pending.id,
            signal_id=trade.id,
            request_payload={
                "reason": "PROTECTION_LEVEL",
                "new_sl_price": float(new_sl_price),
                "level_key": level_key,
                "level_cfg": level_cfg or {},
            },
        )
        db.commit()
        db.refresh(cmd)

        return {
            "success": True,
            "symbol": trade.symbol,
            "signal_id": trade.id,
            "command_id": cmd.id,
            "status": cmd.status,
            "deduped": False,
        }
    
def request_profit_lock_all() -> Dict[str, Any]:
    """
    Profit Lock: close all positions + cancel all pending NEW.
    Giống kill-switch nhưng trigger bởi PnL dương.
    """
    from app.services.live.profit_lock_service import mark_profit_lock_triggered

    result = request_kill_switch_all()

    # Override command type cho audit trail
    with SessionLocal() as db:
        recent_cmds = db.query(ExecutionCommand).filter(
            ExecutionCommand.command_type == CMD_KILL_SWITCH,
            ExecutionCommand.created_at >= utc_now() - __import__('datetime').timedelta(seconds=10),
        ).all()

        for cmd in recent_cmds:
            cmd.command_type = CMD_PROFIT_LOCK
            if cmd.request_payload:
                payload = dict(cmd.request_payload)
                payload["reason"] = "PROFIT_LOCK"
                cmd.request_payload = payload

        db.commit()

    mark_profit_lock_triggered()

    result["trigger"] = "PROFIT_LOCK"
    return result
