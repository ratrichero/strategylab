"""
Backtest Replay — Orchestration Service
==========================================
Chạy toàn bộ replay job.
"""

import traceback
from datetime import datetime
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta


def _parse_date(raw, fallback_days_ago=None, fallback_future=False):
    """
    Parse date string linh hoạt:
    - "2026-06-01" -> datetime
    - "2026-06-01T00:00:00Z" -> datetime
    - None -> fallback
    """
    if not raw:
        if fallback_future:
            return datetime.now(timezone.utc) + timedelta(days=1)
        if fallback_days_ago:
            return datetime.now(timezone.utc) - timedelta(days=fallback_days_ago)
        return datetime.now(timezone.utc) - timedelta(days=30)

    raw = str(raw).strip()

    # "2026-06-01" -> thêm time
    if len(raw) == 10:
        raw = raw + "T00:00:00Z"

    # "2026-06-01T00:00:00" -> thêm Z
    if not raw.endswith("Z") and "+" not in raw:
        raw = raw + "Z"

    # Parse
    raw = raw.replace("Z", "+00:00")
    return datetime.fromisoformat(raw)

from app.services.backtest.replay_models import (
    ReplaySummary,
    PolicyInfo,
    PolicyLevel,
    OutcomeSummary,
    DeltaSummary,
    ActualOutcome,
    DeltaOutcome,
    TradeRow,
)
from app.services.backtest.replay_registry import (
    set_job_running,
    set_job_progress,
    set_job_done,
    set_job_failed,
)
from app.services.backtest.replay_loader import load_closed_signals
from app.services.backtest.replay_market_data import fetch_mark_klines_1m, get_horizon
from app.services.backtest.replay_simulator import simulate_trade

from app.core.time_utils import ensure_utc


BUFFER_PCT_MAP = {
    "15m": 0.002,
    "1h": 0.0025,
    "4h": 0.003,
}


def run_replay_job(job_id: str, params: dict):
    """
    Main orchestration. Gọi từ background thread.
    """
    try:
        set_job_running(job_id, "Loading signals...")

        signals = load_closed_signals(
            date_from=_parse_date(params.get("date_from"), fallback_days_ago=90),
            date_to=_parse_date(params.get("date_to"), fallback_future=True),
            timeframes=params.get("timeframes", []),
            symbols=params.get("symbols", []),
            strategies=params.get("strategies", []),
            limit=params.get("limit", 500),
            include_manual=params.get("include_manual", False),
        )

        if not signals:
            set_job_done(job_id, _empty_summary(job_id), [])
            return

        set_job_progress(job_id, 10, f"Loaded {len(signals)} signals. Fetching market data...")

        rows: List[TradeRow] = []
        total = len(signals)

        for idx, trade in enumerate(signals):
            try:
                entry_time = ensure_utc(datetime.fromisoformat(trade["entry_time"]))
                horizon = get_horizon(trade["timeframe"])
                end_time = entry_time + horizon

                bars = fetch_mark_klines_1m(
                    symbol=trade["symbol"],
                    start_time=entry_time,
                    end_time=end_time,
                )

                if bars is None or bars.empty:
                    continue

                sim_result = simulate_trade(trade, bars)

                actual_rr = _calc_actual_rr(trade)

                row = _build_trade_row(trade, sim_result, actual_rr)
                rows.append(row)

            except Exception as e:
                print(f"[BACKTEST] Error replaying signal {trade.get('signal_id')}: {e}")
                traceback.print_exc()

            pct = 10 + int((idx + 1) / total * 85)
            if (idx + 1) % 10 == 0 or idx == total - 1:
                set_job_progress(job_id, pct, f"Replayed {idx + 1}/{total}")

        summary = _build_summary(job_id, rows)

        set_job_done(job_id, summary, [r.dict() for r in rows])

    except Exception as e:
        traceback.print_exc()
        set_job_failed(job_id, f"{type(e).__name__}: {e}")


def _calc_actual_rr(trade: dict) -> float:
    entry = trade["entry_price"]
    r_value = trade["r_value_abs"]
    exit_price = trade.get("actual_exit_price")
    direction = trade["direction"]

    if not exit_price or r_value <= 0:
        return 0.0

    if direction == "LONG":
        return (exit_price - entry) / r_value
    else:
        return (entry - exit_price) / r_value


def _build_trade_row(trade: dict, sim_result: dict, actual_rr: float) -> TradeRow:
    sim = sim_result["simulated"]

    actual = ActualOutcome(
        exit_time=trade.get("actual_exit_time"),
        exit_price=trade.get("actual_exit_price"),
        exit_reason=trade.get("actual_exit_reason"),
        status=trade.get("actual_status"),
        result_pct=trade.get("actual_result_pct"),
        rr_realized=round(actual_rr, 4),
    )

    delta = DeltaOutcome(
        result_pct_diff=round(
            (sim.result_pct or 0) - (actual.result_pct or 0), 4
        ) if actual.result_pct is not None else None,
        rr_realized_diff=round(
            (sim.rr_realized or 0) - actual_rr, 4
        ) if actual_rr else None,
    )

    return TradeRow(
        signal_id=trade["signal_id"],
        symbol=trade["symbol"],
        timeframe=trade["timeframe"],
        strategy_name=trade.get("strategy_name"),
        pattern=trade.get("pattern"),
        direction=trade["direction"],
        entry_time=trade["entry_time"],
        entry_price=trade["entry_price"],
        initial_stop_loss=trade["initial_stop_loss"],
        tp_2r_price=trade["tp_2r_price"],
        r_value_abs=trade["r_value_abs"],
        actual=actual,
        simulated=sim,
        delta=delta,
        policy_levels=sim_result["policy_levels"],
        timeline=sim_result["timeline"],
    )


def _build_summary(job_id: str, rows: List[TradeRow]) -> ReplaySummary:
    if not rows:
        return _empty_summary(job_id)

    actual_returns = [r.actual.result_pct for r in rows if r.actual.result_pct is not None]
    actual_rrs = [r.actual.rr_realized for r in rows if r.actual.rr_realized is not None]
    sim_returns = [r.simulated.result_pct for r in rows if r.simulated.result_pct is not None]
    sim_rrs = [r.simulated.rr_realized for r in rows if r.simulated.rr_realized is not None]

    actual_wins = sum(1 for r in actual_returns if r > 0)
    sim_wins = sum(1 for r in sim_returns if r > 0)

    exit_breakdown = {}
    ambiguous_count = 0
    for r in rows:
        reason = r.simulated.exit_reason or "UNKNOWN"
        exit_breakdown[reason] = exit_breakdown.get(reason, 0) + 1
        if r.simulated.ambiguous_bar:
            ambiguous_count += 1

    n = len(rows)

    actual_summary = OutcomeSummary(
        winrate=round(actual_wins / len(actual_returns), 4) if actual_returns else None,
        avg_return_pct=round(sum(actual_returns) / len(actual_returns), 4) if actual_returns else None,
        avg_rr_realized=round(sum(actual_rrs) / len(actual_rrs), 4) if actual_rrs else None,
        median_rr_realized=round(sorted(actual_rrs)[len(actual_rrs) // 2], 4) if actual_rrs else None,
        total_rr_realized=round(sum(actual_rrs), 4) if actual_rrs else None,
        count=len(actual_returns),
    )

    sim_summary = OutcomeSummary(
        winrate=round(sim_wins / len(sim_returns), 4) if sim_returns else None,
        avg_return_pct=round(sum(sim_returns) / len(sim_returns), 4) if sim_returns else None,
        avg_rr_realized=round(sum(sim_rrs) / len(sim_rrs), 4) if sim_rrs else None,
        median_rr_realized=round(sorted(sim_rrs)[len(sim_rrs) // 2], 4) if sim_rrs else None,
        total_rr_realized=round(sum(sim_rrs), 4) if sim_rrs else None,
        count=len(sim_returns),
    )

    delta = DeltaSummary(
        winrate_diff=round((sim_summary.winrate or 0) - (actual_summary.winrate or 0), 4),
        avg_return_pct_diff=round((sim_summary.avg_return_pct or 0) - (actual_summary.avg_return_pct or 0), 4),
        avg_rr_realized_diff=round((sim_summary.avg_rr_realized or 0) - (actual_summary.avg_rr_realized or 0), 4),
        total_rr_realized_diff=round((sim_summary.total_rr_realized or 0) - (actual_summary.total_rr_realized or 0), 4),
    )

    policy = PolicyInfo(
        name="current_policy_v1",
        tp_r=2.0,
        levels=[
            PolicyLevel(
                name="BE",
                trigger_r=1.0,
                action="move_to_entry_plus_buffer",
            ),
            PolicyLevel(
                name="LOCK_0_5R",
                trigger_r=1.5,
                action="move_to_0_5R",
                target_r=0.5,
            ),
        ],
        intrabar_mode="conservative",
    )

    return ReplaySummary(
        job_id=job_id,
        sample_size=n,
        policy=policy,
        actual=actual_summary,
        simulated=sim_summary,
        delta=delta,
        sim_exit_breakdown=exit_breakdown,
        ambiguous_bars=ambiguous_count,
    )


def _empty_summary(job_id: str) -> ReplaySummary:
    return ReplaySummary(job_id=job_id, sample_size=0)