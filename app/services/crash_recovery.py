"""
Crash Recovery
==============
Chạy khi server startup.

RULE:
  - Check LAST_HEARTBEAT_AT
  - Nếu downtime > threshold:
      PAPER:
        Pending WAIT  -> CANCELLED + SYSTEM_CRASH
        Signals OPEN  -> MANUAL + SYSTEM_CRASH

      LIVE / TESTNET:
        1. Cancel ALL exchange orders
        2. Pause ngắn
        3. Close ALL exchange positions
        4. Sync pending final (executed_qty)
        5. Pending:
             executed_qty > 0 -> FILLED + SYSTEM_CRASH
             executed_qty = 0 -> CANCELLED + SYSTEM_CRASH
        6. Signals OPEN -> MANUAL + SYSTEM_CRASH
        7. Audit log

  - Không ghi trade_outcome_analytics cho crash-closed positions
"""

import os
import json
import time as time_module

from app.core.time_utils import utc_now, ensure_utc
from app.core.trading_mode import get_current_mode, TradingMode
from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from sqlalchemy import text


RECOVERY_THRESHOLD = int(os.getenv("PAPER_RECOVERY_THRESHOLD_SECONDS", "120"))


# ============================================================
# HEARTBEAT
# ============================================================

def update_heartbeat():
    """Ghi heartbeat vào app_config. Gọi mỗi 30s."""
    try:
        now = utc_now()
        with SessionLocal() as db:
            db.execute(text(
                "INSERT INTO app_config (key, value, updated_at) "
                "VALUES ('LAST_HEARTBEAT_AT', :v, :now) "
                "ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = :now"
            ), {"v": now.isoformat(), "now": now})
            db.commit()
    except Exception as e:
        print(f"[HEARTBEAT] Error: {e}")


# ============================================================
# RECOVERY
# ============================================================

def check_and_recover():
    """
    Chạy khi server startup.
    Nếu downtime > threshold → recover state.
    """
    print("\n🔍 Checking for crash recovery...")

    try:
        mode = get_current_mode()
        now = utc_now()

        with SessionLocal() as db:
            # ── Lấy heartbeat cuối ────────────────────────
            row = db.execute(text(
                "SELECT value FROM app_config WHERE key = 'LAST_HEARTBEAT_AT'"
            )).fetchone()

            if not row:
                print("  ℹ️  No heartbeat found — first run, skipping recovery")
                update_heartbeat()
                return

            last_hb = ensure_utc(
                __import__("datetime").datetime.fromisoformat(row[0])
            )
            downtime_seconds = (now - last_hb).total_seconds()

            print(f"  Last heartbeat: {last_hb.isoformat()}")
            print(f"  Current time:   {now.isoformat()}")
            print(f"  Downtime:       {downtime_seconds:.0f}s (threshold: {RECOVERY_THRESHOLD}s)")
            print(f"  Mode:           {mode.value}")

            if downtime_seconds <= RECOVERY_THRESHOLD:
                print("  ✅ Downtime within threshold — no recovery needed")
                update_heartbeat()
                return

            # ── RECOVERY ──────────────────────────────────
            print(f"\n  ⚠️  CRASH DETECTED — downtime {downtime_seconds:.0f}s > {RECOVERY_THRESHOLD}s")
            print("  🔄 Recovering state...")

            results = {
                "downtime_seconds": round(downtime_seconds),
                "last_heartbeat": last_hb.isoformat(),
                "recovery_time": now.isoformat(),
                "mode": mode.value,
                "pending_cancelled": 0,
                "pending_filled": 0,
                "trades_closed": 0,
                "exchange_cleanup": False,
                "errors": [],
            }

            # ── LIVE/TESTNET: exchange cleanup trước ──────
            if mode != TradingMode.PAPER:
                try:
                    _exchange_crash_cleanup(db, results)
                    results["exchange_cleanup"] = True
                except Exception as e:
                    results["errors"].append(f"Exchange cleanup: {e}")
                    print(f"  ❌ Exchange cleanup error: {e}")

                # pause cho exchange settle
                time_module.sleep(2)

            # ── Cancel/finalize all pending WAIT ──────────
            pending_wait = db.query(PendingSignal).filter(
                PendingSignal.status == "WAIT"
            ).all()

            for p in pending_wait:
                try:
                    if mode != TradingMode.PAPER:
                        _finalize_pending_crash(db, p, now, results)
                    else:
                        p.status = "CANCELLED"
                        p.rejection_reason = "SYSTEM_CRASH"
                        results["pending_cancelled"] += 1
                except Exception as e:
                    results["errors"].append(f"Pending [{p.id}] {p.symbol}: {e}")
                    # fallback: cancel local anyway
                    p.status = "CANCELLED"
                    p.rejection_reason = "SYSTEM_CRASH"
                    results["pending_cancelled"] += 1

            # ── Close all open signals ────────────────────
            open_trades = db.query(Signal).filter(
                Signal.status == "OPEN"
            ).all()

            for trade in open_trades:
                trade.status = "MANUAL"
                trade.exit_reason = "SYSTEM_CRASH"
                trade.exit_time = now
                # Không set result_percent / exit_price
                # Không ghi trade_outcome_analytics
                results["trades_closed"] += 1

            # ── Audit log ─────────────────────────────────
            db.execute(text(
                "INSERT INTO audit_logs (event_type, message, metadata, created_at) "
                "VALUES ('CRASH_RECOVERY', :msg, :meta, :now)"
            ), {
                "msg": f"System crash detected. Downtime: {downtime_seconds:.0f}s. Mode: {mode.value}",
                "meta": json.dumps(results),
                "now": now,
            })

            db.commit()

            # ── Log + Notify ──────────────────────────────
            _log_recovery_result(results)
            _notify_crash_recovery(results)

            update_heartbeat()

    except Exception as e:
        print(f"  ❌ Recovery error: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# LIVE/TESTNET EXCHANGE CLEANUP
# ============================================================

def _exchange_crash_cleanup(db, results: dict):
    """
    LIVE/TESTNET:
    Cancel all exchange orders + close all positions.
    Giống kill switch nhưng là auto-trigger khi startup.
    """
    from app.services.execution_service import get_executor

    executor = get_executor()
    if not executor or not executor.ready:
        print("  ⚠️ Executor not ready, skip exchange cleanup")
        return

    # Lấy danh sách symbols cần dọn
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
        print("  ℹ️  No symbols to clean up on exchange")
        return

    print(f"  🔄 Exchange cleanup: {len(all_symbols)} symbols...")

    # Cancel all orders
    for symbol in all_symbols:
        try:
            executor.cancel_all_orders(symbol)
        except Exception as e:
            results["errors"].append(f"Cancel orders {symbol}: {e}")

    # Pause
    time_module.sleep(1)

    # Close all positions
    for symbol in all_symbols:
        try:
            pos = executor.get_position_info(symbol)
            if pos and abs(pos.get("positionAmt", 0)) > 0:
                direction = pos["direction"]
                executor.close_position(symbol, direction)
                print(f"  💰 Closed position: {symbol} {direction}")
        except Exception as e:
            results["errors"].append(f"Close position {symbol}: {e}")


def _finalize_pending_crash(db, p: PendingSignal, now, results: dict):
    """
    LIVE/TESTNET:
    Finalize 1 pending trong crash recovery.
    - Nếu có exchange_order_id: cancel + sync final qty
    - executed_qty > 0 → FILLED
    - executed_qty = 0 → CANCELLED
    """
    from app.services.execution_service import (
        cancel_entry_and_exits,
        get_entry_order_status,
    )

    if p.exchange_order_id:
        # Cancel entry + SL + TP nếu còn sống
        try:
            cancel_entry_and_exits(p)
        except Exception as e:
            results["errors"].append(f"Cancel orders [{p.id}] {p.symbol}: {e}")

        # Sync final executed_qty
        try:
            info = get_entry_order_status(p.symbol, p.exchange_order_id)
            p.executed_qty = float(info.get("executed_qty") or p.executed_qty or 0)
            p.exchange_status = info.get("status", p.exchange_status)
            if info.get("avg_price"):
                p.avg_fill_price = float(info["avg_price"])
            p.last_exchange_sync_at = now
        except Exception as e:
            results["errors"].append(f"Sync order [{p.id}] {p.symbol}: {e}")

    # Chốt local status
    if (p.executed_qty or 0) > 0:
        p.status = "FILLED"
        p.rejection_reason = "SYSTEM_CRASH"
        results["pending_filled"] = results.get("pending_filled", 0) + 1
    else:
        p.status = "CANCELLED"
        p.rejection_reason = "SYSTEM_CRASH"
        results["pending_cancelled"] = results.get("pending_cancelled", 0) + 1


# ============================================================
# LOG + NOTIFY
# ============================================================

def _log_recovery_result(results: dict):
    print(f"\n  ✅ Recovery complete:")
    print(f"     Mode:              {results['mode']}")
    print(f"     Pending cancelled: {results['pending_cancelled']}")
    print(f"     Pending filled:    {results.get('pending_filled', 0)}")
    print(f"     Trades closed:     {results['trades_closed']}")
    print(f"     Exchange cleanup:  {results['exchange_cleanup']}")
    if results.get("errors"):
        print(f"     Errors:            {len(results['errors'])}")
        for e in results["errors"]:
            print(f"       - {e}")


def _notify_crash_recovery(results: dict):
    try:
        from app.services.telegram_service import send_telegram

        msg = (
            f"⚠️ <b>SYSTEM CRASH RECOVERY</b>\n\n"
            f"<b>Mode:</b> {results['mode']}\n"
            f"<b>Downtime:</b> {results['downtime_seconds']}s\n"
            f"<b>Pending cancelled:</b> {results['pending_cancelled']}\n"
            f"<b>Pending filled (partial):</b> {results.get('pending_filled', 0)}\n"
            f"<b>Trades closed:</b> {results['trades_closed']}\n"
            f"<b>Exchange cleanup:</b> {results['exchange_cleanup']}\n"
        )
        if results.get("errors"):
            msg += f"\n⚠️ Errors: {len(results['errors'])}"

        send_telegram(msg)
    except Exception as e:
        print(f"[CRASH RECOVERY NOTIFY] {e}")