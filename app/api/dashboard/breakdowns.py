"""Dashboard Breakdowns API — regime breakdown and pattern/timeframe heatmap."""
from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, to_float

router = APIRouter(tags=["Dashboard - Breakdowns"])


class BreakdownsRequest(AnalyticsFilter):
    pass


class RegimeItem(BaseModel):
    regime: str
    trades: int
    wins: int
    win_rate: float
    expectancy: float
    profit_factor: float
    total_return: float


class HeatmapItem(BaseModel):
    pattern: str
    timeframe: str
    win_rate: float
    count: int


class BreakdownsResponse(BaseModel):
    regime_breakdown: list[RegimeItem]
    heatmap: list[HeatmapItem]


@router.post("/api/dashboard/breakdowns")
async def dashboard_breakdowns(body: BreakdownsRequest) -> BreakdownsResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        # Regime breakdown
        regime_rows = await conn.fetch(
            f"""
            SELECT
                COALESCE(s.regime, 'UNKNOWN') AS regime,
                COUNT(*) AS trades,
                COUNT(*) FILTER (WHERE s.status = 'WIN') AS wins,
                SUM(s.result_percent) AS total_return,
                SUM(CASE WHEN s.result_percent > 0 THEN s.result_percent ELSE 0 END) AS gains,
                SUM(CASE WHEN s.result_percent < 0 THEN ABS(s.result_percent) ELSE 0 END) AS losses_abs
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            GROUP BY COALESCE(s.regime, 'UNKNOWN')
            ORDER BY trades DESC
            """,
            *sql_filter.params,
        )

        # Heatmap: pattern x timeframe
        heatmap_rows = await conn.fetch(
            f"""
            SELECT
                COALESCE(s.pattern, 'UNKNOWN') AS pattern,
                COALESCE(s.timeframe, 'UNKNOWN') AS timeframe,
                COUNT(*) AS count,
                COUNT(*) FILTER (WHERE s.status = 'WIN') AS wins
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            GROUP BY COALESCE(s.pattern, 'UNKNOWN'), COALESCE(s.timeframe, 'UNKNOWN')
            """,
            *sql_filter.params,
        )

    # Build regime breakdown
    regime_items: list[RegimeItem] = []
    for r in regime_rows:
        trades = r["trades"]
        wins = r["wins"]
        win_rate = (wins / trades * 100) if trades > 0 else 0.0
        gains = to_float(r["gains"])
        losses_abs = to_float(r["losses_abs"])

        # Calculate expectancy: win_rate_decimal * avg_win - loss_rate_decimal * avg_loss
        # avg_win = gains / wins, avg_loss = losses_abs / losses
        win_count = wins
        loss_count = trades - wins
        avg_win = (gains / win_count) if win_count > 0 else 0.0
        avg_loss = (losses_abs / loss_count) if loss_count > 0 else 0.0
        win_rate_decimal = win_rate / 100
        loss_rate_decimal = 1 - win_rate_decimal
        expectancy = win_rate_decimal * avg_win - loss_rate_decimal * avg_loss

        # Calculate profit factor: gains / losses_abs, handle division by zero
        profit_factor = (gains / losses_abs) if losses_abs > 0 else (math.inf if gains > 0 else 0.0)

        regime_items.append(
            RegimeItem(
                regime=r["regime"],
                trades=trades,
                wins=wins,
                win_rate=win_rate,
                expectancy=round(expectancy, 2),
                profit_factor=round(profit_factor, 2) if profit_factor != math.inf else float("inf"),
                total_return=round(to_float(r["total_return"]), 2),
            )
        )

    # Build heatmap
    heatmap_items: list[HeatmapItem] = []
    for r in heatmap_rows:
        count = r["count"]
        wins = r["wins"]
        heatmap_items.append(
            HeatmapItem(
                pattern=r["pattern"],
                timeframe=r["timeframe"],
                win_rate=round((wins / count * 100) if count > 0 else 50.0, 1),
                count=count,
            )
        )

    return BreakdownsResponse(
        regime_breakdown=regime_items,
        heatmap=heatmap_items,
    )
