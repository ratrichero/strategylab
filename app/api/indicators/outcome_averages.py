"""Indicators Outcome Averages API — outcome averages by indicator for IndicatorsPage."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, indicator_sql_expr, to_float

router = APIRouter(tags=["Indicators - Outcome Averages"])


class OutcomeAveragesRequest(AnalyticsFilter):
    pass


class OutcomeAverageItem(BaseModel):
    indicator: str
    win_avg: float
    loss_avg: float


class OutcomeAveragesResponse(BaseModel):
    averages: list[OutcomeAverageItem]


@router.post("/api/indicators/outcome-averages")
async def indicators_outcome_averages(body: OutcomeAveragesRequest) -> OutcomeAveragesResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        # Calculate average indicator values for wins and losses
        rows = await conn.fetch(
            f"""
            SELECT
                s.status,
                AVG({indicator_sql_expr("rsi", alias="s")}) AS avg_rsi,
                AVG({indicator_sql_expr("volume_ratio", alias="s")}) AS avg_vol_ratio,
                AVG({indicator_sql_expr("atr_ratio", alias="s")}) AS avg_atr_ratio,
                AVG(s.score) AS avg_score
            FROM {sql_filter.table} s
            WHERE {sql_filter.where} AND s.status IN ('WIN', 'LOSS')
            GROUP BY s.status
            """,
            *sql_filter.params,
        )

    win_avg = {}
    loss_avg = {}
    
    for r in rows:
        if r["status"] == "WIN":
            win_avg = {
                "rsi": to_float(r["avg_rsi"]),
                "volume_ratio": to_float(r["avg_vol_ratio"]),
                "atr_ratio": to_float(r["avg_atr_ratio"]),
                "score": to_float(r["avg_score"]),
            }
        elif r["status"] == "LOSS":
            loss_avg = {
                "rsi": to_float(r["avg_rsi"]),
                "volume_ratio": to_float(r["avg_vol_ratio"]),
                "atr_ratio": to_float(r["avg_atr_ratio"]),
                "score": to_float(r["avg_score"]),
            }

    labels = {"rsi": "RSI", "volume_ratio": "Vol Ratio", "atr_ratio": "ATR Ratio", "score": "Score"}
    averages: list[OutcomeAverageItem] = []
    
    for ind_key, label in labels.items():
        win_val = win_avg.get(ind_key, 0)
        loss_val = loss_avg.get(ind_key, 0)
        if win_val > 0 or loss_val > 0:
            averages.append(
                OutcomeAverageItem(
                    indicator=label,
                    win_avg=round(win_val, 2),
                    loss_avg=round(loss_val, 2),
                )
            )

    return OutcomeAveragesResponse(averages=averages)
