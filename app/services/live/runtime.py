"""
Live Runtime Loops
==================
3 loops riêng cho LIVE mode:
1. intent_loop     — validate + place pending entries
2. reconcile_loop  — sync exchange → derive state → finalize
3. advisory_loop   — profit protection + deferred outcome save

NOTE:
- Không dùng asyncio.to_thread cho job dài nữa
- Dùng daemon background runner để shutdown nhanh hơn
"""

import asyncio

from app.core.trading_mode import get_current_mode, TradingMode
from app.services.config_service import get_runtime_config
from app.services.live.intent_engine import process_live_pending_intents
from app.services.live.reconciler import (
    reconcile_all_active_symbols,
    run_deferred_outcomes,
    backfill_missing_outcomes,
)
from app.services.live.advisory_monitor import run_advisory_cycle
from app.core.bg_runner import start_daemon_job, is_shutting_down


def _run_live_advisory_bundle():
    run_advisory_cycle()
    run_deferred_outcomes()
    backfill_missing_outcomes()


async def live_intent_loop():
    """
    Xử lý pending E0: validate + place entry.
    Interval: 1s
    """
    while True:
        await asyncio.sleep(1.0)

        if is_shutting_down():
            return

        if get_current_mode() == TradingMode.PAPER:
            continue

        cfg = get_runtime_config()
        if not cfg.get("ENABLE_MONITOR", True):
            continue

        start_daemon_job("live_intent", process_live_pending_intents)


async def live_reconcile_loop():
    """
    Sync exchange state → derive lifecycle → finalize.
    Interval: 1s
    """
    while True:
        await asyncio.sleep(1.0)

        if is_shutting_down():
            return

        if get_current_mode() == TradingMode.PAPER:
            continue

        cfg = get_runtime_config()
        if not cfg.get("ENABLE_MONITOR", True):
            continue

        start_daemon_job("live_reconcile", reconcile_all_active_symbols)


async def live_advisory_loop():
    """
    Profit protection + deferred outcome save.
    Interval: 2s
    """
    while True:
        await asyncio.sleep(2.0)

        if is_shutting_down():
            return

        if get_current_mode() == TradingMode.PAPER:
            continue

        cfg = get_runtime_config()
        if not cfg.get("ENABLE_MONITOR", True):
            continue

        start_daemon_job("live_advisory", _run_live_advisory_bundle)