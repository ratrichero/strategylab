import app.core.env_bootstrap
import os
import asyncio
import threading
import traceback
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI

from app.core.trading_mode import get_current_mode, TradingMode
from app.core.time_utils import utc_now, vn_now_str
from app.core.bg_runner import clear_shutdown, mark_shutdown
from app.services.price_feed import start_price_feed, stop_price_feed, get_price_feed, add_price_callback
from app.services.volatility_alert_service import register_volatility_alerts
from app.services.binance_user_stream_service import start_user_stream, stop_user_stream
from app.services.config_service import get_runtime_config
from app.core.config import get_telegram_token
from app.core.app_role import get_app_role, is_admin, is_bot
from app.auth.migration import run_auth_migration

# ── Refactored Modules ───────────────────────────────────────
from app.core.middleware import setup_middleware
from app.core.app_setup import setup_app
from app.core.background_tasks import get_background_tasks, scan_queue
from app.core.price_callback import on_price_update, set_main_loop

import logging
logging.getLogger("asyncio").setLevel(logging.CRITICAL)

# ── Globals ───────────────────────────────────────────────────
_main_loop: Optional[asyncio.AbstractEventLoop] = None


# ── Lifespan ──────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _main_loop
    
    clear_shutdown()

    # Database lifecycle:
    # ADMIN binds DATABASE_URL immediately, then runs auth + control migrations.
    # BOT must activate/cache-bootstrap first to obtain its own DB URL, then
    # bind the runtime DB and run bot-local auth/schema checks.
    _bot_runtime_ref = None
    if is_admin():
        from app.db.session import configure_database
        admin_database_url = os.getenv("DATABASE_URL", "").strip()
        configure_database(admin_database_url)

        run_auth_migration()
        try:
            from app.control.migration import run_control_plane_migration
            run_control_plane_migration()
        except ImportError:
            pass
        except Exception as e:
            print(f"[CONTROL MIGRATION] {e}")

    elif is_bot():
        try:
            from app.bot_runtime.runtime import get_bot_runtime
            from app.bot_runtime.runtime_gate import get_runtime_gate

            bot_runtime = get_bot_runtime()
            bot_runtime.startup()
            _bot_runtime_ref = bot_runtime

            # Auth migration must run after bot DB has been bound.
            run_auth_migration()

            gate = get_runtime_gate()
            gate.update(
                status=bot_runtime.state.license_status,
                license_expires_at=bot_runtime.state.license_expires_at,
                monitor_only=bot_runtime.is_monitor_only(),
            )
        except Exception as e:
            print(f"[BOT RUNTIME] Startup failed: {e}")
            raise e

    # FAIL-FAST: check schema after the correct DB has been bound.
    from app.services.schema_guard import assert_schema_ok
    try:
        print("🔍 Checking Database Schema...")
        assert_schema_ok()
        print("✅ Schema valid")
    except Exception as e:
        print(f"❌ CRITICAL ERROR: {e}")
        raise e

    _main_loop = asyncio.get_running_loop()

    print("=" * 60)
    print("🚀 STRATEGY LAB RESEARCH v5.0")
    print(f"   APP_ROLE: {get_app_role()}")
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

    # Price Feed
    print("\n📡 Price Feed...")
    set_main_loop(_main_loop)
    add_price_callback(on_price_update)
    register_volatility_alerts()
    start_price_feed()

    feed = get_price_feed()
    if feed.wait_ready(timeout=15):
        print(f"✅ Feed ready: {feed.get_stats()['symbols_count']} symbols")
    else:
        print("⚠️ Feed: timeout, running in fallback mode")

    # Background tasks
    print("⚙️  Background tasks...")
    tasks = [
        asyncio.create_task(task, name=name)
        for task, name in zip(get_background_tasks(), ["heartbeat", "scheduler", "scan_worker", "mv_refresh", "report"])
    ]

    # ← CHANGED: Bot heartbeat task (chỉ khi BOT mode)
    if is_bot() and _bot_runtime_ref and _bot_runtime_ref.license_client:
        from app.bot_runtime.heartbeat_task import bot_heartbeat_loop
        tasks.append(asyncio.create_task(
            bot_heartbeat_loop(
                license_client=_bot_runtime_ref.license_client,
                interval_sec=_bot_runtime_ref.state.heartbeat_interval_sec,
            ),
            name="bot_heartbeat"
        ))
        print("  💓 Bot heartbeat task registered")

    if mode != TradingMode.PAPER:
        start_user_stream()
        from app.services.live.runtime import (
            live_intent_loop,
            live_reconcile_loop,
            live_advisory_loop,
        )
        tasks.append(asyncio.create_task(live_intent_loop(),    name="live_intent"))
        tasks.append(asyncio.create_task(live_reconcile_loop(), name="live_reconcile"))
        tasks.append(asyncio.create_task(live_advisory_loop(),  name="live_advisory"))
        print("  ✅ LIVE loops registered (intent + reconcile + advisory)")
    else:
        print("  📋 PAPER mode — using price callback monitor")

    # Telegram bot — resolve token/runtime config here
    def start_bot():
        try:
            token = get_telegram_token()

            if not token:
                print("🤖 Bot disabled: no telegram token configured")
                return

            print("🤖 Bot start requested")
            from app.bot.telegram_bot import run_bot
            run_bot(token)
        except Exception as e:
            print(f"[BOT] {e}")

    threading.Thread(target=start_bot, daemon=True, name="Bot").start()

    print("✅ All systems GO")
    print("=" * 60)

    yield

    # Shutdown
    print(f"\n🛑 Shutting down... [{vn_now_str()}]")
    mark_shutdown()

    _main_loop = None

    stop_price_feed()
    stop_user_stream()

    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    try:
        from app.db.async_pool import close_async_pool
        await close_async_pool()
    except Exception:
        pass

    print(f"✅ Shutdown complete [{vn_now_str()}]")


# ── App ───────────────────────────────────────────────────────

_api_docs_exposed = (
    is_admin()
    and os.getenv("EXPOSE_API_DOCS", "false").strip().lower() == "true"
)

app = FastAPI(
    title="Strategy Research Lab v5.0",
    version="5.0",
    lifespan=lifespan,
    docs_url="/docs" if _api_docs_exposed else None,
    redoc_url="/redoc" if _api_docs_exposed else None,
    openapi_url="/openapi.json" if _api_docs_exposed else None,
)

# Setup app components
setup_middleware(app)
setup_app(app)
