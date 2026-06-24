"""Manual Behavior Overview API — KPI metrics for ManualBehaviorPage."""
from __future__ import annotations

import math
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, to_float

router = APIRouter(tags=["Manual Behavior - Overview"])

MANUAL_BEHAVIOR_STATUSES = ["WIN", "LOSS", "MANUAL", "KILLED", "MANUAL_CLOSE"]


class ManualBehaviorOverviewRequest(AnalyticsFilter):
    pass


class ManualBehaviorOverviewResponse(BaseModel):
    total: int
    manual_count: int
    wins: int
    win_rate: float
    manual_wins: int
    manual_win_rate: float
    avg_std_pnl: float
    avg_manual_pnl: float
    planned_total: float
    actual_total: float
    impact: float


@router.post("/api/manual-behavior/overview")
async def manual_behavior_overview(body: ManualBehaviorOverviewRequest) -> ManualBehaviorOverviewResponse:
    # Manual-behavior analysis intentionally includes all closed/manual outcomes.
    sql_filter = build_sql_filter(body, source="closed", alias="s")
    sql_filter.params[0] = MANUAL_BEHAVIOR_STATUSES

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                s.status,
                s.direction,
                s.entry_price,
                s.exit_price,
                s.result_percent
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            """,
            *sql_filter.params,
        )

    total = len(rows)
    if total == 0:
        return ManualBehaviorOverviewResponse(
            total=0,
            manual_count=0,
            wins=0,
            win_rate=0.0,
            manual_wins=0,
            manual_win_rate=0.0,
            avg_std_pnl=0.0,
            avg_manual_pnl=0.0,
            planned_total=0.0,
            actual_total=0.0,
            impact=0.0,
        )

    # Derive outcomes for non-standard statuses
    enriched = []
    for r in rows:
        is_standard = r["status"] in ("WIN", "LOSS")
        entry = to_float(r["entry_price"])
        exit = to_float(r["exit_price"])
        direction = r["direction"] or "LONG"
        
        if is_standard:
            derived_status = r["status"]
            derived_pnl = to_float(r["result_percent"])
        else:
            # Derive WIN/LOSS from entry/exit/direction
            if entry and exit:
                if direction == "LONG":
                    derived_pnl = ((exit - entry) / entry) * 100
                else:
                    derived_pnl = ((entry - exit) / entry) * 100
                derived_status = "WIN" if derived_pnl >= 0 else "LOSS"
            else:
                derived_status = r["status"]
                derived_pnl = to_float(r["result_percent"])
        
        enriched.append({
            "is_manual": not is_standard,
            "derived_status": derived_status,
            "derived_pnl": derived_pnl,
            "actual_pnl": to_float(r["result_percent"]),
        })

    # Calculate KPIs
    manual_signals = [s for s in enriched if s["is_manual"]]
    std_signals = [s for s in enriched if not s["is_manual"]]
    
    manual_count = len(manual_signals)
    wins = sum(1 for s in enriched if s["derived_status"] == "WIN")
    win_rate = (wins / total * 100) if total > 0 else 0.0
    
    manual_wins = sum(1 for s in manual_signals if s["derived_status"] == "WIN")
    manual_win_rate = (manual_wins / manual_count * 100) if manual_count > 0 else 0.0
    
    avg_std_pnl = (sum(s["actual_pnl"] for s in std_signals) / len(std_signals)) if std_signals else 0.0
    avg_manual_pnl = (sum(s["actual_pnl"] for s in manual_signals) / len(manual_signals)) if manual_signals else 0.0
    
    planned_total = sum(abs(s["derived_pnl"]) for s in manual_signals)
    actual_total = sum(s["actual_pnl"] for s in manual_signals)
    
    impact = avg_manual_pnl - avg_std_pnl

    return ManualBehaviorOverviewResponse(
        total=total,
        manual_count=manual_count,
        wins=wins,
        win_rate=round(win_rate, 1),
        manual_wins=manual_wins,
        manual_win_rate=round(manual_win_rate, 1),
        avg_std_pnl=round(avg_std_pnl, 2),
        avg_manual_pnl=round(avg_manual_pnl, 2),
        planned_total=round(planned_total, 2),
        actual_total=round(actual_total, 2),
        impact=round(impact, 2),
    )
