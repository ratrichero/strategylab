"""
Live Runtime Loops
==================
3 loops riêng cho LIVE mode:
1. intent_loop     — validate + place pending entries
2. reconcile_loop  — sync exchange → derive state → finalize
3. advisory_loop   — profit protection + anomaly detection + deferred outcomes
"""

import asyncio

from app.core.trading_mode import get_current_mode, TradingMode
from app.services.config_service import get_runtime_config
from app.services.live.intent_engine import process_live_pending_intents
from app.services.live.reconciler import reconcile_all_active_symbols, run_deferred_outcomes
from app.services.live.advisory_monitor import run_advisory_cycle


async def live_intent_loop():
    """
    Xử lý pending E0: validate + place entry.
    Interval: 1s
    """
    while True:
        await asyncio.sleep(1.0)

        if get_current_mode() == TradingMode.PAPER:
            continue

        cfg = get_runtime_config()
        if not cfg.get("ENABLE_MONITOR", True):
            continue

        try:
            await asyncio.to_thread(process_live_pending_intents)
        except Exception as e:
            print(f"[LIVE INTENT LOOP] {e}")


async def live_reconcile_loop():
    """
    Sync exchange state → derive lifecycle → finalize.
    Interval: 1s
    """
    while True:
        await asyncio.sleep(1.0)

        if get_current_mode() == TradingMode.PAPER:
            continue

        cfg = get_runtime_config()
        if not cfg.get("ENABLE_MONITOR", True):
            continue

        try:
            await asyncio.to_thread(reconcile_all_active_symbols)
        except Exception as e:
            print(f"[LIVE RECONCILE LOOP] {e}")


async def live_advisory_loop():
    """
    Profit protection + anomaly detection + deferred outcome save.
    Interval: 2s
    """
    while True:
        await asyncio.sleep(2.0)

        if get_current_mode() == TradingMode.PAPER:
            continue

        cfg = get_runtime_config()
        if not cfg.get("ENABLE_MONITOR", True):
            continue

        try:
            await asyncio.to_thread(run_advisory_cycle)
        except Exception as e:
            print(f"[LIVE ADVISORY LOOP] {e}")

        # Drain deferred outcome queue
        # Chạy sau advisory để không cạnh tranh resource với protection logic
        try:
            await asyncio.to_thread(run_deferred_outcomes)
        except Exception as e:
            print(f"[LIVE OUTCOME LOOP] {e}")