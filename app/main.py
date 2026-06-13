# app/main.py — CLEAN VERSION

import os
import asyncio
import threading
import traceback
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import TELEGRAM_TOKEN
from app.core.trading_mode import get_trading_mode
from app.services.price_feed import (
    start_price_feed, stop_price_feed,
    get_price_feed, add_price_callback
)
from app.services.config_service import get_runtime_config

# ── Routers ───────────────────────────────────────────────────
from app.api.health import router as health_router
from app.api.scan import router as scan_router
from app.api.ml import router as ml_router
from app.api.performance import router as performance_router
from app.api.assistant import router as assistant_router
from app.api.report import router as report_router
from app.api.report_history import router as report_history_router
from app.api.telegram_webhook import router as telegram_webhook_router
from app.api.config import router as config_router
from app.api.monitor_trade import router as monitor_trade_router
from app.api.retrain import router as retrain_router
from app.api.signal_analysis_handler import router as signal_analysis_router
from app.api.system import router as system_router

from app.api.dashboard.signals import router as dash_signals_router
from app.api.dashboard.research import router as dash_research_router
from app.api.dashboard.analysis import router as dash_analysis_router
from app.api.dashboard.edge import router as dash_edge_router
from app.api.dashboard.config_api import router as dash_config_router
from app.api.dashboard.performance_api import router as dash_perf_router

from asyncio import Queue as AsyncQueue

import logging
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# ── Globals ───────────────────────────────────────────────────

scan_queue: AsyncQueue = AsyncQueue()
_main_loop: Optional[asyncio.AbstractEventLoop] = None
_last_monitor_run: float = 0
MONITOR_THROTTLE = 2.0


# ── Price Update Handler ─────────────────────────────────────

async def on_price_update(price_map: dict):
    global _main_loop
    if _main_loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(
            _process_price_update(price_map), _main_loop)
    except Exception as e:
        print(f"[PRICE CALLBACK] {e}")


async def _process_price_update(price_map: dict):
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
        await asyncio.to_thread(_run_monitor, price_map)
    except Exception as e:
        print(f"[MONITOR ERROR] {e}")


def _run_monitor(price_map: dict):
    from app.services.pending_engine import process_pending_signals
    from app.services.trade_monitor import monitor_open_trades
    try:
        process_pending_signals(price_map=price_map)
    except Exception as e:
        print(f"[PENDING ENGINE ERROR] {e}")
    try:
        monitor_open_trades(price_map=price_map)
    except Exception as e:
        print(f"[TRADE MONITOR ERROR] {e}")


# ── Background Tasks ─────────────────────────────────────────

async def scan_worker():
    while True:
        timeframe = await scan_queue.get()
        try:
            vn = datetime.now(timezone(timedelta(hours=7)))
            print(f"🚀 [SCAN] {timeframe} | {vn.strftime('%Y-%m-%d %H:%M:%S')}")
            from app.services.signal_service import run_market_scan_single_tf
            await asyncio.to_thread(run_market_scan_single_tf, timeframe)
            print(f"✅ [SCAN DONE] {timeframe} Time: {datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")}")
        except Exception as e:
            print(f"[SCAN ERROR] {e}")
            traceback.print_exc()
        finally:
            scan_queue.task_done()


async def scheduler_loop():
    last = {"15m": None, "1h": None, "4h": None}
    while True:
        cfg = get_runtime_config()
        if not cfg.get("ENABLE_SCHEDULER", True):
            await asyncio.sleep(5)
            continue
        now = datetime.now()
        if now.minute in [1, 16, 31, 46] and last["15m"] != now.minute:
            await scan_queue.put("15m"); last["15m"] = now.minute
        if now.minute == 1 and last["1h"] != now.hour:
            await scan_queue.put("1h"); last["1h"] = now.hour
        if now.minute == 1 and now.hour % 4 == 0 and last["4h"] != now.hour:
            await scan_queue.put("4h"); last["4h"] = now.hour
        await asyncio.sleep(1)


async def heartbeat_loop():
    from app.services.crash_recovery import update_heartbeat
    while True:
        await asyncio.sleep(30)
        try:
            await asyncio.to_thread(update_heartbeat)
        except Exception as e:
            print(f"[HEARTBEAT] {e}")


async def mv_refresh_loop():
    while True:
        await asyncio.sleep(600)
        try:
            from app.services.mv_refresh import _do_refresh
            await asyncio.to_thread(_do_refresh)
        except Exception as e:
            print(f"[MV REFRESH] {e}")


async def report_scheduler_loop():
    _ld = _lw = _lm = None
    while True:
        await asyncio.sleep(60)
        try:
            vn = datetime.now(timezone(timedelta(hours=7)))
            if vn.hour == 8 and vn.minute == 0 and _ld != vn.date():
                _ld = vn.date()
                from app.services.report_service import send_daily
                await asyncio.to_thread(send_daily)
            if vn.weekday() == 0 and vn.hour == 8 and vn.minute == 0 and _lw != vn.date():
                _lw = vn.date()
                from app.services.report_service import send_weekly
                await asyncio.to_thread(send_weekly)
            if vn.day == 1 and vn.hour == 8 and vn.minute == 0 and _lm != vn.month:
                _lm = vn.month
                from app.services.report_service import send_monthly
                await asyncio.to_thread(send_monthly)
        except Exception as e:
            print(f"[REPORT] {e}")


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop
    _main_loop = asyncio.get_event_loop()
    print("=" * 60)
    print("🚀 STRATEGY LAPB RESEARCH LAB v5.0")
    print("=" * 60)

    from app.services.crash_recovery import check_and_recover
    check_and_recover()

    from app.db.async_pool import get_async_pool
    try:
        await get_async_pool()
    except Exception as e:
        print(f"⚠️ Async pool: {e}")

    print(f"  Mode: {get_trading_mode().get_mode().value}")

    print("\n📡 Price Feed...")
    add_price_callback(on_price_update)
    start_price_feed()
    feed = get_price_feed()
    if feed.wait_ready(timeout=10):
        print(f"✅ Feed: {feed.get_stats()['symbols_count']} symbols")
    else:
        print("⚠️ Feed: fallback")

    print("⚙️ Background tasks...")
    tasks = [
        asyncio.create_task(heartbeat_loop()),
        asyncio.create_task(scheduler_loop()),
        asyncio.create_task(scan_worker()),
        asyncio.create_task(mv_refresh_loop()),
        asyncio.create_task(report_scheduler_loop()),
    ]

    def start_bot():
        try:
            from app.bot.telegram_bot import run_bot
            run_bot(TELEGRAM_TOKEN)
        except Exception as e:
            print(f"[BOT] {e}")

    threading.Thread(target=start_bot, daemon=True, name="Bot").start()
    print("🤖 Bot started\n✅ All GO")
    print("=" * 60)

    yield

    print("\n🛑 Shutting down...")
    stop_price_feed()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    try:
        from app.db.async_pool import close_async_pool
        await close_async_pool()
    except:
        pass
    print("✅ Done")


# ── App ───────────────────────────────────────────────────────

app = FastAPI(title="Strategy Research Lab v2.0", version="2.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware, allow_origins=["*"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Register all routers
for r in [
    health_router, scan_router, ml_router, performance_router,
    assistant_router, report_router, report_history_router,
    telegram_webhook_router, config_router, monitor_trade_router,
    retrain_router, signal_analysis_router, system_router,
    dash_signals_router, dash_research_router, dash_analysis_router,
    dash_edge_router, dash_config_router, dash_perf_router,
]:
    app.include_router(r)


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


# ── SPA Frontend ──────────────────────────────────────────────

_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dist")
if os.path.exists(_DIST):
    _assets = os.path.join(_DIST, "assets")
    if os.path.exists(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        fp = os.path.join(_DIST, path)
        if os.path.exists(fp) and os.path.isfile(fp):
            return FileResponse(fp)
        return FileResponse(os.path.join(_DIST, "index.html"))


@app.exception_handler(Exception)
async def err(request: Request, exc: Exception):
    e = f"{type(exc).__name__}: {exc}"
    print(f"\n{'='*60}\n🚨 {e}\n{traceback.format_exc()}{'='*60}")
    return JSONResponse(500, {"error": e})