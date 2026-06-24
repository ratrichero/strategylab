"""Shared analytics support endpoints."""

from typing import Optional

from fastapi import APIRouter, Query

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import (
    AnalyticsFilter,
    AnalyticsPreviewRequest,
    build_sql_filter,
)

router = APIRouter(tags=["Dashboard - Analytics"])


def _split_csv(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [x.strip() for x in str(value).replace(",", " ").split() if x.strip()]


def _query_filter(
    start_date: Optional[str],
    end_date: Optional[str],
    date_field: str,
    symbols: Optional[str],
    symbol_mode: str,
    timeframes: Optional[str],
    strategies: Optional[str],
    patterns: Optional[str],
    regimes: Optional[str],
    directions: Optional[str],
    engine_version: Optional[str],
    engine_mode: str,
    score_min: Optional[float],
    score_max: Optional[float],
    include_manual: bool,
) -> AnalyticsFilter:
    return AnalyticsFilter(
        start_date=start_date,
        end_date=end_date,
        date_field=date_field,
        symbols=symbols,
        symbol_mode=symbol_mode if symbol_mode in {"include", "exclude"} else "include",
        timeframes=_split_csv(timeframes),
        strategies=_split_csv(strategies),
        patterns=_split_csv(patterns),
        regimes=_split_csv(regimes),
        directions=_split_csv(directions),
        engine_version=engine_version or "all",
        engine_mode=engine_mode if engine_mode in {"only", "newest", "older"} else "only",
        score_min=score_min,
        score_max=score_max,
        include_manual=include_manual,
    )


@router.get("/api/filter-options")
async def filter_options(
    source: str = Query(default="closed"),
    start_date: Optional[str] = Query(default=None),
    end_date: Optional[str] = Query(default=None),
    date_field: str = Query(default="exit_time"),
    symbols: Optional[str] = Query(default=None),
    symbol_mode: str = Query(default="include"),
    timeframes: Optional[str] = Query(default=None),
    strategies: Optional[str] = Query(default=None),
    patterns: Optional[str] = Query(default=None),
    regimes: Optional[str] = Query(default=None),
    directions: Optional[str] = Query(default=None),
    engine_version: Optional[str] = Query(default="all"),
    engine_mode: str = Query(default="only"),
    score_min: Optional[float] = Query(default=None),
    score_max: Optional[float] = Query(default=None),
    include_manual: bool = Query(default=False),
):
    safe_source = source if source in {"closed", "open", "signals"} else "closed"
    filters = _query_filter(
        start_date,
        end_date,
        date_field,
        symbols,
        symbol_mode,
        timeframes,
        strategies,
        patterns,
        regimes,
        directions,
        engine_version,
        engine_mode,
        score_min,
        score_max,
        include_manual,
    )
    sql_filter = build_sql_filter(filters, source=safe_source, alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        option_row = await conn.fetchrow(
            f"""
            SELECT
              ARRAY_AGG(DISTINCT strategy_name) FILTER (WHERE strategy_name IS NOT NULL) AS strategies,
              ARRAY_AGG(DISTINCT pattern) FILTER (WHERE pattern IS NOT NULL) AS patterns,
              ARRAY_AGG(DISTINCT regime) FILTER (WHERE regime IS NOT NULL) AS regimes,
              ARRAY_AGG(DISTINCT symbol) FILTER (WHERE symbol IS NOT NULL) AS symbols,
              ARRAY_AGG(DISTINCT timeframe) FILTER (WHERE timeframe IS NOT NULL) AS timeframes,
              ARRAY_AGG(DISTINCT direction) FILTER (WHERE direction IS NOT NULL) AS directions
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            """,
            *sql_filter.params,
        )

        engine_rows = await conn.fetch(
            f"""
            SELECT DISTINCT engine_version
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
              AND engine_version IS NOT NULL
            ORDER BY engine_version DESC
            """,
            *sql_filter.params,
        )

    def clean(values):
        return sorted([v for v in (values or []) if v not in (None, "")])

    return {
        "source": sql_filter.source,
        "status_scope": sql_filter.status_scope,
        "date_field": sql_filter.date_field,
        "strategies": clean(option_row["strategies"] if option_row else []),
        "patterns": clean(option_row["patterns"] if option_row else []),
        "regimes": clean(option_row["regimes"] if option_row else []),
        "symbols": clean(option_row["symbols"] if option_row else []),
        "timeframes": clean(option_row["timeframes"] if option_row else []),
        "directions": clean(option_row["directions"] if option_row else []),
        "engine_versions": [str(r["engine_version"]) for r in engine_rows],
    }


@router.post("/api/analytics/preview")
async def analytics_preview(body: AnalyticsPreviewRequest):
    sql_filter = build_sql_filter(body, source=body.source, alias="s")
    pool = await get_async_pool()
    async with pool.acquire() as conn:
        total = await conn.fetchval(
            f"SELECT COUNT(*) FROM {sql_filter.table} s WHERE {sql_filter.where}",
            *sql_filter.params,
        )
    return {
        "total": total or 0,
        "source": sql_filter.source,
        "table": sql_filter.table,
        "status_scope": sql_filter.status_scope,
        "date_field": sql_filter.date_field,
    }
