"""
Kill Switch Service
===================
PAPER:  local bulk cancel/close như cũ
LIVE:   dùng command_service -> reconciler finalize
"""

import time as time_module
import json
from typing import Dict

from app.core.time_utils import utc_now
from app.core.trading_mode import get_current_mode, TradingMode
from app.db.session import SessionLocal
from app.db.models import Signal, PendingSignal
from sqlalchemy import text


def execute_kill_switch() -> Dict:
    mode = get_current_mode()

    if mode != TradingMode.PAPER:
        return _kill_switch_live()

    return _kill_switch_paper()


# ============================================================
# PAPER — giữ nguyên behavior cũ
# ============================================================

def _kill_switch_paper() -> Dict:
    now = utc_now()

    result = {
        "mode":              "PAPER",
        "timestamp":         now.isoformat(),
        "pending_cancelled": 0,
        "signals_closed":    0,
        "errors":            [],
    }

    with SessionLocal() as db:
        try:
            pending_count = db.query(PendingSignal).filter(
                PendingSignal.status == "WAIT"
            ).update({
                "status": "CANCELLED",
                "rejection_reason": "KILL_SWITCH",
            })
            result["pending_cancelled"] = pending_count

            open_signals = db.query(Signal).filter(
                Signal.status == "OPEN"
            ).all()

            for trade in open_signals:
                trade.status = "MANUAL"
                trade.exit_reason = "KILL_SWITCH"
                trade.exit_time = now
                result["signals_closed"] += 1

            db.execute(text("""
                INSERT INTO audit_logs (event_type, message, metadata, created_at)
                VALUES ('KILL_SWITCH', :msg, :meta, :now)
            """), {
                "msg":  "Kill switch executed. Mode: PAPER",
                "meta": json.dumps(result),
                "now":  now,
            })

            db.commit()

        except Exception as e:
            db.rollback()
            result["errors"].append(f"DB error: {e}")

    _log_result(result)
    _notify(result)
    return result


# ============================================================
# LIVE — delegate to command_service + reconciler
# ============================================================

def _kill_switch_live() -> Dict:
    from app.services.live.command_service import request_kill_switch_all
    from app.services.live.reconciler import reconcile_all_active_symbols

    mode = get_current_mode()
    mode_label = mode.value
    now = utc_now()

    # 1) Gửi commands + exchange cleanup
    cmd_result = request_kill_switch_all()

    # 2) Đợi exchange settle
    time_module.sleep(2)

    # 3) Reconcile tất cả active symbols
    try:
        reconcile_all_active_symbols()
    except Exception as e:
        cmd_result.setdefault("errors", []).append(f"Reconcile error: {e}")
        print(f"[KILL SWITCH] Reconcile error: {e}")

    # 4) Audit log
    with SessionLocal() as db:
        try:
            db.execute(text("""
                INSERT INTO audit_logs (event_type, message, metadata, created_at)
                VALUES ('KILL_SWITCH', :msg, :meta, :now)
            """), {
                "msg":  f"Kill switch executed. Mode: {mode_label}",
                "meta": json.dumps(cmd_result, default=str),
                "now":  now,
            })
            db.commit()
        except Exception as e:
            print(f"[KILL SWITCH AUDIT] {e}")

    result = {
        "mode":              mode_label,
        "timestamp":         now.isoformat(),
        "exchange_cleanup":  cmd_result.get("success", False),
        "local_pending_cancelled": cmd_result.get("local_pending_cancelled", 0),
        "symbols":           cmd_result.get("symbols", []),
        "commands":          cmd_result.get("commands", []),
        "errors":            cmd_result.get("errors", []),
    }

    _log_result(result)
    _notify(result)
    return result


# ============================================================
# LOG + NOTIFY
# ============================================================

def _log_result(result: Dict):
    print("\n" + "=" * 55)
    print("🛑 KILL SWITCH EXECUTED")
    print("=" * 55)
    print(f"  Mode:              {result.get('mode')}")
    print(f"  Pending cancelled: {result.get('pending_cancelled', '-')}")
    print(f"  Signals closed:    {result.get('signals_closed', '-')}")
    print(f"  Exchange cleanup:  {result.get('exchange_cleanup', '-')}")
    if result.get("symbols"):
        print(f"  Symbols:           {result['symbols']}")
    if result.get("errors"):
        print(f"  Errors:            {len(result['errors'])}")
        for e in result["errors"]:
            print(f"    - {e}")
    print("=" * 55 + "\n")


def _notify(result: Dict):
    try:
        from app.services.telegram_service import send_telegram

        mode = result.get("mode", "UNKNOWN")
        msg = (
            f"🛑 <b>Kill switch đã kích hoạt</b>\n\n"
            f"📌 <b>Chế độ:</b> {mode}\n"
        )

        if mode == "PAPER":
            msg += (
                f"⏸ <b>Lệnh chờ đã hủy:</b> {result.get('pending_cancelled', 0)}\n"
                f"🔒 <b>Lệnh đã đóng:</b> {result.get('signals_closed', 0)}\n"
            )
        else:
            msg += (
                f"🧹 <b>Dọn trạng thái sàn:</b> {result.get('exchange_cleanup', False)}\n"
                f"🪙 <b>Số coin ảnh hưởng:</b> {len(result.get('symbols', []))}\n"
                f"📨 <b>Lệnh xử lý:</b> {len(result.get('commands', []))}\n"
            )

        if result.get("errors"):
            msg += f"\n⚠️ <b>Lỗi cần kiểm tra:</b> {len(result['errors'])}"

        send_telegram(msg)
    except Exception as e:
        print(f"[KILL SWITCH NOTIFY] {e}")
