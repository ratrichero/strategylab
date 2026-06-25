"""Dashboard Recent Trades API — paginated closed trades with symbol search."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.db.async_pool import get_async_pool, serialize_records
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter

router = APIRouter(tags=["Dashboard - Recent Trades"])


class RecentTradesRequest(AnalyticsFilter):
    page: int = Field(default=1, ge=1)
    limit: int = Field(default=10, ge=1, le=100)
    search_symbols: Optional[str] = None


class RecentTradesResponse(BaseModel):
    data: list[dict]
    total: int
    page: int
    limit: int
    pages: int


@router.post("/api/dashboard/recent-trades")
async def dashboard_recent_trades(body: RecentTradesRequest) -> RecentTradesResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    # Symbol search: space-separated tokens, case-insensitive
    search_conds = []
    search_params: list = []
    if body.search_symbols:
        tokens = [t.strip().upper() for t in body.search_symbols.split() if t.strip()]
        if tokens:
            # Build OR condition for symbol ILIKE
            like_clauses = []
            for token in tokens:
                search_params.append(f"%{token}%")
                like_clauses.append(f"s.symbol ILIKE ${len(search_params) + len(sql_filter.params)}")
            search_conds.append("(" + " OR ".join(like_clauses) + ")")

    # Combine filter WHERE with search conditions
    where = sql_filter.where
    if search_conds:
        where = f"({where}) AND " + " AND ".join(search_conds)

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
                s.pattern,
                s.direction,
                s.timeframe,
                s.entry_price,
                s.exit_price,
                s.stop_loss,
                s.take_profit,
                s.result_percent,
                s.status,
                s.regime,
                s.score,
                s.candle_time,
                s.exit_time,
                s.indicators_snapshot,
                s.market_context,
                s.mae,
                s.mfe,
                s.strategy_name,
                s.engine_version
            FROM {sql_filter.table} s
            WHERE {where}
            ORDER BY s.exit_time DESC
            LIMIT ${len(all_params) - 1} OFFSET ${len(all_params)}
            """,
            *all_params,
        )

    pages = ((total or 0) + body.limit - 1) // body.limit
    return RecentTradesResponse(
        data=serialize_records(rows),
        total=total or 0,
        page=body.page,
        limit=body.limit,
        pages=pages,
    )