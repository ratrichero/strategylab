"""Manual Behavior Comparison API — comparison metrics for ManualBehaviorPage."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter

router = APIRouter(tags=["Manual Behavior - Comparison"])

MANUAL_BEHAVIOR_STATUSES = ["WIN", "LOSS", "MANUAL", "KILLED", "MANUAL_CLOSE"]


class ManualBehaviorComparisonRequest(AnalyticsFilter):
    pass


class ComparisonGroup(BaseModel):
    group_type: Literal["standard", "manual"]
    total: int
    wins: int
    win_rate: float
    avg_pnl: float
    profit_factor: float


class ManualBehaviorComparisonResponse(BaseModel):
    standard: ComparisonGroup
    manual: ComparisonGroup


@router.post("/api/manual-behavior/comparison")
async def manual_behavior_comparison(body: ManualBehaviorComparisonRequest) -> ManualBehaviorComparisonResponse:
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

    # Derive outcomes for non-standard statuses
    enriched = []
    for r in rows:
        is_standard = r["status"] in ("WIN", "LOSS")
        entry = r["entry_price"] or 0
        exit = r["exit_price"] or 0
        direction = r["direction"] or "LONG"
        
        if is_standard:
            derived_status = r["status"]
            derived_pnl = r["result_percent"] or 0
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
                derived_pnl = r["result_percent"] or 0
        
        enriched.append({
            "is_manual": not is_standard,
            "derived_status": derived_status,
            "actual_pnl": r["result_percent"] or 0,
        })

    # Split into standard and manual groups
    manual_signals = [s for s in enriched if s["is_manual"]]
    std_signals = [s for s in enriched if not s["is_manual"]]

    def calculate_group(signals):
        total = len(signals)
        if total == 0:
            return ComparisonGroup(
                group_type="standard" if signals is std_signals else "manual",
                total=0,
                wins=0,
                win_rate=0.0,
                avg_pnl=0.0,
                profit_factor=0.0,
            )
        
        wins = sum(1 for s in signals if s["derived_status"] == "WIN")
        win_rate = (wins / total * 100) if total > 0 else 0.0
        
        avg_pnl = sum(s["actual_pnl"] for s in signals) / total
        
        gains = sum(s["actual_pnl"] for s in signals if s["actual_pnl"] > 0)
        losses_abs = abs(sum(s["actual_pnl"] for s in signals if s["actual_pnl"] < 0))
        profit_factor = (gains / losses_abs) if losses_abs > 0 else (float("inf") if gains > 0 else 0.0)
        
        return ComparisonGroup(
            group_type="standard" if signals is std_signals else "manual",
            total=total,
            wins=wins,
            win_rate=round(win_rate, 1),
            avg_pnl=round(avg_pnl, 2),
            profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else float("inf"),
        )

    standard = calculate_group(std_signals)
    manual = calculate_group(manual_signals)

    return ManualBehaviorComparisonResponse(
        standard=standard,
        manual=manual,
    )
