"""Dashboard Overview API — KPI, win/loss, streaks, direction, duration."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter, profit_factor_for_json, to_float

router = APIRouter(tags=["Dashboard - Overview"])


class OverviewRequest(AnalyticsFilter):
    pass


class DirectionStats(BaseModel):
    total: int
    wins: int
    win_rate: float


class StreakStats(BaseModel):
    max_win: int
    max_loss: int


class OverviewResponse(BaseModel):
    total_trades: int
    trades_today: int
    wins_today: int
    losses_today: int
    win_rate_today: float
    wins: int
    losses: int
    win_rate: float
    profit_factor: float
    expectancy: float
    sharpe: float
    streaks: dict[str, StreakStats]
    direction: dict[str, DirectionStats]
    avg_duration_seconds: Optional[int]
    avg_duration_display: str


def _calc_streaks(statuses: list[str]) -> StreakStats:
    max_win = 0
    max_loss = 0
    cw = 0
    cl = 0
    for s in statuses:
        if s == "WIN":
            cw += 1
            cl = 0
            max_win = max(max_win, cw)
        else:
            cl += 1
            cw = 0
            max_loss = max(max_loss, cl)
    return StreakStats(max_win=max_win, max_loss=max_loss)


def _duration_display(seconds: float) -> str:
    mins = int(seconds / 60)
    if mins < 60:
        return f"{mins}m"
    hrs = mins // 60
    remain_mins = mins % 60
    if hrs < 24:
        return f"{hrs}h {remain_mins}m"
    days = hrs // 24
    remain_hrs = hrs % 24
    return f"{days}d {remain_hrs}h"


@router.post("/api/dashboard/overview")
async def dashboard_overview(body: OverviewRequest) -> OverviewResponse:
    sql_filter = build_sql_filter(body, source="signals", alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        # Fetch all closed trades for the filter (ordered for streaks)
        rows = await conn.fetch(
            f"""
            SELECT
                s.status,
                s.result_percent,
                s.direction,
                s.candle_time,
                s.exit_time,
                EXTRACT(EPOCH FROM (s.exit_time - s.candle_time)) AS duration_sec
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            ORDER BY s.exit_time ASC
            """,
            *sql_filter.params,
        )
        
        # Fetch current day trades separately (without date filter)
        # Build filter without date constraints for current day metrics
        now_utc = datetime.now(timezone.utc)
        vn_offset = timedelta(hours=7)
        now_vn = now_utc + vn_offset
        vn_today_start = now_vn.replace(hour=0, minute=0, second=0, microsecond=0) - vn_offset
        vn_today_end = vn_today_start + timedelta(days=1)
        
        # Build SQL filter without date constraints for current day
        # For current day metrics, we use all filters except date range
        # Create a modified body without date fields
        current_day_body = OverviewRequest(
            start_date=None,
            end_date=None,
            date_field=body.date_field,
            symbols=body.symbols,
            symbol_mode=body.symbol_mode,
            timeframes=body.timeframes,
            strategies=body.strategies,
            patterns=body.patterns,
            regimes=body.regimes,
            directions=body.directions,
            engine_version=body.engine_version,
            engine_mode=body.engine_mode,
            score_min=body.score_min,
            score_max=body.score_max,
            include_manual=body.include_manual,
        )
        current_day_filter = build_sql_filter(
            current_day_body,
            source="signals",
            alias="s"
        )
        
        today_rows = await conn.fetch(
            f"""
            SELECT
                s.status,
                s.result_percent,
                s.direction,
                s.candle_time,
                s.exit_time,
                EXTRACT(EPOCH FROM (s.exit_time - s.candle_time)) AS duration_sec
            FROM {current_day_filter.table} s
            WHERE {current_day_filter.where}
            AND s.exit_time >= $1 AND s.exit_time < $2
            ORDER BY s.exit_time ASC
            """,
            *current_day_filter.params,
            vn_today_start,
            vn_today_end,
        )

    total = len(rows)
    wins = sum(1 for r in rows if r["status"] == "WIN")
    losses = total - wins
    win_rate = (wins / total * 100) if total > 0 else 0.0

    # Profit factor
    result_percents = [to_float(r["result_percent"]) for r in rows]
    gains = sum(rp for rp in result_percents if rp > 0)
    losses_abs = abs(sum(rp for rp in result_percents if rp < 0))
    profit_factor = profit_factor_for_json(gains, losses_abs)

    # Expectancy
    win_rows = [rp for rp in result_percents if rp > 0]
    loss_rows = [rp for rp in result_percents if rp < 0]
    avg_win = sum(win_rows) / len(win_rows) if win_rows else 0.0
    avg_loss = abs(sum(loss_rows) / len(loss_rows)) if loss_rows else 0.0
    expectancy = (win_rate / 100) * avg_win - ((1 - win_rate / 100) * avg_loss)

    # Sharpe (trade-level)
    returns = result_percents
    if len(returns) >= 2:
        avg_ret = sum(returns) / len(returns)
        std_ret = math.sqrt(sum((x - avg_ret) ** 2 for x in returns) / len(returns))
        sharpe = (avg_ret / std_ret) if std_ret > 0.0001 else 0.0
    else:
        sharpe = 0.0

    # Streaks by exit_time and candle_time
    exit_statuses = [r["status"] for r in rows]
    candle_sorted = sorted(rows, key=lambda r: r["candle_time"] or r["exit_time"])
    candle_statuses = [r["status"] for r in candle_sorted]

    # Direction
    longs = [r for r in rows if r["direction"] == "LONG"]
    shorts = [r for r in rows if r["direction"] == "SHORT"]
    long_wins = sum(1 for r in longs if r["status"] == "WIN")
    short_wins = sum(1 for r in shorts if r["status"] == "WIN")

    # Duration
    durations = [to_float(r["duration_sec"]) for r in rows if to_float(r["duration_sec"]) > 0]
    avg_dur = sum(durations) / len(durations) if durations else None

    # trades_today: use separate query that excludes date filter
    trades_today = len(today_rows)
    wins_today = sum(1 for r in today_rows if r["status"] == "WIN")
    losses_today = sum(1 for r in today_rows if r["status"] == "LOSS")
    win_rate_today = (wins_today / trades_today * 100) if trades_today > 0 else 0.0

    return OverviewResponse(
        total_trades=total,
        trades_today=trades_today,
        wins_today=wins_today,
        losses_today=losses_today,
        win_rate_today=win_rate_today,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        profit_factor=profit_factor,
        expectancy=expectancy,
        sharpe=sharpe,
        streaks={
            "exit": _calc_streaks(exit_statuses),
            "candle": _calc_streaks(candle_statuses),
        },
        direction={
            "long": DirectionStats(total=len(longs), wins=long_wins, win_rate=(long_wins / len(longs) * 100) if longs else 0.0),
            "short": DirectionStats(total=len(shorts), wins=short_wins, win_rate=(short_wins / len(shorts) * 100) if shorts else 0.0),
        },
        avg_duration_seconds=int(avg_dur) if avg_dur else None,
        avg_duration_display=_duration_display(avg_dur) if avg_dur else "-",
    )
