"""
Kill Switch Service
===================
Dọn sạch toàn bộ hệ thống khi cần thiết.

PAPER:
  - Pending WAIT → CANCELLED
  - Signals OPEN → MANUAL

LIVE / TESTNET:
  1. Cancel ALL normal orders
  2. Cancel ALL algo orders
  3. Pause
  4. Close ALL positions
  5. Sync pending final
  6. Signals OPEN → MANUAL
  7. Audit log + telegram
"""

import time as time_module
from typing import Dict

from app.core.time_utils import utc_now
from app.core.trading_mode import get_current_mode, TradingMode
from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from app.services.execution_service import (
    get_executor,
    cancel_entry_and_exits,
    get_entry_order_status,
    cancel_all_algo_orders,
)


def execute_kill_switch() -> Dict:
    mode = get_current_mode()
    now  = utc_now()

    result = {
        "mode":              mode.value,
        "timestamp":         now.isoformat(),
        "pending_cancelled": 0,
        "pending_filled":    0,
        "signals_closed":    0,
        "exchange_cleanup":  False,
        "errors":            [],
    }

    # ── Exchange cleanup (LIVE/TESTNET only) ──────────────
    if mode != TradingMode.PAPER:
        try:
            _exchange_emergency_cleanup(result)
            result["exchange_cleanup"] = True
        except Exception as e:
            result["errors"].append(f"Exchange cleanup: {e}")
            print(f"[KILL SWITCH] Exchange cleanup error: {e}")

        time_module.sleep(2)

    # ── DB cleanup ────────────────────────────────────────
    with SessionLocal() as db:
        try:
            # Cancel all pending WAIT
            pending_wait = db.query(PendingSignal).filter(
                PendingSignal.status == "WAIT"
            ).all()

            for p in pending_wait:
                # LIVE/TESTNET: dọn exchange orders nếu có
                if mode != TradingMode.PAPER and p.exchange_order_id:
                    try:
                        cancel_entry_and_exits(p)

                        info = get_entry_order_status(p.symbol, p.exchange_order_id)
                        p.executed_qty = float(info.get("executed_qty") or p.executed_qty or 0)
                        p.exchange_status = info.get("status", p.exchange_status)
                        if info.get("avg_price"):
                            p.avg_fill_price = float(info["avg_price"])
                        p.last_exchange_sync_at = now
                    except Exception as e:
                        result["errors"].append(f"Pending [{p.id}] cleanup: {e}")

                if (p.executed_qty or 0) > 0:
                    p.status = "FILLED"
                    p.rejection_reason = "KILL_SWITCH"
                    result["pending_filled"] += 1
                else:
                    p.status = "CANCELLED"
                    p.rejection_reason = "KILL_SWITCH"
                    result["pending_cancelled"] += 1

            # Close all signals OPEN
            open_signals = db.query(Signal).filter(
                Signal.status == "OPEN"
            ).all()

            for trade in open_signals:
                trade.status = "MANUAL"
                trade.exit_reason = "KILL_SWITCH"
                trade.exit_time = now
                result["signals_closed"] += 1

            # Audit log
            from sqlalchemy import text
            import json

            db.execute(text("""
                INSERT INTO audit_logs (event_type, message, metadata, created_at)
                VALUES ('KILL_SWITCH', :msg, :meta, :now)
            """), {
                "msg":  f"Kill switch executed. Mode: {mode.value}",
                "meta": json.dumps(result),
                "now":  now,
            })

            db.commit()

        except Exception as e:
            db.rollback()
            result["errors"].append(f"DB cleanup: {e}")
            print(f"[KILL SWITCH] DB error: {e}")

    _log_result(result)
    _notify(result)

    return result


def _exchange_emergency_cleanup(result: Dict):
    """
    LIVE/TESTNET:
    Cancel all normal + algo orders, close all positions.
    """
    executor = get_executor()
    if not executor or not executor.ready:
        print("[KILL SWITCH] Executor not ready, skip exchange cleanup")
        return

    with SessionLocal() as db:
        pending_symbols = set(
            row[0] for row in
            db.query(PendingSignal.symbol).filter(
                PendingSignal.status == "WAIT"
            ).distinct().all()
        )
        open_symbols = set(
            row[0] for row in
            db.query(Signal.symbol).filter(
                Signal.status == "OPEN"
            ).distinct().all()
        )
        all_symbols = pending_symbols | open_symbols

    if not all_symbols:
        print("[KILL SWITCH] No symbols to clean up")
        return

    print(f"[KILL SWITCH] Cleaning {len(all_symbols)} symbols...")

    # Cancel all normal + algo orders
    for symbol in all_symbols:
        try:
            executor.cancel_all_orders(symbol)
        except Exception as e:
            result["errors"].append(f"Cancel normal {symbol}: {e}")

        try:
            cancel_all_algo_orders(symbol)
        except Exception as e:
            result["errors"].append(f"Cancel algo {symbol}: {e}")

    time_module.sleep(1)

    # Close all positions
    for symbol in all_symbols:
        try:
            pos = executor.get_position_info(symbol)
            if pos and abs(pos.get("positionAmt", 0)) > 0:
                direction = pos["direction"]
                executor.close_position(symbol, direction)
                print(f"[KILL SWITCH] Closed position: {symbol} {direction}")
        except Exception as e:
            result["errors"].append(f"Close position {symbol}: {e}")


def _log_result(result: Dict):
    print("\n" + "=" * 55)
    print("🛑 KILL SWITCH EXECUTED")
    print("=" * 55)
    print(f"  Mode:              {result['mode']}")
    print(f"  Pending cancelled: {result['pending_cancelled']}")
    print(f"  Pending filled:    {result['pending_filled']}")
    print(f"  Signals closed:    {result['signals_closed']}")
    print(f"  Exchange cleanup:  {result['exchange_cleanup']}")
    if result["errors"]:
        print(f"  Errors:            {len(result['errors'])}")
        for e in result["errors"]:
            print(f"    - {e}")
    print("=" * 55 + "\n")


def _notify(result: Dict):
    try:
        from app.services.telegram_service import send_telegram

        msg = (
            f"🛑 <b>KILL SWITCH ACTIVATED</b>\n\n"
            f"<b>Mode:</b> {result['mode']}\n"
            f"<b>Pending cancelled:</b> {result['pending_cancelled']}\n"
            f"<b>Pending filled (partial):</b> {result['pending_filled']}\n"
            f"<b>Signals closed:</b> {result['signals_closed']}\n"
            f"<b>Exchange cleanup:</b> {result['exchange_cleanup']}\n"
        )
        if result["errors"]:
            msg += f"\n⚠️ Errors: {len(result['errors'])}"

        send_telegram(msg)
    except Exception as e:
        print(f"[KILL SWITCH NOTIFY] {e}")