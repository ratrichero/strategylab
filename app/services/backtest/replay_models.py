"""
Backtest Replay — Pydantic Models
==================================
Request/Response schemas cho Signal Replay Backtest Phase 1.
"""

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============================================================
# REQUEST
# ============================================================

class ReplayRunRequest(BaseModel):
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    timeframes: List[str] = Field(default_factory=lambda: ["15m", "1h", "4h"])
    symbols: List[str] = Field(default_factory=list)
    strategies: List[str] = Field(default_factory=list)
    limit: int = Field(default=500, ge=1, le=2000)
    include_manual: bool = False
    directions: List[str] = Field(default_factory=list)
    patterns: List[str] = Field(default_factory=list)
    regimes: List[str] = Field(default_factory=list)


# ============================================================
# JOB STATUS
# ============================================================

class ReplayJobStatus(BaseModel):
    job_id: str
    status: str  # QUEUED, RUNNING, DONE, FAILED
    progress_pct: int = 0
    message: str = ""
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None


# ============================================================
# POLICY
# ============================================================

class PolicyLevel(BaseModel):
    name: str
    trigger_r: float
    action: str
    trigger_price: Optional[float] = None
    stop_after_trigger: Optional[float] = None
    buffer_pct: Optional[float] = None
    target_r: Optional[float] = None


class PolicyInfo(BaseModel):
    name: str = "current_policy_v1"
    tp_r: float = 2.0
    levels: List[PolicyLevel] = Field(default_factory=list)
    intrabar_mode: str = "conservative"
    horizon_map: Dict[str, str] = Field(default_factory=lambda: {
        "15m": "24h", "1h": "72h", "4h": "7d"
    })


# ============================================================
# ACTUAL / SIMULATED per trade
# ============================================================

class ActualOutcome(BaseModel):
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    status: Optional[str] = None
    result_pct: Optional[float] = None
    rr_realized: Optional[float] = None


class SimulatedOutcome(BaseModel):
    exit_time: Optional[str] = None
    exit_price: Optional[float] = None
    exit_reason: Optional[str] = None
    result_pct: Optional[float] = None
    rr_realized: Optional[float] = None
    max_rr_seen: Optional[float] = None
    level_1_hit: bool = False
    level_2_hit: bool = False
    ambiguous_bar: bool = False


class DeltaOutcome(BaseModel):
    result_pct_diff: Optional[float] = None
    rr_realized_diff: Optional[float] = None


# ============================================================
# SUMMARY
# ============================================================

class OutcomeSummary(BaseModel):
    winrate: Optional[float] = None
    avg_return_pct: Optional[float] = None
    avg_rr_realized: Optional[float] = None
    median_rr_realized: Optional[float] = None
    total_rr_realized: Optional[float] = None
    count: int = 0


class DeltaSummary(BaseModel):
    winrate_diff: Optional[float] = None
    avg_return_pct_diff: Optional[float] = None
    avg_rr_realized_diff: Optional[float] = None
    total_rr_realized_diff: Optional[float] = None


class ReplaySummary(BaseModel):
    job_id: str
    sample_size: int = 0
    policy: PolicyInfo = Field(default_factory=PolicyInfo)
    actual: OutcomeSummary = Field(default_factory=OutcomeSummary)
    simulated: OutcomeSummary = Field(default_factory=OutcomeSummary)
    delta: DeltaSummary = Field(default_factory=DeltaSummary)
    sim_exit_breakdown: Dict[str, int] = Field(default_factory=dict)
    ambiguous_bars: int = 0


# ============================================================
# TRADE ROW
# ============================================================

class TimelineEvent(BaseModel):
    time: str
    event: str
    new_stop: Optional[float] = None
    exit_price: Optional[float] = None


class TradeRow(BaseModel):
    signal_id: int
    symbol: str
    timeframe: str
    strategy_name: Optional[str] = None
    pattern: Optional[str] = None
    direction: str
    entry_time: str
    entry_price: float
    initial_stop_loss: float
    tp_2r_price: float
    r_value_abs: float

    actual: ActualOutcome = Field(default_factory=ActualOutcome)
    simulated: SimulatedOutcome = Field(default_factory=SimulatedOutcome)
    delta: DeltaOutcome = Field(default_factory=DeltaOutcome)

    policy_levels: List[PolicyLevel] = Field(default_factory=list)
    timeline: List[TimelineEvent] = Field(default_factory=list)


class TradeRowsPage(BaseModel):
    job_id: str
    page: int
    page_size: int
    total_rows: int
    items: List[TradeRow] = Field(default_factory=list)