"""Manual Behavior Trades API — paginated trades for ManualBehaviorPage."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter

router = APIRouter(tags=["Manual Behavior - Trades"])

MANUAL_BEHAVIOR_STATUSES = ["WIN", "LOSS", "MANUAL", "KILLED", "MANUAL_CLOSE"]


class ManualBehaviorTradesRequest(AnalyticsFilter):
    page: int = 1
    limit: int = 20
    search_symbols: str = ""
    sort_by: Literal["exit_time", "candle_time", "result_percent", "score"] = "exit_time"
    sort_order: Literal["desc", "asc"] = "desc"


class ManualTradeItem(BaseModel):
    id: int
    symbol: str
    direction: str
    timeframe: str
    pattern: str
    score: float
    entry_price: float
    exit_price: float
    result_percent: float
    status: str
    derived_status: str
    derived_pnl: float
    is_manual: bool
    regime: str
    strategy_name: str
    candle_time: str
    exit_time: str


class ManualBehaviorTradesResponse(BaseModel):
    data: list[ManualTradeItem]
    total: int
    page: int
    limit: int
    pages: int


@router.post("/api/manual-behavior/trades")
async def manual_behavior_trades(body: ManualBehaviorTradesRequest) -> ManualBehaviorTradesResponse:
    # Manual-behavior analysis intentionally includes all closed/manual outcomes.
    sql_filter = build_sql_filter(body, source="closed", alias="s")
    sql_filter.params[0] = MANUAL_BEHAVIOR_STATUSES

    # Sort column mapping
    sort_column_map = {
        "exit_time": "s.exit_time",
        "candle_time": "s.candle_time",
        "result_percent": "s.result_percent",
        "score": "s.score",
    }
    sort_col = sort_column_map.get(body.sort_by, "s.exit_time")
    sort_order = "DESC" if body.sort_order == "desc" else "ASC"

    # Search symbols filter
    search_where = ""
    search_params = []
    if body.search_symbols:
        symbols = [s.strip().upper() for s in body.search_symbols.split(",") if s.strip()]
        if symbols:
            placeholders = ",".join(f"${len(sql_filter.params) + i + 1}" for i in range(len(symbols)))
            search_where = f" AND UPPER(s.symbol) IN ({placeholders})"
            search_params = symbols

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        # Get total count
        count_rows = await conn.fetch(
            f"""
            SELECT COUNT(*) AS total
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}{search_where}
            """,
            *sql_filter.params,
            *search_params,
        )
        total = count_rows[0]["total"] if count_rows else 0

        # Get paginated data
        offset = (body.page - 1) * body.limit
        rows = await conn.fetch(
            f"""
            SELECT
                s.id,
                s.symbol,
                s.direction,
                s.timeframe,
                s.pattern,
                s.score,
                s.entry_price,
                s.exit_price,
                s.result_percent,
                s.status,
                s.regime,
                s.strategy_name,
                s.candle_time,
                s.exit_time
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}{search_where}
            ORDER BY {sort_col} {sort_order}
            LIMIT ${len(sql_filter.params) + len(search_params) + 1} OFFSET ${len(sql_filter.params) + len(search_params) + 2}
            """,
            *sql_filter.params,
            *search_params,
            body.limit,
            offset,
        )

    # Enrich with derived status/pnl
    data = []
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
        
        data.append(ManualTradeItem(
            id=r["id"],
            symbol=r["symbol"],
            direction=r["direction"],
            timeframe=r["timeframe"],
            pattern=r["pattern"],
            score=r["score"] or 0,
            entry_price=r["entry_price"] or 0,
            exit_price=r["exit_price"] or 0,
            result_percent=r["result_percent"] or 0,
            status=r["status"],
            derived_status=derived_status,
            derived_pnl=derived_pnl,
            is_manual=not is_standard,
            regime=r["regime"] or "N/A",
            strategy_name=r["strategy_name"] or "",
            candle_time=r["candle_time"] or "",
            exit_time=r["exit_time"] or "",
        ))

    pages = (total + body.limit - 1) // body.limit if total > 0 else 0

    return ManualBehaviorTradesResponse(
        data=data,
        total=total,
        page=body.page,
        limit=body.limit,
        pages=pages,
    )
