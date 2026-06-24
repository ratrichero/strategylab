"""Signals Heatmaps API — pattern/timeframe heatmap for SignalsPage."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter

router = APIRouter(tags=["Signals - Heatmaps"])


class HeatmapsRequest(AnalyticsFilter):
    pass


class HeatmapItem(BaseModel):
    x: str
    y: str
    value: float
    count: int


class HeatmapsResponse(BaseModel):
    pattern_timeframe: list[HeatmapItem]


@router.post("/api/signals/heatmaps")
async def signals_heatmaps(body: HeatmapsRequest) -> HeatmapsResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        # Pattern x Timeframe heatmap
        rows = await conn.fetch(
            f"""
            SELECT
                COALESCE(s.pattern, 'unknown') AS pattern,
                COALESCE(s.timeframe, 'unknown') AS timeframe,
                COUNT(*) AS count,
                COUNT(*) FILTER (WHERE s.status = 'WIN') AS wins
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            GROUP BY COALESCE(s.pattern, 'unknown'), COALESCE(s.timeframe, 'unknown')
            """,
            *sql_filter.params,
        )

    heatmap_items: list[HeatmapItem] = []
    timeframes = ["15m", "1h", "4h", "All"]
    
    # Build heatmap with all timeframes for each pattern
    pattern_data = {}
    for r in rows:
        pattern = r["pattern"]
        tf = r["timeframe"]
        count = r["count"]
        wins = r["wins"]
        win_rate = (wins / count * 100) if count > 0 else 50.0
        
        if pattern not in pattern_data:
            pattern_data[pattern] = {}
        pattern_data[pattern][tf] = {"count": count, "win_rate": win_rate}
    
    # Add "All" column for each pattern
    for pattern, tf_data in pattern_data.items():
        total_count = sum(d["count"] for d in tf_data.values())
        total_wins = sum(d["count"] * d["win_rate"] / 100 for d in tf_data.values())
        all_win_rate = (total_wins / total_count * 100) if total_count > 0 else 50.0
        pattern_data[pattern]["All"] = {"count": total_count, "win_rate": all_win_rate}
    
    # Generate heatmap items
    for pattern, tf_data in pattern_data.items():
        for tf in timeframes:
            if tf in tf_data:
                heatmap_items.append(
                    HeatmapItem(
                        x=tf,
                        y=pattern,
                        value=round(tf_data[tf]["win_rate"], 1),
                        count=tf_data[tf]["count"],
                    )
                )

    return HeatmapsResponse(pattern_timeframe=heatmap_items)
