# app/services/crash_recovery.py

import os
import time
from datetime import datetime, timedelta
from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from sqlalchemy import text
from app.core.time_utils import utc_now, ensure_utc


# Ngưỡng downtime (giây) để coi là crash
RECOVERY_THRESHOLD = int(os.getenv("PAPER_RECOVERY_THRESHOLD_SECONDS", "120"))


def update_heartbeat():
    try:
        now = utc_now()                         # ← đổi
        with SessionLocal() as db:
            db.execute(text(
                "INSERT INTO app_config (key, value, updated_at) "
                "VALUES ('LAST_HEARTBEAT_AT', :v, :now) "
                "ON CONFLICT (key) DO UPDATE SET value = :v, updated_at = :now"
            ), {"v": now.isoformat(), "now": now})  # ← pass Python now, không dùng NOW()
            db.commit()
    except Exception as e:
        print(f"[HEARTBEAT] Error: {e}")


def check_and_recover():
    """
    Chạy khi server startup.
    Nếu downtime > threshold → recover paper state.
    """
    print("\n🔍 Checking for crash recovery...")

    try:
        with SessionLocal() as db:
            # Lấy heartbeat cuối
            row = db.execute(text(
                "SELECT value FROM app_config WHERE key = 'LAST_HEARTBEAT_AT'"
            )).fetchone()

            if not row:
                print("  ℹ️  No heartbeat found — first run, skipping recovery")
                update_heartbeat()
                return

            last_hb = ensure_utc(datetime.fromisoformat(row[0]))
            now = utc_now() 
            downtime_seconds = (now - last_hb).total_seconds()

            print(f"  Last heartbeat: {last_hb.isoformat()}")
            print(f"  Current time:   {now.isoformat()}")
            print(f"  Downtime:       {downtime_seconds:.0f}s (threshold: {RECOVERY_THRESHOLD}s)")

            if downtime_seconds <= RECOVERY_THRESHOLD:
                print("  ✅ Downtime within threshold — no recovery needed")
                update_heartbeat()
                return

            # ── RECOVERY ─────────────────────────────────────
            print(f"\n  ⚠️  CRASH DETECTED — downtime {downtime_seconds:.0f}s > {RECOVERY_THRESHOLD}s")
            print("  🔄 Recovering paper state...")

            # 1. Cancel all pending WAIT
            pending_count = db.query(PendingSignal).filter(
                PendingSignal.status == "WAIT"
            ).update({
                "status": "CANCELLED",
                "rejection_reason": "SYSTEM_CRASH"
            })

            # 2. Close all open signals → MANUAL
            open_trades = db.query(Signal).filter(
                Signal.status == "OPEN"
            ).all()

            trade_count = 0
            for trade in open_trades:
                trade.status = "MANUAL"
                trade.exit_reason = "SYSTEM_CRASH"
                trade.exit_time = now
                # Không set result_percent
                # Không ghi trade_outcome_analytics
                trade_count += 1

            # 3. Log event
            """db.execute(text(
                "INSERT INTO audit_logs (event_type, message, metadata, created_at) "
                "VALUES ('CRASH_RECOVERY', :msg, :meta, :now)"
            ), {
                "msg": f"System crash detected. Downtime: {downtime_seconds:.0f}s",
                "meta": f'{{"downtime_seconds": {downtime_seconds:.0f}, "pending_cancelled": {pending_count}, "trades_closed": {trade_count}, "last_heartbeat": "{last_hb.isoformat()}", "recovery_time": "{now.isoformat()}"}}'
            })"""

            import json
            db.execute(text(
                "INSERT INTO audit_logs (event_type, message, metadata, created_at) "
                "VALUES ('CRASH_RECOVERY', :msg, :meta, :now)"
            ), {
                "msg":  f"Crash detected. Downtime: {downtime_seconds:.0f}s",
                "meta": json.dumps({
                    "downtime_seconds":   round(downtime_seconds),
                    "pending_cancelled":  pending_count,
                    "trades_closed":      trade_count,
                    "last_heartbeat":     last_hb.isoformat(),
                    "recovery_time":      now.isoformat(),
                }),
                "now": now,                         # ← pass Python now
            })

            db.commit()

            print(f"  ✅ Recovery complete:")
            print(f"     Pending cancelled: {pending_count}")
            print(f"     Trades closed:     {trade_count}")

            # Update heartbeat
            update_heartbeat()

    except Exception as e:
        print(f"  ❌ Recovery error: {e}")
        import traceback
        traceback.print_exc()