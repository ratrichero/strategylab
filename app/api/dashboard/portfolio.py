"""Dashboard Portfolio API — compounding and fixed equity curves."""
from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, to_float

router = APIRouter(tags=["Dashboard - Portfolio"])


class PortfolioRequest(AnalyticsFilter):
    initial_capital: float = Field(default=10000.0, ge=0)
    position_size: float = Field(default=1000.0, ge=0)


class CurvePoint(BaseModel):
    time: str
    nav: float
    dd: float
    symbol: Optional[str]
    pnl: float
    rp: float


class PortfolioMode(BaseModel):
    initial_capital: float
    final_nav: float
    total_pnl: float
    return_pct: float
    max_dd_pct: float
    max_gain_pct: float
    peak_nav: float
    trough_nav: float
    sharpe: float
    calmar: float
    curve: list[CurvePoint]


class PortfolioResponse(BaseModel):
    compounding: PortfolioMode
    fixed: PortfolioMode


def _calc_sharpe(returns: list[float]) -> float:
    if len(returns) < 2:
        return 0.0
    avg = sum(returns) / len(returns)
    std = math.sqrt(sum((x - avg) ** 2 for x in returns) / len(returns))
    return avg / std if std > 0.0001 else 0.0


@router.post("/api/dashboard/portfolio")
async def dashboard_portfolio(body: PortfolioRequest) -> PortfolioResponse:
    sql_filter = build_sql_filter(body, source="signals", alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                s.exit_time,
                s.symbol,
                s.result_percent
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            ORDER BY s.exit_time ASC
            """,
            *sql_filter.params,
        )

    ic = to_float(body.initial_capital)
    ps = to_float(body.position_size)

    # Compounding
    nav_c = ic
    peak_c = ic
    trough_c = ic
    max_dd_c = 0.0
    max_gain_c = 0.0
    pnl_list_c: list[float] = []
    curve_c: list[CurvePoint] = []

    for r in rows:
        rp = to_float(r["result_percent"])
        dynamic = ps * (nav_c / ic)
        pnl = dynamic * (rp / 100.0)
        nav_c += pnl
        pnl_list_c.append(pnl)
        peak_c = max(peak_c, nav_c)
        trough_c = min(trough_c, nav_c)
        dd = (peak_c - nav_c) / peak_c * 100.0 if peak_c > 0 else 0.0
        max_dd_c = max(max_dd_c, dd)
        max_gain_c = max(max_gain_c, (nav_c - ic) / ic * 100.0)
        curve_c.append(
            CurvePoint(
                time=str(r["exit_time"]),
                nav=round(nav_c, 2),
                dd=round(dd, 2),
                symbol=r["symbol"],
                pnl=round(pnl, 2),
                rp=rp,
            )
        )

    ret_c = ((nav_c - ic) / ic) * 100.0 if ic > 0 else 0.0
    pct_returns_c = [(p / ic) * 100.0 for p in pnl_list_c] if ic > 0 else []
    sharpe_c = _calc_sharpe(pct_returns_c)
    calmar_c = ret_c / max_dd_c if max_dd_c > 0 else 0.0

    # Fixed
    nav_f = ic
    peak_f = ic
    trough_f = ic
    max_dd_f = 0.0
    max_gain_f = 0.0
    pnl_list_f: list[float] = []
    curve_f: list[CurvePoint] = []

    for r in rows:
        rp = to_float(r["result_percent"])
        pnl = ps * (rp / 100.0)
        nav_f += pnl
        pnl_list_f.append(pnl)
        peak_f = max(peak_f, nav_f)
        trough_f = min(trough_f, nav_f)
        dd = (peak_f - nav_f) / peak_f * 100.0 if peak_f > 0 else 0.0
        max_dd_f = max(max_dd_f, dd)
        max_gain_f = max(max_gain_f, (nav_f - ic) / ic * 100.0)
        curve_f.append(
            CurvePoint(
                time=str(r["exit_time"]),
                nav=round(nav_f, 2),
                dd=round(dd, 2),
                symbol=r["symbol"],
                pnl=round(pnl, 2),
                rp=rp,
            )
        )

    ret_f = ((nav_f - ic) / ic) * 100.0 if ic > 0 else 0.0
    pct_returns_f = [(p / ic) * 100.0 for p in pnl_list_f] if ic > 0 else []
    sharpe_f = _calc_sharpe(pct_returns_f)
    calmar_f = ret_f / max_dd_f if max_dd_f > 0 else 0.0

    return PortfolioResponse(
        compounding=PortfolioMode(
            initial_capital=ic,
            final_nav=round(nav_c, 2),
            total_pnl=round(nav_c - ic, 2),
            return_pct=round(ret_c, 2),
            max_dd_pct=round(max_dd_c, 2),
            max_gain_pct=round(max_gain_c, 2),
            peak_nav=round(peak_c, 2),
            trough_nav=round(trough_c, 2),
            sharpe=round(sharpe_c, 2),
            calmar=round(calmar_c, 2),
            curve=curve_c,
        ),
        fixed=PortfolioMode(
            initial_capital=ic,
            final_nav=round(nav_f, 2),
            total_pnl=round(nav_f - ic, 2),
            return_pct=round(ret_f, 2),
            max_dd_pct=round(max_dd_f, 2),
            max_gain_pct=round(max_gain_f, 2),
            peak_nav=round(peak_f, 2),
            trough_nav=round(trough_f, 2),
            sharpe=round(sharpe_f, 2),
            calmar=round(calmar_f, 2),
            curve=curve_f,
        ),
    )
