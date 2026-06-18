import os
import asyncio
import threading
import traceback
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import TELEGRAM_TOKEN
from app.core.trading_mode import get_trading_mode, get_current_mode, TradingMode
from app.core.time_utils import utc_now, vn_now_str
from app.services.price_feed import (
    start_price_feed, stop_price_feed,
    get_price_feed, add_price_callback
)
from app.services.config_service import get_runtime_config
from app.api.account import router as account_router

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
from app.api.signal_analysis_handler_update import router as signal_analysis_router
from app.api.system import router as system_router
from app.api.dashboard.signals import router as dash_signals_router
from app.api.dashboard.research import router as dash_research_router
from app.api.dashboard.analysis import router as dash_analysis_router
from app.api.dashboard.edge import router as dash_edge_router
from app.api.dashboard.config_api import router as dash_config_router
from app.api.dashboard.performance_api import router as dash_perf_router
from app.api.dashboard.pending_api import router as dash_pending_router
from app.api.price_feed_status import router as price_feed_status_router

from app.services.strategy_debug_scanner import run_debug_scan
async def debug_scan_loop():
    """
    Chạy debug scan mỗi 4 giờ.
    Ghi CSV, không đụng DB.
    """
    while True:
        try:
            cfg = get_runtime_config()
            if cfg.get("ENABLE_SCHEDULER", True):
                await asyncio.to_thread(run_debug_scan)
        except Exception as e:
            print(f"[DEBUG SCAN ERROR] {e}")
        await asyncio.sleep(1 * 3600)  # mỗi 1 giờ

from asyncio import Queue as AsyncQueue
import logging
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# ── Globals ───────────────────────────────────────────────────
scan_queue: AsyncQueue = AsyncQueue()
_main_loop: Optional[asyncio.AbstractEventLoop] = None
_last_monitor_run: float = 0
MONITOR_THROTTLE = 2.0

_monitor_running = False
_monitor_lock = threading.Lock()


# ── Price Callback — PAPER ONLY ──────────────────────────────

def on_price_update(price_map: dict):
    """
    Callback từ price feed thread.
    PAPER mode: dispatch sang paper monitor.
    LIVE mode: chỉ cache giá, KHÔNG chạy monitor/pending.
    """
    global _main_loop
    if _main_loop is None or _main_loop.is_closed():
        return

    # LIVE mode: price callback không trigger monitor
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
        await asyncio.to_thread(_run_paper_monitor, price_map)
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


# ── Background Tasks ─────────────────────────────────────────

async def scan_worker():
    while True:
        timeframe = await scan_queue.get()
        try:
            print(f"🚀 [SCAN] {timeframe} | {vn_now_str()}")
            from app.services.signal_service import run_market_scan_single_tf
            await asyncio.to_thread(run_market_scan_single_tf, timeframe)
            print(f"✅ [SCAN DONE] {timeframe} | {vn_now_str()}")
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

        # Dùng UTC để schedule — không dùng local time
        now = utc_now()

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
            # Dùng VN time để check giờ gửi report
            vn = vn_now_str()
            from app.core.time_utils import vn_now
            now_vn = vn_now()

            if now_vn.hour == 8 and now_vn.minute == 0 and _ld != now_vn.date():
                _ld = now_vn.date()
                from app.services.report_service import send_daily
                await asyncio.to_thread(send_daily)

            if (now_vn.weekday() == 0 and now_vn.hour == 8
                    and now_vn.minute == 0 and _lw != now_vn.date()):
                _lw = now_vn.date()
                from app.services.report_service import send_weekly
                await asyncio.to_thread(send_weekly)

            if (now_vn.day == 1 and now_vn.hour == 8
                    and now_vn.minute == 0 and _lm != now_vn.month):
                _lm = now_vn.month
                from app.services.report_service import send_monthly
                await asyncio.to_thread(send_monthly)

        except Exception as e:
            print(f"[REPORT] {e}")


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):

    # 1. FAIL-FAST: Kiểm tra schema trước tiên
    from app.services.schema_guard import assert_schema_ok
    try:
        print("🔍 Checking Database Schema...")
        assert_schema_ok()
        print("✅ Schema valid")
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        raise e

    global _main_loop

    # Set main loop TRƯỚC KHI start price feed
    _main_loop = asyncio.get_running_loop()

    print("=" * 60)
    print("🚀 STRATEGY LAB RESEARCH v5.0")
    print("=" * 60)

    mode = get_current_mode()

    # Crash recovery — mode-aware
    from app.services.crash_recovery import check_and_recover
    await asyncio.to_thread(check_and_recover)

    # Async pool
    from app.db.async_pool import get_async_pool
    try:
        await get_async_pool()
    except Exception as e:
        print(f"⚠️ Async pool: {e}")

    cfg = get_runtime_config(force_reload=True)

    print(f"  Mode: {mode.value}")

    if mode != TradingMode.PAPER:
        print(f"  LIVE monitor enabled: {cfg.get('ENABLE_MONITOR', True)}")
        print(f"  LIVE scheduler enabled: {cfg.get('ENABLE_SCHEDULER', True)}")
        print(f"  LIVE max open trades: {cfg.get('MAX_OPEN_TRADES')}")
        print(f"  LIVE position size cfg: {cfg.get('POSITION_SIZE_CONFIG')}")
        print("  LIVE intent retry policy: hardcoded max_retries=1 backoff=10s")
        if cfg.get("ENABLE_SCHEDULER", True):
            print("  ⚠️ LIVE scheduler is ENABLED — scanner may create real pending/orders automatically")

    # Price Feed — đăng ký callback TRƯỚC khi start
    print("\n📡 Price Feed...")
    add_price_callback(on_price_update)
    start_price_feed()

    feed = get_price_feed()
    if feed.wait_ready(timeout=15):
        print(f"✅ Feed ready: {feed.get_stats()['symbols_count']} symbols")
    else:
        print("⚠️ Feed: timeout, running in fallback mode")

    # Background tasks — common
    print("⚙️  Background tasks...")
    tasks = [
        asyncio.create_task(heartbeat_loop(),        name="heartbeat"),
        asyncio.create_task(scheduler_loop(),        name="scheduler"),
        asyncio.create_task(scan_worker(),           name="scan_worker"),
        asyncio.create_task(mv_refresh_loop(),       name="mv_refresh"),
        asyncio.create_task(report_scheduler_loop(), name="report"),
        #asyncio.create_task(debug_scan_loop(),       name="debug_scan"),
    ]

    # LIVE mode: thêm live loops riêng
    if mode != TradingMode.PAPER:
        from app.services.live.runtime import (
            live_intent_loop,
            live_reconcile_loop,
            live_advisory_loop,
        )
        tasks.append(asyncio.create_task(live_intent_loop(),     name="live_intent"))
        tasks.append(asyncio.create_task(live_reconcile_loop(),  name="live_reconcile"))
        tasks.append(asyncio.create_task(live_advisory_loop(),   name="live_advisory"))
        print("  ✅ LIVE loops registered (intent + reconcile + advisory)")
    else:
        print("  📋 PAPER mode — using price callback monitor")

    def start_bot():
        try:
            from app.bot.telegram_bot import run_bot
            #run_bot(TELEGRAM_TOKEN)
        except Exception as e:
            print(f"[BOT] {e}")

    #threading.Thread(target=start_bot, daemon=True, name="Bot").start()

    print("🤖 Bot started")
    print("✅ All systems GO")
    print("=" * 60)

    yield

    # Shutdown
    print("\n🛑 Shutting down...")
    stop_price_feed()
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    try:
        from app.db.async_pool import close_async_pool
        await close_async_pool()
    except Exception:
        pass
    print("✅ Shutdown complete")


# ── App ───────────────────────────────────────────────────────

app = FastAPI(
    title="Strategy Research Lab v5.0",
    version="5.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

for r in [
    health_router, scan_router, ml_router, performance_router,
    assistant_router, report_router, report_history_router,
    telegram_webhook_router, config_router, monitor_trade_router,
    retrain_router, signal_analysis_router, system_router,
    dash_signals_router, dash_research_router, dash_analysis_router,
    dash_edge_router, dash_config_router, dash_perf_router,
    dash_pending_router, price_feed_status_router, account_router,
]:
    app.include_router(r)


@app.get("/")
async def root():
    return RedirectResponse(url="/dashboard")


# ── SPA ───────────────────────────────────────────────────────

_DIST = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dist")
if os.path.exists(_DIST):
    _assets = os.path.join(_DIST, "assets")
    if os.path.exists(_assets):
        app.mount("/assets", StaticFiles(directory=_assets), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)
        fp = os.path.join(_DIST, path)
        if os.path.exists(fp) and os.path.isfile(fp):
            return FileResponse(fp)
        return FileResponse(os.path.join(_DIST, "index.html"))


@app.exception_handler(Exception)
async def global_error(request: Request, exc: Exception):
    e = f"{type(exc).__name__}: {exc}"
    print(f"\n{'='*60}\n🚨 {e}\n{traceback.format_exc()}{'='*60}")
    return JSONResponse(status_code=500, content={"error": e})