"""
Backtest Replay — Policy Simulator
=====================================
Replay exit policy trên mark price 1m bars.

Policy-driven:
- tp_r lấy từ policy_config
- levels lấy từ policy_config
- nếu không có policy_config -> dùng default
- intrabar mode: conservative (SL ưu tiên nếu cùng bar)
"""

from typing import Dict, Any, List
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

DEFAULT_POLICY = {
    "tp_r": 2.0,
    "levels": [
        {"trigger_r": 1.0, "action": "move_to_entry", "buffer_pct": None},
        {"trigger_r": 1.5, "action": "move_to_r", "target_r": 0.5},
    ],
}


def simulate_trade(
    trade: Dict[str, Any],
    bars: pd.DataFrame,
    policy_config: Dict[str, Any] = None,
) -> Dict[str, Any]:
    """
    Simulate 1 trade theo policy config.

    Returns:
        {
          "simulated": SimulatedOutcome,
          "policy_levels": List[PolicyLevel],
          "timeline": List[TimelineEvent],
        }
    """
    if policy_config is None:
        policy_config = dict(DEFAULT_POLICY)

    direction = trade["direction"]
    entry_price = float(trade["entry_price"])
    initial_sl = float(trade["initial_stop_loss"])
    r_value = float(trade["r_value_abs"])
    timeframe = trade["timeframe"]

    tp_r = float(policy_config.get("tp_r", 2.0))
    levels_cfg = policy_config.get("levels", []) or []

    # Sort ascending theo trigger_r
    levels_cfg = sorted(
        levels_cfg,
        key=lambda x: float(x.get("trigger_r", 0) or 0)
    )

    default_buffer = BUFFER_PCT_MAP.get(timeframe, 0.002)

    # TP price
    if direction == "LONG":
        tp_price = entry_price + tp_r * r_value
    else:
        tp_price = entry_price - tp_r * r_value

    # Build runtime policy levels
    policy_levels: List[PolicyLevel] = []
    level_states = []

    for lv_cfg in levels_cfg:
        trigger_r = float(lv_cfg.get("trigger_r", 0) or 0)
        action = str(lv_cfg.get("action", "move_to_entry") or "move_to_entry")
        buffer_pct = float(lv_cfg.get("buffer_pct") or default_buffer)
        target_r = float(lv_cfg.get("target_r", 0) or 0)

        if direction == "LONG":
            trigger_price = entry_price + trigger_r * r_value
        else:
            trigger_price = entry_price - trigger_r * r_value

        if action == "move_to_entry":
            stop_after = entry_price * (1 + buffer_pct) if direction == "LONG" else entry_price * (1 - buffer_pct)
        elif action == "move_to_r":
            stop_after = entry_price + target_r * r_value if direction == "LONG" else entry_price - target_r * r_value
        else:
            stop_after = initial_sl

        name = _level_name_from_cfg(lv_cfg)

        policy_levels.append(
            PolicyLevel(
                name=name,
                trigger_r=trigger_r,
                action=action,
                trigger_price=round(trigger_price, 8),
                stop_after_trigger=round(stop_after, 8),
                buffer_pct=buffer_pct if action == "move_to_entry" else None,
                target_r=target_r if action == "move_to_r" else None,
            )
        )

        level_states.append({
            "trigger_r": trigger_r,
            "trigger_price": trigger_price,
            "stop_after": stop_after,
            "hit": False,
            "name": name,
        })

    # State
    current_sl = initial_sl
    max_rr_seen = 0.0
    ambiguous_bar = False
    timeline: List[Dict] = []

    exit_time = None
    exit_price = None
    exit_reason = None

    for _, bar in bars.iterrows():
        bar_time = bar["time"].isoformat()
        bar_high = float(bar["high"])
        bar_low = float(bar["low"])

        # Max RR seen
        if direction == "LONG":
            current_max_r = (bar_high - entry_price) / r_value if r_value > 0 else 0
        else:
            current_max_r = (entry_price - bar_low) / r_value if r_value > 0 else 0

        max_rr_seen = max(max_rr_seen, current_max_r)

        # Conservative intrabar:
        # Check SL BEFORE TP
        if direction == "LONG":
            sl_hit = bar_low <= current_sl
            tp_hit = bar_high >= tp_price
        else:
            sl_hit = bar_high >= current_sl
            tp_hit = bar_low <= tp_price

        # If both hit same bar => SL wins
        if sl_hit and tp_hit:
            ambiguous_bar = True
            exit_time = bar_time
            exit_price = current_sl
            exit_reason = _current_sl_reason(level_states)

            timeline.append({
                "time": bar_time,
                "event": f"AMBIGUOUS_{exit_reason}",
            })
            break

        if sl_hit:
            exit_time = bar_time
            exit_price = current_sl
            exit_reason = _current_sl_reason(level_states)

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

        # Apply ladder triggers after exit checks (conservative)
        for ls in level_states:
            if ls["hit"]:
                continue

            if direction == "LONG":
                triggered = bar_high >= ls["trigger_price"]
            else:
                triggered = bar_low <= ls["trigger_price"]

            if triggered:
                ls["hit"] = True
                current_sl = ls["stop_after"]

                timeline.append({
                    "time": bar_time,
                    "event": f"{ls['name']}_TRIGGERED",
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

    hit_levels = [ls for ls in level_states if ls["hit"]]

    sim = SimulatedOutcome(
        exit_time=exit_time,
        exit_price=round(exit_price, 8) if exit_price is not None else None,
        exit_reason=exit_reason,
        result_pct=round(result_pct, 4),
        rr_realized=round(rr_realized, 4),
        max_rr_seen=round(max_rr_seen, 4),
        level_1_hit=len(hit_levels) >= 1,
        level_2_hit=len(hit_levels) >= 2,
        ambiguous_bar=ambiguous_bar,
    )

    return {
        "simulated": sim,
        "policy_levels": policy_levels,
        "timeline": [TimelineEvent(**evt) for evt in timeline],
    }


def _current_sl_reason(level_states: list) -> str:
    """
    Derive exit reason based on last hit level.
    Keeps FE-compatible naming:
      - SL_INITIAL
      - SL_BE
      - SL_LOCK_0_5R
      - SL_LOCK_1R
      ...
    """
    hit_levels = [ls for ls in level_states if ls["hit"]]
    if not hit_levels:
        return "SL_INITIAL"

    last_hit = hit_levels[-1]
    name = str(last_hit.get("name", "")).upper()

    if name.startswith("BE"):
        return "SL_BE"

    if name.startswith("LOCK_"):
        return f"SL_{name}"

    return f"SL_{name}"


def _level_name_from_cfg(lv_cfg: dict) -> str:
    """
    Stable FE-friendly naming:
      move_to_entry -> BE
      move_to_r(0.5) -> LOCK_0_5R
      move_to_r(1.0) -> LOCK_1R
    """
    action = lv_cfg.get("action", "")
    trigger = float(lv_cfg.get("trigger_r", 0) or 0)

    if action == "move_to_entry":
        return "BE"

    if action == "move_to_r":
        target = float(lv_cfg.get("target_r", 0) or 0)
        target_label = _format_r_label(target)
        return f"LOCK_{target_label}"

    return f"LEVEL_{_format_r_label(trigger)}"


def _format_r_label(value: float) -> str:
    """
    0.5 -> 0_5R
    1.0 -> 1R
    1.25 -> 1_25R
    """
    s = f"{value}".rstrip("0").rstrip(".")
    s = s.replace(".", "_")
    return f"{s}R"