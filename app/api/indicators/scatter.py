"""Indicators Scatter API — sample scatter data for IndicatorsPage."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, indicator_sql_expr, to_float

router = APIRouter(tags=["Indicators - Scatter"])


class ScatterRequest(AnalyticsFilter):
    x_indicator: Literal["rsi", "volume_ratio", "atr_ratio", "score"] = "rsi"
    y_indicator: Literal["rsi", "volume_ratio", "atr_ratio", "score"] = "volume_ratio"
    x_axis: Literal["rsi", "volume_ratio", "atr_ratio", "score"] | None = None
    y_axis: Literal["rsi", "volume_ratio", "atr_ratio", "score"] | None = None
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

    x_col = indicator_sql_expr(body.x_axis or body.x_indicator, alias="s")
    y_col = indicator_sql_expr(body.y_axis or body.y_indicator, alias="s")

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
        x_val = to_float(r["x_val"])
        y_val = to_float(r["y_val"])
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
