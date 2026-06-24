"""Signals Trades API — paginated detail table for SignalsPage."""
from __future__ import annotations

from typing import Optional, Literal

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter

router = APIRouter(tags=["Signals - Trades"])


class SignalsTradesRequest(AnalyticsFilter):
    page: int = 1
    limit: int = 20
    search_symbols: str = ""
    sort_by: Literal["exit_time", "candle_time", "result_percent", "score"] = "exit_time"
    sort_order: Literal["desc", "asc"] = "desc"


class TradeItem(BaseModel):
    id: int
    symbol: str
    direction: str
    timeframe: str
    pattern: str
    score: float
    entry_price: float
    result_percent: float
    status: str
    regime: str
    strategy_name: str
    candle_time: str
    exit_time: str


class SignalsTradesResponse(BaseModel):
    data: list[TradeItem]
    total: int
    page: int
    limit: int
    pages: int


@router.post("/api/signals/trades")
async def signals_trades(body: SignalsTradesRequest) -> SignalsTradesResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    # Build search conditions for symbols
    search_conds = []
    search_params = []
    if body.search_symbols.strip():
        tokens = body.search_symbols.strip().split()
        for token in tokens:
            search_params.append(f"%{token}%")
            search_conds.append(f"s.symbol ILIKE ${len(search_params) + len(sql_filter.params)}")
    
    # Combine filter WHERE with search conditions
    where = sql_filter.where
    if search_conds:
        where = f"({where}) AND " + " OR ".join(search_conds)

    # Build ORDER BY clause
    sort_column_map = {
        "exit_time": "s.exit_time",
        "candle_time": "s.candle_time",
        "result_percent": "s.result_percent",
        "score": "s.score",
    }
    sort_col = sort_column_map.get(body.sort_by, "s.exit_time")
    order_clause = f"{sort_col} {body.sort_order.upper()}"

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        # Count total
        count_sql = f"SELECT COUNT(*) FROM {sql_filter.table} s WHERE {where}"
        total = await conn.fetchval(count_sql, *sql_filter.params, *search_params)

        # Fetch paginated rows
        offset = (body.page - 1) * body.limit
        all_params = [*sql_filter.params, *search_params, body.limit, offset]
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
                s.result_percent,
                s.status,
                s.regime,
                s.strategy_name,
                s.candle_time,
                s.exit_time
            FROM {sql_filter.table} s
            WHERE {where}
            ORDER BY {order_clause}
            LIMIT ${len(all_params) - 1} OFFSET ${len(all_params)}
            """,
            *all_params,
        )

    trades: list[TradeItem] = []
    for r in rows:
        trades.append(
            TradeItem(
                id=r["id"],
                symbol=r["symbol"],
                direction=r["direction"],
                timeframe=r["timeframe"],
                pattern=r["pattern"],
                score=r["score"] or 0,
                entry_price=r["entry_price"] or 0,
                result_percent=r["result_percent"] or 0,
                status=r["status"],
                regime=r["regime"],
                strategy_name=r["strategy_name"],
                candle_time=r["candle_time"].isoformat() if r["candle_time"] else "",
                exit_time=r["exit_time"].isoformat() if r["exit_time"] else "",
            )
        )

    pages = (total + body.limit - 1) // body.limit if total > 0 else 1

    return SignalsTradesResponse(
        data=trades,
        total=total,
        page=body.page,
        limit=body.limit,
        pages=pages,
    )
