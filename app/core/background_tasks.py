"""
Background tasks for FastAPI application.
Contains scan worker, scheduler, heartbeat, and other periodic tasks.
"""

import asyncio
import traceback
from asyncio import Queue as AsyncQueue

from app.core.time_utils import utc_now, vn_now
from app.core.bg_runner import is_shutting_down, start_daemon_job
from app.core.trading_mode import get_current_mode, TradingMode
from app.services.config_service import get_runtime_config
from app.core.app_role import is_bot


# Global scan queue
scan_queue: AsyncQueue = AsyncQueue()


def _run_scan_job(timeframe: str):
    """Run a single timeframe scan job."""
    print(f"🚀 [SCAN] {timeframe} | {vn_now()}")
    from app.services.signal_service import run_market_scan_single_tf
    run_market_scan_single_tf(timeframe)
    print(f"✅ [SCAN DONE] {timeframe} | {vn_now()}")


async def scan_worker():
    """Scan worker that processes scan jobs from the queue."""
    while True:
        timeframe = await scan_queue.get()
        try:
            while True:
                if is_shutting_down():
                    break

                started = start_daemon_job("scan_worker", _run_scan_job, timeframe)
                if started:
                    break

                await asyncio.sleep(0.5)

        except Exception as e:
            print(f"[SCAN ERROR] {e}")
            traceback.print_exc()
        finally:
            scan_queue.task_done()


async def scheduler_loop():
    """Scheduler loop that enqueues scan jobs based on time."""
    last = {"15m": None, "1h": None, "4h": None}
    while True:
        cfg = get_runtime_config()
        if not cfg.get("ENABLE_SCHEDULER", True):
            await asyncio.sleep(5)
            continue

        # ← CHANGED: Bot runtime gate check
        # Nếu bot monitor_only → không enqueue scan
        if is_bot():
            try:
                from app.bot_runtime.runtime_gate import get_runtime_gate
                gate = get_runtime_gate()
                if gate.is_monitor_only():
                    await asyncio.sleep(5)
                    continue
            except ImportError:
                pass

        now = utc_now()

        # LIVE scheduler pause gate:
        # nếu saturated và local queue đã đủ reserve thì không enqueue scan auto
        if get_current_mode() != TradingMode.PAPER:
            try:
                from app.db.session import SessionLocal
                from app.services.live.capacity_service import get_capacity_snapshot, should_pause_scan

                with SessionLocal() as db:
                    c_config = int(cfg.get("MAX_OPEN_TRADES", 10) or 10)
                    cap = get_capacity_snapshot(db, c_config)

                    if should_pause_scan(cap):
                        await asyncio.sleep(1)
                        continue
            except Exception as e:
                print(f"[SCHEDULER CAPACITY CHECK] {e}")

        if now.minute in [1, 16, 31, 46] and last["15m"] != now.minute:
            await scan_queue.put("15m")
            last["15m"] = now.minute

        if now.minute == 1 and last["1h"] != now.hour:
            await scan_queue.put("1h")
            last["1h"] = now.hour

        if now.minute == 1 and now.hour % 4 == 0 and last["4h"] != now.hour:
            await scan_queue.put("4h")
            last["4h"] = now.hour

        await asyncio.sleep(1)


async def heartbeat_loop():
    """Heartbeat loop that updates crash recovery status."""
    from app.services.crash_recovery import update_heartbeat
    while True:
        await asyncio.sleep(30)
        try:
            if is_shutting_down():
                return
            start_daemon_job("heartbeat", update_heartbeat)
        except Exception as e:
            print(f"[HEARTBEAT] {e}")


async def mv_refresh_loop():
    """MV refresh loop that periodically refreshes market data."""
    while True:
        await asyncio.sleep(600)
        try:
            if is_shutting_down():
                return
            from app.services.mv_refresh import _do_refresh
            start_daemon_job("mv_refresh", _do_refresh)
        except Exception as e:
            print(f"[MV REFRESH] {e}")


async def report_scheduler_loop():
    """Report scheduler loop that sends daily/weekly/monthly reports."""
    _ld = _lw = _lm = None
    while True:
        await asyncio.sleep(60)
        try:
            if is_shutting_down():
                return

            now_vn = vn_now()

            if now_vn.hour == 8 and now_vn.minute == 0 and _ld != now_vn.date():
                _ld = now_vn.date()
                from app.services.trading_agent_service import send_agent_daily
                start_daemon_job("report_daily", send_agent_daily)

            if (now_vn.weekday() == 0 and now_vn.hour == 8
                    and now_vn.minute == 0 and _lw != now_vn.date()):
                _lw = now_vn.date()
                from app.services.trading_agent_service import send_agent_weekly
                start_daemon_job("report_weekly", send_agent_weekly)

            if (now_vn.day == 1 and now_vn.hour == 8
                    and now_vn.minute == 0 and _lm != now_vn.month):
                _lm = now_vn.month
                from app.services.trading_agent_service import send_agent_monthly
                start_daemon_job("report_monthly", send_agent_monthly)

        except Exception as e:
            print(f"[REPORT] {e}")


def get_background_tasks():
    """Return list of background task coroutines."""
    return [
        heartbeat_loop(),
        scheduler_loop(),
        scan_worker(),
        mv_refresh_loop(),
        report_scheduler_loop(),
    ]
