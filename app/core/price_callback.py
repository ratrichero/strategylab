"""
Price callback handlers for PAPER mode.
Contains price update processing and paper monitor logic.
"""

import asyncio
import threading
import traceback
from typing import Optional

from app.core.bg_runner import is_shutting_down, start_daemon_job
from app.core.trading_mode import get_current_mode, TradingMode
from app.services.config_service import get_runtime_config


# Global state for price callback
_main_loop: Optional[asyncio.AbstractEventLoop] = None
_last_monitor_run: float = 0
MONITOR_THROTTLE = 2.0

_monitor_running = False
_monitor_lock = threading.Lock()


def set_main_loop(loop: asyncio.AbstractEventLoop):
    """Set the main event loop for price callback."""
    global _main_loop
    _main_loop = loop


def on_price_update(price_map: dict):
    """
    Callback từ price feed thread.
    PAPER mode: dispatch sang paper monitor.
    LIVE mode: chỉ cache giá, KHÔNG chạy monitor/pending.
    """
    global _main_loop
    if _main_loop is None or _main_loop.is_closed():
        return

    if is_shutting_down():
        return

    # LIVE mode: price callback không trigger paper monitor
    if get_current_mode() != TradingMode.PAPER:
        return

    try:
        asyncio.run_coroutine_threadsafe(
            _process_price_update_paper(price_map),
            _main_loop
        )
    except Exception as e:
        print(f"[PRICE CALLBACK] {e}")


async def _process_price_update_paper(price_map: dict):
    """Process price update in PAPER mode."""
    import time
    global _last_monitor_run

    now = time.time()
    if now - _last_monitor_run < MONITOR_THROTTLE:
        return
    _last_monitor_run = now

    cfg = get_runtime_config()
    if not cfg.get("ENABLE_MONITOR", True):
        return

    try:
        start_daemon_job("paper_monitor", _run_paper_monitor, price_map)
    except Exception as e:
        print(f"[PAPER MONITOR ERROR] {e}")
        traceback.print_exc()


def _run_paper_monitor(price_map: dict):
    """
    PAPER ONLY monitor cycle.
    Chỉ cho phép 1 cycle chạy tại 1 thời điểm.
    """
    global _monitor_running

    with _monitor_lock:
        if _monitor_running:
            return
        _monitor_running = True

    try:
        from app.services.pending_engine import process_pending_signals
        from app.services.trade_monitor import monitor_open_trades

        try:
            process_pending_signals(price_map=price_map)
        except Exception as e:
            print(f"[PAPER PENDING ERROR] {type(e).__name__}: {e}")
            traceback.print_exc()

        try:
            monitor_open_trades(price_map=price_map)
        except Exception as e:
            print(f"[PAPER MONITOR ERROR] {type(e).__name__}: {e}")
            traceback.print_exc()

    finally:
        with _monitor_lock:
            _monitor_running = False
