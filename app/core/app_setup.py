"""
App setup for FastAPI application.
Contains CORS configuration, router mounting, and SPA handling.
"""

import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.core.app_role import is_admin, is_bot
from app.auth.routes import router as auth_router
from app.control.admin_routes import router as admin_routes_router
from app.control.bot_api import router as bot_api_router
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
from app.api.dashboard.analytics import router as dash_analytics_router
from app.api.dashboard.analysis import router as dash_analysis_router
from app.api.dashboard.edge import router as dash_edge_router
from app.api.dashboard.config_api import router as dash_config_router
from app.api.dashboard.performance_api import router as dash_perf_router
from app.api.dashboard.pending_api import router as dash_pending_router
from app.api.dashboard.overview import router as dash_overview_router
from app.api.dashboard.portfolio import router as dash_portfolio_router
from app.api.dashboard.breakdowns import router as dash_breakdowns_router
from app.api.dashboard.recent_trades import router as dash_recent_trades_router
from app.api.signals.overview import router as signals_overview_router
from app.api.signals.group_performance import router as signals_group_performance_router
from app.api.signals.heatmaps import router as signals_heatmaps_router
from app.api.signals.indicator_distribution import router as signals_indicator_distribution_router
from app.api.signals.trades import router as signals_trades_router
from app.api.indicators.overview import router as indicators_overview_router
from app.api.indicators.thresholds import router as indicators_thresholds_router
from app.api.indicators.distribution import router as indicators_distribution_router
from app.api.indicators.outcome_averages import router as indicators_outcome_averages_router
from app.api.indicators.scatter import router as indicators_scatter_router
from app.api.indicators.regime_fingerprint import router as indicators_regime_fingerprint_router
from app.api.manual_behavior.overview import router as manual_behavior_overview_router
from app.api.manual_behavior.comparison import router as manual_behavior_comparison_router
from app.api.manual_behavior.trades import router as manual_behavior_trades_router
from app.api.price_feed_status import router as price_feed_status_router
from app.api.backtest_replay import router as backtest_replay_router
from app.api.live_settings import router as live_settings_router
from app.api.account import router as account_router


def setup_cors(app: FastAPI):
    """
    Setup CORS middleware for the FastAPI app.
    """
    _cors_origins_raw = os.getenv("CORS_ORIGINS", "*")
    _cors_origins = [
        origin.strip()
        for origin in _cors_origins_raw.split(",")
        if origin.strip()
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"]
    )


def setup_routers(app: FastAPI):
    """
    Mount all routers to the FastAPI app.
    """
    # Auth routes (public — không cần auth, đã whitelist)
    app.include_router(auth_router)

    # Control plane routes
    # (admin_routes cần require_admin dependency bên trong)
    # (bot_api cần bot machine auth bên trong)
    if is_admin():
        app.include_router(admin_routes_router)
        app.include_router(bot_api_router)

    # Trading/Dashboard routes (protected by auth middleware)
    for r in [
        health_router, scan_router, ml_router, performance_router,
        assistant_router, report_router, report_history_router,
        telegram_webhook_router, config_router, monitor_trade_router,
        retrain_router, signal_analysis_router, system_router,
        dash_signals_router, dash_research_router, dash_analytics_router, dash_analysis_router,
        dash_edge_router, dash_config_router, dash_perf_router,
        dash_pending_router, price_feed_status_router, account_router,
        backtest_replay_router, live_settings_router,
        dash_overview_router, dash_portfolio_router, dash_breakdowns_router, dash_recent_trades_router,
        signals_overview_router, signals_group_performance_router, signals_heatmaps_router,
        signals_indicator_distribution_router, signals_trades_router,
        indicators_overview_router, indicators_thresholds_router, indicators_distribution_router,
        indicators_outcome_averages_router, indicators_scatter_router, indicators_regime_fingerprint_router,
        manual_behavior_overview_router, manual_behavior_comparison_router, manual_behavior_trades_router,
    ]:
        app.include_router(r)


def setup_spa(app: FastAPI):
    """
    Setup SPA (Single Page Application) serving.
    """
    _DIST = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "dist")
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


def setup_root_redirect(app: FastAPI):
    """
    Setup root path redirect to dashboard.
    """
    @app.get("/")
    async def root():
        return RedirectResponse(url="/dashboard")


def setup_app(app: FastAPI):
    """
    Setup all app components: CORS, routers, SPA, root redirect.
    """
    setup_cors(app)
    setup_routers(app)
    setup_spa(app)
    setup_root_redirect(app)
