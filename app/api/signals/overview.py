"""Signals Overview API — KPI metrics for SignalsPage."""
from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, profit_factor_for_json, to_float

router = APIRouter(tags=["Signals - Overview"])


class SignalsOverviewRequest(AnalyticsFilter):
    initial_capital: float = 10000.0
    position_size: float = 1000.0


class SignalsOverviewResponse(BaseModel):
    nav: float
    total: int
    scanned: int
    win_rate: float
    profit_factor: float
    expectancy: float
    score_return_corr: float


@router.post("/api/signals/overview")
async def signals_overview(body: SignalsOverviewRequest) -> SignalsOverviewResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        # Fetch closed trades for KPI calculation
        rows = await conn.fetch(
            f"""
            SELECT
                s.status,
                s.result_percent,
                s.score
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            """,
            *sql_filter.params,
        )

    total = len(rows)
    if total == 0:
        return SignalsOverviewResponse(
            nav=body.initial_capital,
            total=0,
            scanned=0,
            win_rate=0.0,
            profit_factor=0.0,
            expectancy=0.0,
            score_return_corr=0.0,
        )

    wins = sum(1 for r in rows if r["status"] == "WIN")
    win_rate = (wins / total * 100)

    # Profit factor
    result_percents = [to_float(r["result_percent"]) for r in rows]
    gains = sum(rp for rp in result_percents if rp > 0)
    losses_abs = abs(sum(rp for rp in result_percents if rp < 0))
    profit_factor = profit_factor_for_json(gains, losses_abs)

    # Expectancy
    win_rows = [rp for rp in result_percents if rp > 0]
    loss_rows = [rp for rp in result_percents if rp < 0]
    avg_win = sum(win_rows) / len(win_rows) if win_rows else 0.0
    avg_loss = abs(sum(loss_rows) / len(loss_rows)) if loss_rows else 0.0
    expectancy = (win_rate / 100) * avg_win - ((1 - win_rate / 100) * avg_loss)

    # NAV with compounding
    nav = body.initial_capital
    for r in rows:
        nav += to_float(body.position_size) * (to_float(r["result_percent"]) / 100)

    # Score to return correlation
    scores = [to_float(r["score"]) for r in rows if r["score"] is not None]
    returns = result_percents
    if len(scores) >= 2 and len(returns) >= 2:
        n = len(scores)
        avg_score = sum(scores) / n
        avg_ret = sum(returns) / n
        cov = sum((scores[i] - avg_score) * (returns[i] - avg_ret) for i in range(n)) / n
        std_score = math.sqrt(sum((s - avg_score) ** 2 for s in scores) / n)
        std_ret = math.sqrt(sum((r - avg_ret) ** 2 for r in returns) / n)
        score_return_corr = (cov / (std_score * std_ret)) if std_score > 0 and std_ret > 0 else 0.0
    else:
        score_return_corr = 0.0

    # Scanned count - fetch from funnel if available, otherwise 0
    # This is a separate query that depends on scan_debug table
    scanned = 0  # Placeholder - would need separate endpoint or query

    return SignalsOverviewResponse(
        nav=round(nav, 2),
        total=total,
        scanned=scanned,
        win_rate=round(win_rate, 1),
        profit_factor=round(profit_factor, 2),
        expectancy=round(expectancy, 2),
        score_return_corr=round(score_return_corr, 3),
    )
