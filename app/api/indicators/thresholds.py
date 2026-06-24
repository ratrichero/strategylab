"""Indicators Thresholds API — threshold optimizer for IndicatorsPage."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, indicator_sql_expr

router = APIRouter(tags=["Indicators - Thresholds"])


class ThresholdsRequest(AnalyticsFilter):
    indicator: Literal["rsi", "volume_ratio", "atr_ratio", "score"] = "rsi"


class ThresholdItem(BaseModel):
    threshold: float
    trades: int
    winrate: float


class ThresholdsResponse(BaseModel):
    thresholds: list[ThresholdItem]


@router.post("/api/indicators/thresholds")
async def indicators_thresholds(body: ThresholdsRequest) -> ThresholdsResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    indicator_col = indicator_sql_expr(body.indicator, alias="s")

    # Define threshold steps based on indicator
    if body.indicator == "rsi":
        steps = [20, 30, 40, 50, 60, 70, 80]
    elif body.indicator == "volume_ratio":
        steps = [0.5, 1, 1.5, 2, 3, 5]
    elif body.indicator == "score":
        steps = [5, 6, 7, 8, 9]
    else:  # atr_ratio
        steps = [0.005, 0.01, 0.015, 0.02, 0.03]

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        thresholds: list[ThresholdItem] = []
        for threshold in steps:
            rows = await conn.fetch(
                f"""
                SELECT
                    COUNT(*) AS trades,
                    COUNT(*) FILTER (WHERE s.status = 'WIN') AS wins
                FROM {sql_filter.table} s
                WHERE {sql_filter.where} AND {indicator_col} >= ${len(sql_filter.params) + 1}
                """,
                *sql_filter.params,
                threshold,
            )

            if rows:
                trades = rows[0]["trades"]
                wins = rows[0]["wins"]
                winrate = (wins / trades * 100) if trades > 0 else 0.0
                if trades > 0:
                    thresholds.append(
                        ThresholdItem(
                            threshold=float(threshold),
                            trades=trades,
                            winrate=round(winrate, 1),
                        )
                    )

    return ThresholdsResponse(thresholds=thresholds)
