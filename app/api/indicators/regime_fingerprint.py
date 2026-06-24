"""Indicators Regime Fingerprint API — regime fingerprint for IndicatorsPage."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.db.async_pool import get_async_pool
from app.services.analytics_filter import AnalyticsFilter, build_sql_filter

router = APIRouter(tags=["Indicators - Regime Fingerprint"])


class RegimeFingerprintRequest(AnalyticsFilter):
    pass


class RegimeFingerprintItem(BaseModel):
    regime: str
    trades: int
    winrate: float
    rsi: float
    volume_ratio: float
    atr_ratio: float
    score: float


class RegimeFingerprintResponse(BaseModel):
    regimes: list[RegimeFingerprintItem]


@router.post("/api/indicators/regime-fingerprint")
async def indicators_regime_fingerprint(body: RegimeFingerprintRequest) -> RegimeFingerprintResponse:
    sql_filter = build_sql_filter(body, source="closed", alias="s")

    pool = await get_async_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"""
            SELECT
                COALESCE(s.regime, 'UNKNOWN') AS regime,
                COUNT(*) AS trades,
                COUNT(*) FILTER (WHERE s.status = 'WIN') AS wins,
                AVG(s.rsi) AS avg_rsi,
                AVG(s.volume_ratio) AS avg_vol_ratio,
                AVG(s.atr_ratio) AS avg_atr_ratio,
                AVG(s.score) AS avg_score
            FROM {sql_filter.table} s
            WHERE {sql_filter.where}
            GROUP BY COALESCE(s.regime, 'UNKNOWN')
            ORDER BY trades DESC
            """,
            *sql_filter.params,
        )

    regimes: list[RegimeFingerprintItem] = []
    for r in rows:
        trades = r["trades"]
        wins = r["wins"]
        winrate = (wins / trades * 100) if trades > 0 else 0.0
        
        regimes.append(
            RegimeFingerprintItem(
                regime=r["regime"],
                trades=trades,
                winrate=round(winrate, 1),
                rsi=round(r["avg_rsi"] or 0, 1),
                volume_ratio=round(r["avg_vol_ratio"] or 0, 2),
                atr_ratio=round(r["avg_atr_ratio"] or 0, 2),
                score=round(r["avg_score"] or 0, 2),
            )
        )

    return RegimeFingerprintResponse(regimes=regimes)
