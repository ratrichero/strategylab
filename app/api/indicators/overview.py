"""Indicators Overview API — KPI metrics for IndicatorsPage."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, profit_factor_for_json, to_float

router = APIRouter(tags=["Indicators - Overview"])


class IndicatorsOverviewRequest(AnalyticsFilter):
    pass


class IndicatorsOverviewResponse(BaseModel):
    total: int
    win_rate: float
    profit_factor: float
    expectancy: float


@router.post("/api/indicators/overview")
async def indicators_overview(body: IndicatorsOverviewRequest) -> IndicatorsOverviewResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                s.status,
                s.result_percent
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            """,
            *sql_filter.params,
        )

    total = len(rows)
    if total == 0:
        return IndicatorsOverviewResponse(
            total=0,
            win_rate=0.0,
            profit_factor=0.0,
            expectancy=0.0,
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

    return IndicatorsOverviewResponse(
        total=total,
        win_rate=round(win_rate, 1),
        profit_factor=round(profit_factor, 2),
        expectancy=round(expectancy, 2),
    )
