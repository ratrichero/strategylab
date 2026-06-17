"""
Crash Recovery
==============
PAPER:
  - threshold-based
  - Pending WAIT → CANCELLED + SYSTEM_CRASH
  - Signals OPEN → MANUAL + SYSTEM_CRASH

LIVE:
  - startup full reconcile từ exchange
  - KHÔNG auto bulk cancel/close trước khi hỏi exchange
"""

import os
import json

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
# MAIN RECOVERY
# ============================================================

def check_and_recover():
    print("\n🔍 Checking for crash recovery...")

    try:
        mode = get_current_mode()
        now = utc_now()

        if mode != TradingMode.PAPER:
            _recover_live_startup(now)
            update_heartbeat()
            return

        # ── PAPER recovery (threshold-based, giữ nguyên) ────
        _recover_paper_startup(now)
        update_heartbeat()

    except Exception as e:
        print(f"  ❌ Recovery error: {e}")
        import traceback
        traceback.print_exc()


# ============================================================
# PAPER RECOVERY — giữ nguyên behavior cũ
# ============================================================

def _recover_paper_startup(now):
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
        print(f"  Mode:           PAPER")

        if downtime_seconds <= RECOVERY_THRESHOLD:
            print("  ✅ Downtime within threshold — no recovery needed")
            return

        print(f"\n  ⚠️  CRASH DETECTED — downtime {downtime_seconds:.0f}s > {RECOVERY_THRESHOLD}s")
        print("  🔄 Recovering PAPER state...")

        results = {
            "downtime_seconds":  round(downtime_seconds),
            "last_heartbeat":    last_hb.isoformat(),
            "recovery_time":     now.isoformat(),
            "mode":              "PAPER",
            "pending_cancelled": 0,
            "signals_closed":    0,
            "errors":            [],
        }

        # PAPER: bulk cancel/close
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

        db.execute(text(
            "INSERT INTO audit_logs (event_type, message, metadata, created_at) "
            "VALUES ('CRASH_RECOVERY', :msg, :meta, :now)"
        ), {
            "msg": f"Paper crash detected. Downtime: {downtime_seconds:.0f}s",
            "meta": json.dumps(results),
            "now": now,
        })

        db.commit()

        _log_result(results)
        _notify(results)


# ============================================================
# LIVE RECOVERY — exchange-first reconcile
# ============================================================

def _recover_live_startup(now):
    """
    LIVE recovery:
    1. Log startup
    2. Gọi live reconciler để sync tất cả active symbols
    3. KHÔNG auto bulk cancel/close trước khi hỏi exchange
    """
    print(f"  Mode: LIVE")
    print(f"  🔄 Running LIVE startup reconcile...")

    results = {
        "recovery_time": now.isoformat(),
        "mode":          "LIVE",
        "errors":        [],
    }

    try:
        from app.services.live.recovery import run_startup_live_recovery
        run_startup_live_recovery()
        results["reconcile_ok"] = True
        print("  ✅ LIVE startup reconcile complete")
    except Exception as e:
        results["reconcile_ok"] = False
        results["errors"].append(f"Reconcile error: {e}")
        print(f"  ❌ LIVE startup reconcile error: {e}")
        import traceback
        traceback.print_exc()

    # Audit log
    with SessionLocal() as db:
        try:
            db.execute(text(
                "INSERT INTO audit_logs (event_type, message, metadata, created_at) "
                "VALUES ('CRASH_RECOVERY', :msg, :meta, :now)"
            ), {
                "msg": f"LIVE startup recovery. Reconcile OK: {results.get('reconcile_ok')}",
                "meta": json.dumps(results),
                "now": now,
            })
            db.commit()
        except Exception as e:
            print(f"[RECOVERY AUDIT] {e}")

    if results.get("errors"):
        _notify(results)


# ============================================================
# LOG + NOTIFY
# ============================================================

def _log_result(results):
    print(f"\n  ✅ Recovery complete:")
    print(f"     Mode:              {results.get('mode')}")
    print(f"     Pending cancelled: {results.get('pending_cancelled', '-')}")
    print(f"     Signals closed:    {results.get('signals_closed', '-')}")
    if results.get("errors"):
        print(f"     Errors:            {len(results['errors'])}")
        for e in results["errors"]:
            print(f"       - {e}")


def _notify(results):
    try:
        from app.services.telegram_service import send_telegram

        mode = results.get("mode", "UNKNOWN")

        if mode == "PAPER":
            msg = (
                f"⚠️ <b>SYSTEM CRASH RECOVERY</b>\n\n"
                f"<b>Mode:</b> PAPER\n"
                f"<b>Downtime:</b> {results.get('downtime_seconds', '?')}s\n"
                f"<b>Pending cancelled:</b> {results.get('pending_cancelled', 0)}\n"
                f"<b>Signals closed:</b> {results.get('signals_closed', 0)}\n"
            )
        else:
            msg = (
                f"⚠️ <b>LIVE STARTUP RECOVERY</b>\n\n"
                f"<b>Mode:</b> LIVE\n"
                f"<b>Reconcile OK:</b> {results.get('reconcile_ok', False)}\n"
            )

        if results.get("errors"):
            msg += f"\n⚠️ Errors: {len(results['errors'])}"
            for e in results["errors"][:3]:
                msg += f"\n  - {e}"

        send_telegram(msg)
    except Exception as e:
        print(f"[CRASH RECOVERY NOTIFY] {e}")