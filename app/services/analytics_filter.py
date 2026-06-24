"""Shared analytics filter contract and SQL builder.

This module is intentionally small and dependency-light so dashboard,
signals, indicators, and manual-behavior endpoints can share identical
filter semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Optional
import re

from pydantic import BaseModel, Field


DATE_FIELDS = {"exit_time", "created_at", "candle_time"}
SOURCE_TABLES = {
    "closed": "mv_signal_performance",
    "open": "signals",
    "signals": "signals",
}


class AnalyticsFilter(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    date_field: str = "exit_time"
    symbols: Optional[str] = None
    symbol_mode: Literal["include", "exclude"] = "include"
    timeframes: list[str] = Field(default_factory=list)
    strategies: list[str] = Field(default_factory=list)
    patterns: list[str] = Field(default_factory=list)
    regimes: list[str] = Field(default_factory=list)
    directions: list[str] = Field(default_factory=list)
    engine_version: Optional[str] = "all"
    engine_mode: Literal["only", "newest", "older"] = "only"
    score_min: Optional[float] = None
    score_max: Optional[float] = None
    include_manual: bool = False


class AnalyticsPreviewRequest(AnalyticsFilter):
    source: Literal["closed", "open", "signals"] = "closed"


@dataclass(frozen=True)
class SQLFilter:
    where: str
    params: list[Any]
    source: str
    table: str
    status_scope: str
    date_field: str


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse datetime string to naive UTC datetime."""
    if not value:
        return None
    text = str(value).strip()
    text = re.sub(r"\.\d+", "", text)
    text = text.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_vn_date_range(start_date: Optional[str], end_date: Optional[str]) -> tuple[Optional[datetime], Optional[datetime]]:
    """Parse UI date range where plain dates are Vietnam dates.

    Plain end date is inclusive in the UI and becomes an exclusive UTC
    boundary at the start of the next Vietnam day.
    """
    start_dt = None
    end_dt = None

    if start_date:
        start_s = str(start_date).strip()
        start_dt = parse_dt(start_s if "T" in start_s else f"{start_s}T00:00:00+07:00")

    if end_date:
        end_s = str(end_date).strip()
        if "T" in end_s:
            end_dt = parse_dt(end_s)
        else:
            base = parse_dt(f"{end_s}T00:00:00+07:00")
            end_dt = base + timedelta(days=1) if base else None

    return start_dt, end_dt


def normalize_symbols(symbols: Optional[str]) -> list[str]:
    if not symbols:
        return []
    out = []
    for item in str(symbols).replace(",", " ").split():
        symbol = item.strip().upper()
        if not symbol:
            continue
        out.append(symbol if symbol.endswith("USDT") else f"{symbol}USDT")
    return sorted(set(out))


def clean_list(values: Optional[Iterable[Any]]) -> list[str]:
    if not values:
        return []
    out = []
    for value in values:
        text = str(value).strip()
        if text:
            out.append(text)
    return sorted(set(out))


def expand_regimes(values: Optional[Iterable[Any]]) -> list[str]:
    regimes = clean_list(values)
    expanded = set(regimes)
    if "SIDEWAYS" in expanded:
        expanded.add("RANGING")
    return sorted(expanded)


def _column(alias: str, name: str) -> str:
    return f"{alias}.{name}" if alias else name


def _add_param(params: list[Any], value: Any) -> str:
    params.append(value)
    return f"${len(params)}"


def _status_scope(filters: AnalyticsFilter, source: str) -> tuple[str, list[str]]:
    if source == "open":
        return "OPEN", ["OPEN"]
    if filters.include_manual:
        return "WIN_LOSS_MANUAL", ["WIN", "LOSS", "MANUAL"]
    return "WIN_LOSS", ["WIN", "LOSS"]


def build_sql_filter(
    filters: AnalyticsFilter,
    *,
    source: Literal["closed", "open", "signals"] = "closed",
    alias: str = "s",
) -> SQLFilter:
    """Build parameterized asyncpg WHERE SQL for analytics filters."""
    table = SOURCE_TABLES[source]
    date_field = filters.date_field if filters.date_field in DATE_FIELDS else "exit_time"
    if source == "open" and date_field == "exit_time":
        date_field = "created_at"

    params: list[Any] = []
    conds = ["1=1"]

    status_scope, statuses = _status_scope(filters, source)
    conds.append(f"{_column(alias, 'status')} = ANY({_add_param(params, statuses)}::text[])")

    start_dt, end_dt = parse_vn_date_range(filters.start_date, filters.end_date)
    if start_dt:
        conds.append(f"{_column(alias, date_field)} >= {_add_param(params, start_dt)}")
    if end_dt:
        conds.append(f"{_column(alias, date_field)} < {_add_param(params, end_dt)}")

    array_filters = [
        ("timeframe", clean_list(filters.timeframes)),
        ("strategy_name", clean_list(filters.strategies)),
        ("pattern", clean_list(filters.patterns)),
        ("regime", expand_regimes(filters.regimes)),
        ("direction", clean_list(filters.directions)),
    ]
    for col, values in array_filters:
        if values:
            conds.append(f"{_column(alias, col)} = ANY({_add_param(params, values)}::text[])")

    symbols = normalize_symbols(filters.symbols)
    if symbols:
        op = "<>" if filters.symbol_mode == "exclude" else "="
        conds.append(f"{_column(alias, 'symbol')} {op} ALL({_add_param(params, symbols)}::text[])" if filters.symbol_mode == "exclude" else f"{_column(alias, 'symbol')} = ANY({_add_param(params, symbols)}::text[])")

    engine_version = str(filters.engine_version or "all").strip()
    if engine_version and engine_version != "all":
        try:
            engine_value = float(engine_version)
            if filters.engine_mode == "newest":
                conds.append(f"{_column(alias, 'engine_version')} >= {_add_param(params, engine_value)}")
            elif filters.engine_mode == "older":
                conds.append(f"{_column(alias, 'engine_version')} <= {_add_param(params, engine_value)}")
            else:
                conds.append(f"{_column(alias, 'engine_version')} = {_add_param(params, engine_value)}")
        except ValueError:
            conds.append(f"{_column(alias, 'engine_version')}::text = {_add_param(params, engine_version)}")

    if filters.score_min is not None and filters.score_min > 0:
        conds.append(f"{_column(alias, 'score')} >= {_add_param(params, float(filters.score_min))}")
    if filters.score_max is not None and filters.score_max < 10:
        conds.append(f"{_column(alias, 'score')} <= {_add_param(params, float(filters.score_max))}")

    return SQLFilter(
        where=" AND ".join(conds),
        params=params,
        source=source,
        table=table,
        status_scope=status_scope,
        date_field=date_field,
    )
