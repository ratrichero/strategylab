"""
Live Advisory Monitor
=====================
- Profit Protection trigger
- Profit Lock check

QUAN TRỌNG:
- Protection trigger phải carry level_key xuống command
- Nếu level đã apply rồi thì không được lặp lại
"""

from datetime import timedelta
from typing import Optional, Dict

from app.core.time_utils import utc_now
from app.db.session import SessionLocal
from app.db.models import Signal, ExecutionCommand
from app.services.live.protection_service import (
    is_protection_enabled,
    check_breakeven_condition,
)
from app.services.live.command_service import (
    request_protection_replace,
    has_open_command,
    CMD_PROTECTION_REPLACE,
)


CMD_PROFIT_LOCK = "PROFIT_LOCK"


def run_advisory_cycle(price_map: Optional[Dict[str, float]] = None):
    """
    Main entry point cho advisory monitor.
    Gọi từ live_advisory_loop.
    """
    if not price_map:
        try:
            from app.services.price_feed import get_all_current_prices
            price_map = get_all_current_prices()
        except Exception:
            price_map = {}

    if not price_map:
        return

    if is_protection_enabled():
        _check_all_protection(price_map)

    _check_profit_lock(price_map)


def _check_all_protection(price_map: dict):
    with SessionLocal() as db:
        open_trades = db.query(Signal).filter(
            Signal.status == "OPEN"
        ).all()

        if not open_trades:
            return

        for trade in open_trades:
            try:
                _check_trade_protection(db, trade, price_map)
            except Exception as e:
                print(f"[ADVISORY] {trade.symbol}: {type(e).__name__}: {e}")


def _check_trade_protection(db, trade: Signal, price_map: dict):
    current = price_map.get(trade.symbol)
    if current is None:
        return

    current = float(current)

    if has_open_command(db, trade.symbol, [CMD_PROTECTION_REPLACE]):
        return

    should_trigger, new_sl, level_key, level_cfg = check_breakeven_condition(trade, current)

    if not should_trigger or new_sl is None or not level_key:
        return

    result = request_protection_replace(
        signal_id=trade.id,
        new_sl_price=float(new_sl),
        level_key=level_key,
        level_cfg=level_cfg or {},
    )

    if result.get("success") and not result.get("deduped"):
        print(
            f"🛡️ [ADVISORY] {trade.symbol} hit protection trigger "
            f"| current={current:.4f} new_sl={new_sl:.4f}"
        )


def _check_profit_lock(price_map: dict):
    """
    Auto close tất cả positions khi tổng PnL thực tế >= threshold.

    PnL tính theo % (KHÔNG tính leverage):
      LONG:  (current - entry) / entry * 100
      SHORT: (entry - current) / entry * 100
      Tổng = sum of all OPEN trades
    """
    try:
        from app.services.live.profit_lock_service import (
            check_profit_lock_condition,
            mark_triggered,
        )

        with SessionLocal() as db:
            existing_lock = db.query(ExecutionCommand).filter(
                ExecutionCommand.command_type == CMD_PROFIT_LOCK,
                ExecutionCommand.status.in_(["REQUESTED", "SENT"]),
                ExecutionCommand.created_at >= utc_now() - timedelta(minutes=5),
            ).first()

            if existing_lock:
                return

        if not check_profit_lock_condition(price_map):
            return

        print("🎯 [PROFIT LOCK] Executing profit lock...")

        from app.services.live.command_service import request_kill_switch_all
        result = request_kill_switch_all()
        mark_triggered()

        try:
            with SessionLocal() as db:
                recent_cmds = db.query(ExecutionCommand).filter(
                    ExecutionCommand.command_type == "KILL_SWITCH",
                    ExecutionCommand.created_at >= utc_now() - timedelta(seconds=10),
                ).all()

                for cmd in recent_cmds:
                    cmd.command_type = CMD_PROFIT_LOCK
                    if cmd.request_payload:
                        payload = dict(cmd.request_payload)
                        payload["reason"] = "PROFIT_LOCK"
                        cmd.request_payload = payload

                db.commit()
        except Exception as e:
            print(f"[PROFIT LOCK] Re-tag error: {e}")

        print(f"🎯 [PROFIT LOCK] Result: {result}")

        try:
            from app.services.telegram_service import send_telegram
            send_telegram(
                f"🎯 <b>PROFIT LOCK TRIGGERED</b>\n\n"
                f"Tổng PnL đạt ngưỡng chốt lãi.\n"
                f"Đã đóng tất cả vị thế."
            )
        except Exception:
            pass

    except Exception as e:
        print(f"[ADVISORY PROFIT LOCK] {e}")