"""Signals Indicator Distribution API — indicator bucket analysis for SignalsPage."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, indicator_sql_expr, to_float

router = APIRouter(tags=["Signals - Indicator Distribution"])


class IndicatorDistributionRequest(AnalyticsFilter):
    indicator: Literal["rsi", "volume_ratio", "atr_percentile"] = "rsi"


class IndicatorBucketItem(BaseModel):
    bucket: str
    trades: int
    win_rate: float
    avg_return: float


class IndicatorDistributionResponse(BaseModel):
    buckets: list[IndicatorBucketItem]


@router.post("/api/signals/indicator-distribution")
async def signals_indicator_distribution(body: IndicatorDistributionRequest) -> IndicatorDistributionResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    indicator_col = indicator_sql_expr(body.indicator, alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        # Create buckets based on indicator value
        if body.indicator == "rsi":
            bucket_expr = f"""
                CASE 
                    WHEN {indicator_col} IS NULL THEN 'unknown'
                    WHEN {indicator_col} < 30 THEN '0-30'
                    WHEN {indicator_col} < 50 THEN '30-50'
                    WHEN {indicator_col} < 70 THEN '50-70'
                    ELSE '70-100'
                END
            """
        elif body.indicator == "volume_ratio":
            bucket_expr = f"""
                CASE 
                    WHEN {indicator_col} IS NULL THEN 'unknown'
                    WHEN {indicator_col} < 0.5 THEN '0-0.5'
                    WHEN {indicator_col} < 1.0 THEN '0.5-1.0'
                    WHEN {indicator_col} < 1.5 THEN '1.0-1.5'
                    WHEN {indicator_col} < 2.0 THEN '1.5-2.0'
                    ELSE '2.0+'
                END
            """
        else:  # atr_percentile
            bucket_expr = f"""
                CASE 
                    WHEN {indicator_col} IS NULL THEN 'unknown'
                    WHEN {indicator_col} < 0.5 THEN '0-0.5'
                    WHEN {indicator_col} < 1.0 THEN '0.5-1.0'
                    WHEN {indicator_col} < 1.5 THEN '1.0-1.5'
                    WHEN {indicator_col} < 2.0 THEN '1.5-2.0'
                    ELSE '2.0+'
                END
            """

        rows = await conn.fetch(
            f"""
            SELECT
                {bucket_expr} AS bucket,
                COUNT(*) AS trades,
                COUNT(*) FILTER (WHERE s.status = 'WIN') AS wins,
                AVG(s.result_percent) AS avg_return
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            GROUP BY {bucket_expr}
            ORDER BY {bucket_expr}
            """,
            *sql_filter.params,
        )

    buckets: list[IndicatorBucketItem] = []
    for r in rows:
        trades = r["trades"]
        wins = r["wins"]
        win_rate = (wins / trades * 100) if trades > 0 else 0.0
        avg_return = to_float(r["avg_return"])

        buckets.append(
            IndicatorBucketItem(
                bucket=r["bucket"],
                trades=trades,
                win_rate=round(win_rate, 1),
                avg_return=round(avg_return, 2),
            )
        )

    return IndicatorDistributionResponse(buckets=buckets)
