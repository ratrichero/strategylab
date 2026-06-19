"""
Backtest Replay — Policy Simulator
=====================================
Replay exit policy trên mark price 1m bars.

Policy Phase 1:
- TP = 2R
- Level 1: 1.0R → BE + buffer
- Level 2: 1.5R → lock 0.5R
- Intrabar: conservative (SL ưu tiên nếu cùng bar)
"""

from typing import Dict, Any, List, Optional
import pandas as pd

from app.services.backtest.replay_models import (
    SimulatedOutcome,
    PolicyLevel,
    TimelineEvent,
)


BUFFER_PCT_MAP = {
    "15m": 0.002,
    "1h": 0.0025,
    "4h": 0.003,
}


def simulate_trade(
    trade: Dict[str, Any],
    bars: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Simulate 1 trade theo policy hiện tại.

    Returns dict với keys:
    - simulated: SimulatedOutcome
    - policy_levels: List[PolicyLevel]
    - timeline: List[TimelineEvent]
    """
    direction = trade["direction"]
    entry_price = float(trade["entry_price"])
    initial_sl = float(trade["initial_stop_loss"])
    tp_price = float(trade["tp_2r_price"])
    r_value = float(trade["r_value_abs"])
    timeframe = trade["timeframe"]

    buffer_pct = BUFFER_PCT_MAP.get(timeframe, 0.002)

    # Build policy levels
    if direction == "LONG":
        be_stop = entry_price * (1 + buffer_pct)
        lock_stop = entry_price + 0.5 * r_value
        level_1_trigger = entry_price + 1.0 * r_value
        level_2_trigger = entry_price + 1.5 * r_value
    else:
        be_stop = entry_price * (1 - buffer_pct)
        lock_stop = entry_price - 0.5 * r_value
        level_1_trigger = entry_price - 1.0 * r_value
        level_2_trigger = entry_price - 1.5 * r_value

    policy_levels = [
        PolicyLevel(
            name="BE",
            trigger_r=1.0,
            action="move_to_entry_plus_buffer",
            trigger_price=round(level_1_trigger, 8),
            stop_after_trigger=round(be_stop, 8),
            buffer_pct=buffer_pct,
        ),
        PolicyLevel(
            name="LOCK_0_5R",
            trigger_r=1.5,
            action="move_to_0_5R",
            trigger_price=round(level_2_trigger, 8),
            stop_after_trigger=round(lock_stop, 8),
            target_r=0.5,
        ),
    ]

    # State
    current_sl = initial_sl
    level_1_hit = False
    level_2_hit = False
    max_rr_seen = 0.0
    ambiguous_bar = False
    timeline: List[Dict] = []

    exit_time = None
    exit_price = None
    exit_reason = None

    for i, bar in bars.iterrows():
        bar_time = bar["time"].isoformat()
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])
        bar_close = float(bar["close"])

        # Compute current R at extremes
        if direction == "LONG":
            current_max_r = (bar_high - entry_price) / r_value if r_value > 0 else 0
            current_min_r = (bar_low - entry_price) / r_value if r_value > 0 else 0
        else:
            current_max_r = (entry_price - bar_low) / r_value if r_value > 0 else 0
            current_min_r = (entry_price - bar_high) / r_value if r_value > 0 else 0

        max_rr_seen = max(max_rr_seen, current_max_r)

        # Check SL hit (conservative: SL checked BEFORE TP)
        sl_hit = False
        if direction == "LONG":
            sl_hit = bar_low <= current_sl
        else:
            sl_hit = bar_high >= current_sl

        # Check TP hit
        tp_hit = False
        if direction == "LONG":
            tp_hit = bar_high >= tp_price
        else:
            tp_hit = bar_low <= tp_price

        # Conservative: if both hit same bar, SL wins
        if sl_hit and tp_hit:
            ambiguous_bar = True
            exit_time = bar_time
            exit_price = current_sl

            if level_2_hit:
                exit_reason = "SL_LOCK_0_5R"
            elif level_1_hit:
                exit_reason = "SL_BE"
            else:
                exit_reason = "SL_INITIAL"

            timeline.append({"time": bar_time, "event": f"AMBIGUOUS_{exit_reason}"})
            break

        if sl_hit:
            exit_time = bar_time
            exit_price = current_sl

            if level_2_hit:
                exit_reason = "SL_LOCK_0_5R"
            elif level_1_hit:
                exit_reason = "SL_BE"
            else:
                exit_reason = "SL_INITIAL"

            timeline.append({
                "time": bar_time,
                "event": f"EXIT_{exit_reason}",
                "exit_price": exit_price,
            })
            break

        if tp_hit:
            exit_time = bar_time
            exit_price = tp_price
            exit_reason = "TP"

            timeline.append({
                "time": bar_time,
                "event": "EXIT_TP",
                "exit_price": exit_price,
            })
            break

        # Level triggers (hiệu lực từ bar KẾ TIẾP, theo conservative rule)
        if not level_1_hit:
            triggered = False
            if direction == "LONG":
                triggered = bar_high >= level_1_trigger
            else:
                triggered = bar_low <= level_1_trigger

            if triggered:
                level_1_hit = True
                current_sl = be_stop
                timeline.append({
                    "time": bar_time,
                    "event": "LEVEL_1_TRIGGERED",
                    "new_stop": current_sl,
                })

        if level_1_hit and not level_2_hit:
            triggered = False
            if direction == "LONG":
                triggered = bar_high >= level_2_trigger
            else:
                triggered = bar_low <= level_2_trigger

            if triggered:
                level_2_hit = True
                current_sl = lock_stop
                timeline.append({
                    "time": bar_time,
                    "event": "LEVEL_2_TRIGGERED",
                    "new_stop": current_sl,
                })

    # Horizon exit
    if exit_reason is None and len(bars) > 0:
        last_bar = bars.iloc[-1]
        exit_time = last_bar["time"].isoformat()
        exit_price = float(last_bar["close"])
        exit_reason = "HORIZON"

        timeline.append({
            "time": exit_time,
            "event": "EXIT_HORIZON",
            "exit_price": exit_price,
        })

    # Compute result
    if exit_price is not None:
        if direction == "LONG":
            result_pct = ((exit_price - entry_price) / entry_price) * 100
            rr_realized = (exit_price - entry_price) / r_value if r_value > 0 else 0
        else:
            result_pct = ((entry_price - exit_price) / entry_price) * 100
            rr_realized = (entry_price - exit_price) / r_value if r_value > 0 else 0
    else:
        result_pct = 0.0
        rr_realized = 0.0

    sim = SimulatedOutcome(
        exit_time=exit_time,
        exit_price=round(exit_price, 8) if exit_price else None,
        exit_reason=exit_reason,
        result_pct=round(result_pct, 4),
        rr_realized=round(rr_realized, 4),
        max_rr_seen=round(max_rr_seen, 4),
        level_1_hit=level_1_hit,
        level_2_hit=level_2_hit,
        ambiguous_bar=ambiguous_bar,
    )

    timeline_events = [
        TimelineEvent(**evt) for evt in timeline
    ]

    return {
        "simulated": sim,
        "policy_levels": policy_levels,
        "timeline": timeline_events,
    }