"""
Crash Recovery
==============
Chạy khi server startup.

RULE:
  PAPER:
    - Pending WAIT → CANCELLED + SYSTEM_CRASH
    - Signals OPEN → MANUAL + SYSTEM_CRASH

  LIVE / TESTNET:
    - TH1: order chưa khớp → cancel + CANCELLED
    - TH2: có fill + position còn sống → KỆ, để engine+monitor xử lý
    - TH3: khớp 100% + TP/SL chờ → KỆ
    - TH4: position=0 (TP/SL đã trigger) → cancel remainder + FILLED
    - Signal OPEN + position=0 → để monitor close khi chạy lại
    - Signal OPEN + position>0 → KỆ, monitor tiếp
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
    print("\n🔍 Checking for crash recovery...")

    try:
        mode = get_current_mode()
        now = utc_now()

        with SessionLocal() as db:
            row = db.execute(text(
                "SELECT value FROM app_config WHERE key = 'LAST_HEARTBEAT_AT'"
            )).fetchone()

            if not row:
                print("  ℹ️  No heartbeat found — first run, skipping recovery")
                update_heartbeat()
                return

            from datetime import datetime
            last_hb = ensure_utc(datetime.fromisoformat(row[0]))
            downtime_seconds = (now - last_hb).total_seconds()

            print(f"  Last heartbeat: {last_hb.isoformat()}")
            print(f"  Current time:   {now.isoformat()}")
            print(f"  Downtime:       {downtime_seconds:.0f}s (threshold: {RECOVERY_THRESHOLD}s)")
            print(f"  Mode:           {mode.value}")

            if downtime_seconds <= RECOVERY_THRESHOLD:
                print("  ✅ Downtime within threshold — no recovery needed")
                update_heartbeat()
                return

            print(f"\n  ⚠️  CRASH DETECTED — downtime {downtime_seconds:.0f}s > {RECOVERY_THRESHOLD}s")
            print("  🔄 Recovering state...")

            results = {
                "downtime_seconds":   round(downtime_seconds),
                "last_heartbeat":     last_hb.isoformat(),
                "recovery_time":      now.isoformat(),
                "mode":               mode.value,
                "pending_cancelled":  0,
                "pending_filled":     0,
                "pending_kept":       0,
                "signals_closed":     0,
                "signals_kept":       0,
                "errors":             [],
            }

            if mode == TradingMode.PAPER:
                _recover_paper(db, now, results)
            else:
                _recover_live(db, now, results)

            # Audit log
            db.execute(text(
                "INSERT INTO audit_logs (event_type, message, metadata, created_at) "
                "VALUES ('CRASH_RECOVERY', :msg, :meta, :now)"
            ), {
                "msg": f"Crash detected. Downtime: {downtime_seconds:.0f}s. Mode: {mode.value}",
                "meta": json.dumps(results),
                "now": now,
            })

            db.commit()

            _log_result(results)
            _notify(results)
            update_heartbeat()

    except Exception as e:
        print(f"  ❌ Recovery error: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# PAPER RECOVERY — giữ nguyên logic cũ
# ============================================================

def _recover_paper(db, now, results):
    """
    PAPER: dọn sạch DB.
    - Pending WAIT → CANCELLED
    - Signals OPEN → MANUAL
    """
    pending_count = db.query(PendingSignal).filter(
        PendingSignal.status == "WAIT"
    ).update({
        "status": "CANCELLED",
        "rejection_reason": "SYSTEM_CRASH",
    })
    results["pending_cancelled"] = pending_count

    open_trades = db.query(Signal).filter(
        Signal.status == "OPEN"
    ).all()

    for trade in open_trades:
        trade.status = "MANUAL"
        trade.exit_reason = "SYSTEM_CRASH"
        trade.exit_time = now
        results["signals_closed"] += 1


# ============================================================
# LIVE / TESTNET RECOVERY — logic mới
# ============================================================

def _recover_live(db, now, results):
    """
    LIVE / TESTNET crash recovery:
    - TH1: chưa khớp → cancel + CANCELLED
    - TH2: có fill + position còn → KỆ
    - TH3: khớp 100% + TP/SL chờ → KỆ
    - TH4: position=0 → cancel remainder + FILLED
    - Signal: để monitor xử lý khi restart
    """
    from app.services.execution_service import (
        get_executor,
        get_entry_order_status,
        cancel_entry_and_exits,
    )

    executor = get_executor()

    pending_wait = db.query(PendingSignal).filter(
        PendingSignal.status == "WAIT"
    ).all()

    for p in pending_wait:
        try:
            action = _handle_live_pending(db, p, now, executor, results)
            print(f"  [PENDING {p.id}] {p.symbol} → {action}")
        except Exception as e:
            results["errors"].append(f"Pending [{p.id}] {p.symbol}: {e}")
            print(f"  ❌ Pending [{p.id}] {p.symbol}: {e}")

    # Signal OPEN: không đụng, để monitor xử lý
    open_count = db.query(Signal).filter(
        Signal.status == "OPEN"
    ).count()

    results["signals_kept"] = open_count

    if open_count > 0:
        print(f"  ℹ️  {open_count} signals OPEN — monitor sẽ xử lý sau khi restart")


def _handle_live_pending(db, p, now, executor, results):
    """
    Xử lý 1 pending WAIT trong crash recovery LIVE/TESTNET.

    Returns: action string cho logging
    """
    from app.services.execution_service import (
        get_entry_order_status,
        cancel_entry_and_exits,
    )

    # Nếu chưa place order → cancel local
    if not p.exchange_order_id:
        p.status = "CANCELLED"
        p.rejection_reason = "SYSTEM_CRASH"
        results["pending_cancelled"] += 1
        return "cancelled_no_order"

    # Sync trạng thái từ exchange
    info = get_entry_order_status(p.symbol, p.exchange_order_id)
    p.exchange_status = info.get("status", p.exchange_status)
    p.executed_qty = float(info.get("executed_qty") or p.executed_qty or 0)
    if info.get("orig_qty"):
        p.order_quantity = float(info["orig_qty"])
    if info.get("avg_price"):
        p.avg_fill_price = float(info["avg_price"])
    p.last_exchange_sync_at = now

    executed = float(p.executed_qty or 0)

    # TH1: Chưa khớp gì
    if executed == 0:
        cancel_entry_and_exits(p)
        p.status = "CANCELLED"
        p.rejection_reason = "SYSTEM_CRASH"
        results["pending_cancelled"] += 1
        return "cancelled_no_fill"

    # Đã có fill → check position thật trên exchange
    position_size = 0
    if executor and executor.ready:
        position_size = executor.get_position_size(p.symbol)

    if position_size == 0:
        # TH4: Position đã về 0 (TP/SL đã trigger)
        # Cancel remainder entry nếu còn
        cancel_entry_and_exits(p)
        p.status = "FILLED"
        p.rejection_reason = "SYSTEM_CRASH_POSITION_CLOSED"
        results["pending_filled"] += 1
        return "filled_position_closed"

    # TH2/TH3: Position vẫn còn sống → KỆ
    # Pending engine + monitor sẽ tiếp tục xử lý sau restart
    results["pending_kept"] += 1
    return f"kept_active (pos={position_size}, filled={executed})"


# ============================================================
# LOG + NOTIFY
# ============================================================

def _log_result(results):
    print(f"\n  ✅ Recovery complete:")
    print(f"     Mode:              {results['mode']}")
    print(f"     Pending cancelled: {results['pending_cancelled']}")
    print(f"     Pending filled:    {results.get('pending_filled', 0)}")
    print(f"     Pending kept:      {results.get('pending_kept', 0)}")
    print(f"     Signals closed:    {results['signals_closed']}")
    print(f"     Signals kept:      {results.get('signals_kept', 0)}")
    if results.get("errors"):
        print(f"     Errors:            {len(results['errors'])}")
        for e in results["errors"]:
            print(f"       - {e}")


def _notify(results):
    try:
        from app.services.telegram_service import send_telegram

        mode = results["mode"]
        msg = (
            f"⚠️ <b>SYSTEM CRASH RECOVERY</b>\n\n"
            f"<b>Mode:</b> {mode}\n"
            f"<b>Downtime:</b> {results['downtime_seconds']}s\n"
            f"<b>Pending cancelled:</b> {results['pending_cancelled']}\n"
            f"<b>Pending filled:</b> {results.get('pending_filled', 0)}\n"
            f"<b>Pending kept active:</b> {results.get('pending_kept', 0)}\n"
            f"<b>Signals closed:</b> {results['signals_closed']}\n"
            f"<b>Signals kept (monitor):</b> {results.get('signals_kept', 0)}\n"
        )
        if results.get("errors"):
            msg += f"\n⚠️ Errors: {len(results['errors'])}"

        send_telegram(msg)
    except Exception as e:
        print(f"[CRASH RECOVERY NOTIFY] {e}")