"""Indicators Scatter API — sample scatter data for IndicatorsPage."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter

router = APIRouter(tags=["Indicators - Scatter"])


class ScatterRequest(AnalyticsFilter):
    x_indicator: Literal["rsi", "volume_ratio", "atr_ratio", "score"] = "rsi"
    y_indicator: Literal["rsi", "volume_ratio", "atr_ratio", "score"] = "volume_ratio"
    limit: int = 300


class ScatterItem(BaseModel):
    x: float
    y: float
    label: int  # 1 for WIN, 0 for LOSS
    symbol: str


class ScatterResponse(BaseModel):
    data: list[ScatterItem]


@router.post("/api/indicators/scatter")
async def indicators_scatter(body: ScatterRequest) -> ScatterResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    # Map indicators to column names
    indicator_column_map = {
        "rsi": "s.rsi",
        "volume_ratio": "s.volume_ratio",
        "atr_ratio": "s.atr_ratio",
        "score": "s.score",
    }
    x_col = indicator_column_map.get(body.x_indicator, "s.rsi")
    y_col = indicator_column_map.get(body.y_indicator, "s.volume_ratio")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                {x_col} AS x_val,
                {y_col} AS y_val,
                s.status,
                s.symbol
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            ORDER BY RANDOM()
            LIMIT ${len(sql_filter.params) + 1}
            """,
            *sql_filter.params,
            body.limit,
        )

    data: list[ScatterItem] = []
    for r in rows:
        x_val = r["x_val"] or 0
        y_val = r["y_val"] or 0
        # Only include if at least one value is non-zero
        if x_val > 0 or y_val > 0:
            data.append(
                ScatterItem(
                    x=float(x_val),
                    y=float(y_val),
                    label=1 if r["status"] == "WIN" else 0,
                    symbol=r["symbol"],
                )
            )

    return ScatterResponse(data=data)
