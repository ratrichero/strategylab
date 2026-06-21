"""
Backtest Replay — Orchestration Service
==========================================
Chạy toàn bộ replay job.

IMPORTANT:
- Policy phải được resolve từ params["policy"]
- Nếu FE không gửi → dùng DEFAULT_POLICY
- Nếu FE gửi percent-based → simulator sẽ convert sang R nội bộ
- Summary phải hiển thị đúng policy đang dùng, không hardcode
"""

import traceback
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

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
from app.services.backtest.replay_market_data import (
    batch_fetch_mark_klines,
    get_horizon,
    get_cache_key,
)
from app.services.backtest.replay_simulator import simulate_trade

from app.core.time_utils import ensure_utc


# ============================================================
# DEFAULT POLICY (R-based fallback)
# ============================================================

DEFAULT_POLICY = {
    "tp_r": 2.0,
    "levels": [
        {"trigger_r": 1.0, "action": "move_to_entry", "buffer_pct": 0.002},
        {"trigger_r": 1.5, "action": "move_to_r", "target_r": 0.5},
    ],
}


# ============================================================
# HELPERS
# ============================================================

def _parse_date(raw, fallback_days_ago=None, fallback_future=False):
    if not raw:
        if fallback_future:
            return datetime.now(timezone.utc) + timedelta(days=1)
        if fallback_days_ago is not None:
            return datetime.now(timezone.utc) - timedelta(days=fallback_days_ago)
        return datetime.now(timezone.utc)

    if isinstance(raw, datetime):
        return raw

    raw = str(raw).strip().replace("Z", "+00:00")
    return datetime.fromisoformat(raw)


def _resolve_policy(params: dict) -> dict:
    """
    Resolve policy config từ params:
    - Nếu FE gửi custom policy → dùng nó
    - Nếu không → dùng DEFAULT_POLICY
    """
    custom = params.get("policy") if params else None
    if custom and isinstance(custom, dict):
        print(f"[BT POLICY] Using custom policy: mode={custom.get('mode')}")
        return custom
    print("[BT POLICY] Using DEFAULT_POLICY (R-based)")
    return dict(DEFAULT_POLICY)


def _is_live_active() -> bool:
    try:
        from app.db.session import SessionLocal
        from app.services.live.capacity_service import get_capacity_snapshot
        from app.services.config_service import get_runtime_config

        cfg = get_runtime_config()
        c_config = int(cfg.get("MAX_OPEN_TRADES", 10) or 10)

        with SessionLocal() as db:
            snap = get_capacity_snapshot(db, c_config)

        return snap.c_open > 0 or snap.c_new > 0
    except Exception:
        return True


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


def _level_name(lv: dict) -> str:
    action = lv.get("action", "")
    trigger_r = lv.get("trigger_r", 0)
    trigger_pct = lv.get("trigger_pct", 0)

    if action == "move_to_entry":
        label = trigger_r or trigger_pct
        return f"BE_{label}"
    if action == "move_to_r":
        target = lv.get("target_r", 0)
        return f"LOCK_{target}R"
    if action == "move_stop_to_profit_pct":
        target = lv.get("target_profit_pct", 0)
        return f"LOCK_{target}PCT"
    return "LEVEL"


# ============================================================
# MAIN JOB
# ============================================================

def run_replay_job(job_id: str, params: dict):
    """
    Main orchestration. Gọi từ background thread.
    """
    try:
        set_job_running(job_id, "Loading signals...")

        date_from = _parse_date(params.get("date_from"), fallback_days_ago=90)
        date_to = _parse_date(params.get("date_to"), fallback_future=True)

        signals = load_closed_signals(
            date_from=date_from,
            date_to=date_to,
            timeframes=params.get("timeframes", []),
            symbols=params.get("symbols", []),
            strategies=params.get("strategies", []),
            directions=params.get("directions", []),
            patterns=params.get("patterns", []),
            regimes=params.get("regimes", []),
            limit=params.get("limit", 500),
            include_manual=params.get("include_manual", False),
        )

        if not signals:
            set_job_done(job_id, _empty_summary(job_id, params), [])
            return

        # Resolve policy
        policy_config = _resolve_policy(params)

        # Determine throttle
        live_active = _is_live_active()
        throttle_mode = "SLOW (live active)" if live_active else "FAST (idle)"

        print(
            f"[BACKTEST] Job {job_id} started "
            f"| {len(signals)} signals "
            f"| policy_mode={policy_config.get('mode', 'R-based')} "
            f"| throttle: {throttle_mode}"
        )

        set_job_progress(job_id, 5, f"Loaded {len(signals)} signals. Preparing batch fetch...")

        # ── Phase 1: Build fetch requests ────────────────
        fetch_requests = []
        signal_keys = {}

        for trade in signals:
            entry_time = ensure_utc(datetime.fromisoformat(trade["entry_time"]))
            horizon = get_horizon(trade["timeframe"])
            end_time = entry_time + horizon

            key = get_cache_key(trade["symbol"], entry_time, end_time)
            signal_keys[trade["signal_id"]] = {
                "key": key,
                "entry_time": entry_time,
                "end_time": end_time,
            }

            fetch_requests.append({
                "symbol": trade["symbol"],
                "start_time": entry_time,
                "end_time": end_time,
            })

        set_job_progress(job_id, 10, f"Fetching market data for {len(fetch_requests)} ranges...")

        # ── Phase 2: Batch fetch ─────────────────────────
        klines_cache = batch_fetch_mark_klines(
            fetch_requests=fetch_requests,
            live_active=live_active,
        )

        set_job_progress(
            job_id, 60,
            f"Fetched {len(klines_cache)} kline sets. Simulating..."
        )

        # ── Phase 3: Simulate ────────────────────────────
        rows: List[TradeRow] = []
        total = len(signals)
        skipped = 0

        for idx, trade in enumerate(signals):
            try:
                sig_info = signal_keys.get(trade["signal_id"])
                if not sig_info:
                    skipped += 1
                    continue

                bars = klines_cache.get(sig_info["key"])
                if bars is None or bars.empty:
                    skipped += 1
                    continue

                # QUAN TRỌNG: truyền policy_config vào simulator
                sim_result = simulate_trade(trade, bars, policy_config=policy_config)

                actual_rr = _calc_actual_rr(trade)
                row = _build_trade_row(trade, sim_result, actual_rr)
                rows.append(row)

            except Exception as e:
                print(f"[BACKTEST] Error replaying signal {trade.get('signal_id')}: {e}")
                traceback.print_exc()

            if (idx + 1) % 50 == 0 or idx == total - 1:
                pct = 60 + int((idx + 1) / total * 35)
                set_job_progress(job_id, pct, f"Simulated {idx + 1}/{total}")

        # QUAN TRỌNG: truyền params vào summary để build đúng policy info
        summary = _build_summary(job_id, rows, params)

        print(
            f"[BACKTEST] Job {job_id} complete "
            f"| {len(rows)} simulated / {skipped} skipped "
            f"| throttle: {throttle_mode}"
        )

        set_job_done(job_id, summary, [r.dict() for r in rows])

    except Exception as e:
        traceback.print_exc()
        set_job_failed(job_id, f"{type(e).__name__}: {e}")


# ============================================================
# BUILD TRADE ROW
# ============================================================

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


# ============================================================
# BUILD SUMMARY
# ============================================================

def _build_summary(job_id: str, rows: List[TradeRow], params: dict = None) -> ReplaySummary:
    if not rows:
        return _empty_summary(job_id, params)

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

    # Build policy info DYNAMICALLY từ params
    policy = _build_policy_info(params)

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


def _build_policy_info(params: dict = None) -> PolicyInfo:
    """
    Build PolicyInfo dynamically từ params["policy"].
    Nếu không có custom policy → hiển thị default.
    """
    policy_cfg = _resolve_policy(params or {})
    is_custom = bool(params and params.get("policy"))

    # Xử lý percent-based policy
    if policy_cfg.get("mode") == "percent":
        return _build_policy_info_percent(policy_cfg, is_custom)

    # R-based policy (default hoặc custom R)
    levels_info = []
    for lv in policy_cfg.get("levels", []):
        levels_info.append(PolicyLevel(
            name=_level_name(lv),
            trigger_r=float(lv.get("trigger_r", 0) or 0),
            action=lv.get("action", ""),
            trigger_price=None,
            stop_after_trigger=None,
            buffer_pct=lv.get("buffer_pct"),
            target_r=lv.get("target_r"),
        ))

    return PolicyInfo(
        name="custom_policy" if is_custom else "default_policy_v1",
        tp_r=float(policy_cfg.get("tp_r", 2.0)),
        levels=levels_info,
        intrabar_mode="conservative",
    )


def _build_policy_info_percent(policy_cfg: dict, is_custom: bool) -> PolicyInfo:
    """
    Build PolicyInfo cho percent-based policy.
    Hiển thị summary dạng "merged" cho user dễ đọc.
    """
    tf_configs = policy_cfg.get("timeframes", {})
    all_levels = []
    all_sl = set()
    all_tp = set()

    for tf, tf_cfg in tf_configs.items():
        sl = float(tf_cfg.get("sl_pct", 0) or 0)
        tp = float(tf_cfg.get("tp_pct", 0) or 0)
        all_sl.add(round(sl * 100, 2))
        all_tp.add(round(tp * 100, 2))

        for lv in tf_cfg.get("levels", []):
            trigger_pct = float(lv.get("trigger_pct", 0) or 0)
            action = lv.get("action", "")

            level_info = PolicyLevel(
                name=_level_name_pct(lv),
                trigger_r=round(trigger_pct * 100, 2),  # hiển thị dạng % cho dễ đọc
                action=action,
                trigger_price=None,
                stop_after_trigger=None,
                buffer_pct=lv.get("buffer_pct"),
                target_r=lv.get("target_profit_pct"),
            )

            # Dedup
            exists = any(
                l.name == level_info.name and l.trigger_r == level_info.trigger_r
                for l in all_levels
            )
            if not exists:
                all_levels.append(level_info)

    # TP hiển thị
    tp_display = max(all_tp) if all_tp else 0

    return PolicyInfo(
        name="custom_percent_policy" if is_custom else "default_percent_policy",
        tp_r=tp_display,  # hiển thị dạng % cho summary
        levels=all_levels,
        intrabar_mode="conservative",
    )


def _level_name_pct(lv: dict) -> str:
    action = lv.get("action", "")
    trigger = float(lv.get("trigger_pct", 0) or 0)
    trigger_display = round(trigger * 100, 2)

    if action == "move_to_entry":
        return f"BE_{trigger_display}%"
    if action == "move_stop_to_profit_pct":
        target = float(lv.get("target_profit_pct", 0) or 0)
        target_display = round(target * 100, 2)
        return f"LOCK_{target_display}%"
    return f"LEVEL_{trigger_display}%"


# ============================================================
# EMPTY SUMMARY
# ============================================================

def _empty_summary(job_id: str, params: dict = None) -> ReplaySummary:
    return ReplaySummary(
        job_id=job_id,
        sample_size=0,
        policy=_build_policy_info(params),
    )