"""Signals Group Performance API — grouped metrics for SignalsPage."""
from __future__ import annotations

import math
from typing import Optional, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter

router = APIRouter(tags=["Signals - Group Performance"])


class GroupPerformanceRequest(AnalyticsFilter):
    group_by: Literal["pattern", "direction", "regime", "timeframe", "strategy_name", "score", "engine_version"] = "pattern"


class GroupPerformanceItem(BaseModel):
    name: str
    trades: int
    wins: int
    losses: int
    winrate: float
    profit_factor: float
    avg_return: float


class GroupPerformanceResponse(BaseModel):
    groups: list[GroupPerformanceItem]


@router.post("/api/signals/group-performance")
async def signals_group_performance(body: GroupPerformanceRequest) -> GroupPerformanceResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    # Map group_by to column name
    group_column_map = {
        "pattern": "s.pattern",
        "direction": "s.direction",
        "regime": "s.regime",
        "timeframe": "s.timeframe",
        "strategy_name": "s.strategy_name",
        "engine_version": "s.engine_version",
        "score": "s.score",
    }
    group_col = group_column_map.get(body.group_by, "s.pattern")

    # For score grouping, bucket into ranges
    if body.group_by == "score":
        group_expr = f"CASE WHEN s.score IS NULL THEN 'unknown' ELSE FLOOR(s.score)::text END"
        order_expr = "FLOOR(s.score)"
    else:
        group_expr = f"COALESCE({group_col}, 'unknown')"
        order_expr = group_col

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                {group_expr} AS name,
                COUNT(*) AS trades,
                COUNT(*) FILTER (WHERE s.status = 'WIN') AS wins,
                SUM(s.result_percent) AS total_return,
                SUM(CASE WHEN s.result_percent > 0 THEN s.result_percent ELSE 0 END) AS gains,
                SUM(CASE WHEN s.result_percent < 0 THEN ABS(s.result_percent) ELSE 0 END) AS losses_abs
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            GROUP BY {group_expr}
            ORDER BY {order_expr}
            """,
            *sql_filter.params,
        )

    groups: list[GroupPerformanceItem] = []
    for r in rows:
        trades = r["trades"]
        wins = r["wins"]
        losses = trades - wins
        winrate = (wins / trades * 100) if trades > 0 else 0.0
        gains = r["gains"] or 0
        losses_abs = r["losses_abs"] or 0
        profit_factor = (gains / losses_abs) if losses_abs > 0 else (math.inf if gains > 0 else 0.0)
        avg_return = (r["total_return"] or 0) / trades if trades > 0 else 0.0

        groups.append(
            GroupPerformanceItem(
                name=r["name"],
                trades=trades,
                wins=wins,
                losses=losses,
                winrate=round(winrate, 1),
                profit_factor=round(profit_factor, 2) if profit_factor != math.inf else float("inf"),
                avg_return=round(avg_return, 2),
            )
        )

    return GroupPerformanceResponse(groups=groups)
