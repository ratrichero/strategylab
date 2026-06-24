"""Indicators Distribution API — distribution buckets for IndicatorsPage."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter

router = APIRouter(tags=["Indicators - Distribution"])


class DistributionRequest(AnalyticsFilter):
    indicator: Literal["rsi", "volume_ratio", "atr_ratio", "score"] = "rsi"


class DistributionBucketItem(BaseModel):
    range: str
    wins: int
    losses: int
    total: int
    winrate: float


class DistributionResponse(BaseModel):
    buckets: list[DistributionBucketItem]


@router.post("/api/indicators/distribution")
async def indicators_distribution(body: DistributionRequest) -> DistributionResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    # Map indicator to column name
    indicator_column_map = {
        "rsi": "s.rsi",
        "volume_ratio": "s.volume_ratio",
        "atr_ratio": "s.atr_ratio",
        "score": "s.score",
    }
    indicator_col = indicator_column_map.get(body.indicator, "s.rsi")

    # Define bucket ranges based on indicator
    if body.indicator == "rsi":
        ranges = [(0, 20), (20, 30), (30, 40), (40, 50), (50, 60), (60, 70), (70, 80), (80, 100)]
    elif body.indicator == "volume_ratio":
        ranges = [(0, 1), (1, 2), (2, 3), (3, 5), (5, 10), (10, float("inf"))]
    elif body.indicator == "atr_ratio":
        ranges = [(0, 0.01), (0.01, 0.02), (0.02, 0.03), (0.03, 0.05), (0.05, float("inf"))]
    else:  # score
        ranges = [(0, 5), (5, 6), (6, 7), (7, 8), (8, 9), (9, 10)]

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        buckets: list[DistributionBucketItem] = []
        for lo, hi in ranges:
            if hi == float("inf"):
                where_clause = f"{sql_filter.where} AND {indicator_col} >= ${len(sql_filter.params) + 1}"
                params = [*sql_filter.params, lo]
                label = f">={lo}"
            else:
                where_clause = f"{sql_filter.where} AND {indicator_col} >= ${len(sql_filter.params) + 1} AND {indicator_col} < ${len(sql_filter.params) + 2}"
                params = [*sql_filter.params, lo, hi]
                label = f"{lo}-{hi}"

            rows = await conn.fetch(
                f"""
                SELECT
                    COUNT(*) AS total,
                    COUNT(*) FILTER (WHERE s.status = 'WIN') AS wins
                FROM {sql_filter.table} s
                WHERE {where_clause}
                """,
                *params,
            )

            if rows:
                total = rows[0]["total"]
                wins = rows[0]["wins"]
                losses = total - wins
                winrate = (wins / total * 100) if total > 0 else 0.0
                if total > 0:
                    buckets.append(
                        DistributionBucketItem(
                            range=label,
                            wins=wins,
                            losses=losses,
                            total=total,
                            winrate=round(winrate, 1),
                        )
                    )

    return DistributionResponse(buckets=buckets)
