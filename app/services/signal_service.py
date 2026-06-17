import pandas as pd
import numpy as np
from datetime import datetime, timezone, timedelta
import time
import traceback
from app.core.time_utils import utc_now, utc_after, utc_before, pd_ts_to_utc

from app.services.binance_service import get_top_symbols, get_klines,get_klines_closed,get_binance_server_time,get_all_prices
from app.services.indicator_service import add_indicators, add_indicators_advanced, detect_regime, detect_regime_advanced, get_market_state,build_indicator_snapshot
from app.services.pattern_service import detect_pattern
from app.services.telegram_service import send_telegram

from app.db.session import SessionLocal
from app.db.models import Signal, SignalFeature,PendingSignal  # ← CHANGED: gộp import

from app.ml.predict import predict_prob
from app.ml.features import build_features_from_row
from app.services.llm_router import generate_explanation
from app.db.models import ScanConfig, ScanRun, ScanDebug
from app.services.mtf_service import MTFCalculator
from app.services.derivatives_service import compute_derivative_bias
from app.services.block_service import check_htf_atr_block,check_funding_block,HTF_BLOCK_CONFIG
from app.services.config_service import get_runtime_config

from app.strategies.registry import get_active_strategies
from app.services.open_trade_filter import get_open_trade_filter
from app.core.trading_mode import get_current_mode, TradingMode

# ── Timeframe-based Weights dùng để tính score ───────────────────────────────

WEIGHTS = {
    "15m": {
        "trend": 0.25,
        "momentum": 0.25,
        "volume": 0.10,
        "pattern": 0.15,
        "mtf": 0.25
    },
    "1h": {
        "trend": 0.30,
        "momentum": 0.20,
        "volume": 0.10,
        "pattern": 0.15,
        "mtf": 0.25
    },
    "4h": {
        "trend": 0.30,
        "momentum": 0.15,
        "volume": 0.10,
        "pattern": 0.10,
        "mtf": 0.35
    }
}

MAX_COMPONENTS = {
    "trend": 3,
    "momentum": 2,
    "volume": 2,
    "pattern": 2
}

PENALTY_WEIGHTS = {
    "body": 0.5,
    "volume": 0.5,
    "atr": 0.5,
    "regime_mismatch": 0.3,
    "regime_sideways": 0.1
}

def normalize_component(value, max_value):
    if max_value <= 0:
        return 0.0
    return max(0.0, min(1.0, value / max_value))

# ============================================================
# TIMEZONE HELPER
# ============================================================

def to_local_time(dt):
    return dt.replace(tzinfo=timezone.utc).astimezone(
        timezone(timedelta(hours=7))
    )

def get_hanoi_time():
    return datetime.now(timezone(timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# FORMAT HELPER
# ============================================================

def fmt(val, width, decimals=2):
    """Format giá trị thành string cố định width. None → '─'"""
    if val is None or val == "":
        return f"{'─':>{width}}"
    try:
        f = float(val)
        if decimals == 0:
            s = str(int(round(f)))
        else:
            s = f"{f:.{decimals}f}"
    except (TypeError, ValueError):
        s = str(val)
    if len(s) > width:
        s = s[:width]
    return f"{s:>{width}}"

def sanitize_value(v):
    # numpy → python native
    if isinstance(v, (np.floating, np.integer)):
        return float(v)

    # pandas Timestamp → datetime
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()

    return v

def sanitize_row(row: dict):
    return {k: sanitize_value(v) for k, v in row.items()}

# ============================================================
# SCORE BAR + COLOR
# ============================================================

def score_bar(score, max_score=10, width=10):
    if score is None:
        return ""
    filled = int((score / max_score) * width)
    return "█" * filled + "░" * (width - filled)

def color_score(score):
    if score is None:
        return ""
    if score >= 8:
        return f"\033[92m{score}\033[0m"
    elif score >= 6:
        return f"\033[93m{score}\033[0m"
    else:
        return f"\033[91m{score}\033[0m"


# ============================================================
#  HELPER
# ============================================================


def safe(v):
    import numpy as np
    import pandas as pd

    if isinstance(v, (np.floating, np.integer)):
        return float(v)

    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()

    return v


# ============================================================
# PATTERN-DRIVEN SCORE
# ← CHANGED: nhận htf_df từ ngoài, bỏ get_klines bên trong
# ============================================================

def calculate_score(df, pattern, cfg, symbol, timeframe,trend_df=None, context_df=None,regime=None):

    # ✅ FIX: tránh crash khi thiếu dữ liệu
    if df is None or len(df) < 3:
        return 0, None, {}
    
    last = df.iloc[-1]

    state = get_market_state(df)

    # ── Direction ───────────────────────────────────────────
    bullish_patterns = ["Bullish Engulfing", "Hammer", "Morning Star", "Bullish Marubozu"]
    bearish_patterns = ["Bearish Engulfing", "Shooting Star", "Evening Star", "Bearish Marubozu"]

    if pattern in bullish_patterns:
        direction = "LONG"
    elif pattern in bearish_patterns:
        direction = "SHORT"
    else:
        return 0, None, {}

    trend_score    = 0
    momentum_score = 0
    volume_score   = 0
    pattern_score  = 0
    mtf_score      = 0
    
    # ── Trend (continuous, ATR-normalized) ─────────────────────

    ema200 = last.get("ema200")
    ema50  = last.get("ema50")
    atr    = last.get("atr")
    close  = last.get("close")

    if (
        ema200 is not None and not pd.isna(ema200) and ema200 != 0 and
        atr is not None and not pd.isna(atr) and atr > 0 and
        close is not None and not pd.isna(close)
    ):

        # 1️⃣ Distance component (max 2 points)
        distance_atr = (close - ema200) / atr

        if direction == "LONG":
            distance_component = max(0.0, min(1.0, distance_atr / 2.0))
        else:
            distance_component = max(0.0, min(1.0, -distance_atr / 2.0))

        trend_distance_score = 2 * distance_component

        # 2️⃣ Structure component (max 1 point)
        structure_component = 0.0

        if ema50 is not None and not pd.isna(ema50):
            ema_gap = (ema50 - ema200) / ema200

            if direction == "LONG" and ema_gap > 0:
                structure_component = min(1.0, ema_gap * 50)

            elif direction == "SHORT" and ema_gap < 0:
                structure_component = min(1.0, -ema_gap * 50)

        trend_structure_score = 1 * structure_component

        trend_score = trend_distance_score + trend_structure_score

    # ── Momentum ────────────────────────────────────────────
    rsi = last.get("rsi")

    if rsi is not None:
        if direction == "LONG" and state["rsi_oversold"]:
            momentum_score += 0.5
        elif direction == "SHORT" and state["rsi_overbought"]:
            momentum_score += 0.5

        if direction == "LONG":
            if rsi < 35:
                momentum_score += 2
            elif 35 <= rsi <= 45:
                momentum_score += 1
        else:
            if rsi > 65:
                momentum_score += 2
            elif 55 <= rsi <= 65:
                momentum_score += 1

    # ── Volume ──────────────────────────────────────────────
    vol_ratio = None

    vol_ma = last.get("vol_ma")

    if vol_ma is not None and not pd.isna(vol_ma) and vol_ma > 0:
        vol_ratio = last["volume"] / vol_ma
    else:
        vol_ratio = None

    # Volume scoring
    if vol_ratio is not None:
        if vol_ratio >= 2:
            volume_score += 2
        elif vol_ratio >= cfg["VOLUME_MULTIPLIER"]:
            volume_score += 1

    if state["high_volume"]:
        volume_score += 0.5

    # ── Pattern strength ────────────────────────────────────
    pattern_strength = {
        "Morning Star":      2,
        "Evening Star":      2,
        "Bullish Engulfing": 2,
        "Bearish Engulfing": 2,
        "Hammer":            1.5,
        "Shooting Star":     1.5,
        "Bullish Marubozu":  1.5,
        "Bearish Marubozu":  1.5
    }

    base       = pattern_strength.get(pattern, 0)
    body       = abs(last["close"] - last["open"])
    full_range = last["high"] - last["low"]

    if full_range > 0:
        pattern_score = base * (body / full_range)

    bb_position = last.get("bb_position")
    if bb_position is not None:
        if direction == "LONG" and bb_position < 0.2:
            pattern_score += 0.5
        elif direction == "SHORT" and bb_position > 0.8:
            pattern_score += 0.5

    # ── MTF ─────────────────────────────────────────────────
    mtf_score = 0

    if cfg.get("MTF_ENABLED", False):
        mtf_score = MTFCalculator.compute_mtf_score(
            direction=direction,
            trend_df=trend_df,
            context_df=context_df
        )
    #print(f"[MTF FINAL] mtf_score={mtf_score:.6f}")
    
    # ── Penalty Engine ───────────────────────────────
    body_ratio = body / full_range if full_range > 0 else 0

    atr = last.get("atr")
    close = last.get("close")
    if atr is not None and close is not None and not pd.isna(atr) and not pd.isna(close) and atr > 0 and close > 0:
        atr_ratio = atr / close
    else:
        atr_ratio = 0

    
    total_penalty = 0.0

    if body_ratio < cfg["BODY_RATIO_THRESHOLD"]:
        total_penalty -= PENALTY_WEIGHTS["body"]

    if vol_ratio is None:
        total_penalty -= PENALTY_WEIGHTS["volume"]

    elif vol_ratio < cfg["VOLUME_MULTIPLIER"]:
        total_penalty -= PENALTY_WEIGHTS["volume"]

    if atr_ratio < cfg["ATR_RATIO_MIN"]:
        total_penalty -= PENALTY_WEIGHTS["atr"]

    # Regime penalties
    if regime == "BULL" and direction == "SHORT":
        total_penalty -= PENALTY_WEIGHTS["regime_mismatch"]

    elif regime == "BEAR" and direction == "LONG":
        total_penalty -= PENALTY_WEIGHTS["regime_mismatch"]

    elif regime == "SIDEWAYS":
        total_penalty -= PENALTY_WEIGHTS["regime_sideways"]

    MAX_TOTAL_PENALTY = sum(PENALTY_WEIGHTS.values())
    penalty_norm = total_penalty / MAX_TOTAL_PENALTY if MAX_TOTAL_PENALTY > 0 else 0

    # fallback nếu timeframe lạ
    weights = WEIGHTS.get(timeframe, {
        "trend": 0.30,
        "momentum": 0.20,
        "volume": 0.15,
        "pattern": 0.20,
        "mtf": 0.15
    })

    # ── Normalize ───────────────────────────────────────────
    trend_norm    = normalize_component(trend_score, MAX_COMPONENTS["trend"])
    momentum_norm = normalize_component(momentum_score, MAX_COMPONENTS["momentum"])
    volume_norm   = normalize_component(volume_score, MAX_COMPONENTS["volume"])
    pattern_norm  = normalize_component(pattern_score, MAX_COMPONENTS["pattern"])
    mtf_norm = mtf_score

    rule_score = (
    weights["trend"]    * trend_norm +
    weights["momentum"] * momentum_norm +
    weights["volume"]   * volume_norm +
    weights["pattern"]  * pattern_norm +
    weights["mtf"]      * mtf_norm
) + penalty_norm

    # ← CHANGED: clamp để tránh out of range
    final_score = round(max(0.0, min(10.0, (rule_score + 1) * 5)), 2)

    components = {
        "trend_score": trend_score,
        "momentum_score": momentum_score,
        "volume_score": volume_score,
        "pattern_score": pattern_score,
        "mtf_score": mtf_score,
        "total_penalty": total_penalty,
        "penalty_norm": penalty_norm,
        "rule_score_raw": rule_score,
        "rule_score_scaled": final_score,
        "weights_used": weights
    }

    return final_score, direction, components


# ============================================================
# DUPLICATE + COOLDOWN
# ============================================================

def is_duplicate(db, symbol, timeframe, candle_time):
    return db.query(Signal).filter(
        Signal.symbol    == symbol,
        Signal.timeframe == timeframe,
        Signal.candle_time == candle_time
    ).first() is not None

def in_cooldown(db, symbol, timeframe, hours=4):
    cutoff     = utc_before(hours=hours)

    return db.query(Signal).filter(
        Signal.symbol    == symbol,
        Signal.timeframe == timeframe,
        Signal.status.in_(["WIN", "LOSS", "MANUAL"]),  # ✅ chỉ lệnh đã đóng
        Signal.exit_time != None,                      # ✅ có exit_time
        Signal.exit_time >= cutoff                     # ✅ tính từ lúc đóng
    ).first() is not None

def _in_cooldown_v2(db, symbol, timeframe, strategy_name, hours=4):
    """Cooldown check theo symbol + timeframe + strategy_name."""
    cutoff     = utc_before(hours=hours)
    return db.query(Signal).filter(
        Signal.symbol        == symbol,
        Signal.timeframe     == timeframe,
        Signal.strategy_name == strategy_name,
        Signal.status.in_(["WIN", "LOSS", "MANUAL"]),
        Signal.exit_time     != None,
        Signal.exit_time     >= cutoff
    ).first() is not None

# ============================================================
# SCAN RUNNERS
# ============================================================

def run_market_scan_multi_tf():
    

    runtime_cfg = get_runtime_config(force_reload=True)
    

    # 🛑 CHẶN TẠI ĐÂY: Nếu TOP_LIMIT <= 0, coi như hệ thống đã dừng.
    # Không cần mở DB, không cần tính toán logic, không tốn resource.
    if runtime_cfg.get("TOP_LIMIT", 0) <= 0:
        print(f"💤 Scan system is PAUSED (TOP_LIMIT = 0)")
        return
    
    now        = utc_now()

    # ← CHANGED: dùng context manager, không double-close
    with SessionLocal() as db:
        if now.minute in [1, 16, 31, 46]:
            scan_timeframe(db, "15m", runtime_cfg)

        if now.minute == 5:
            scan_timeframe(db, "1h", runtime_cfg)

        if now.minute == 10 and now.hour % 4 == 0:
            scan_timeframe(db, "4h", runtime_cfg)


def run_market_scan_single_tf(timeframe):
    
    runtime_cfg = get_runtime_config(force_reload=True)

    print(f"\n🚀 Running SINGLE TF scan: {timeframe}")

    # ← CHANGED: dùng context manager, không double-close
    with SessionLocal() as db:
        result = scan_timeframe(db, timeframe, runtime_cfg)

    return result


# ============================================================
# MAIN SCAN ENGINE
# ============================================================

def scan_timeframe(db, timeframe, runtime_cfg):

    config = ScanConfig(
    timeframe=timeframe,
    score_threshold=runtime_cfg["SCORE_THRESHOLD"],
    body_ratio_threshold=runtime_cfg["BODY_RATIO_THRESHOLD"],
    volume_multiplier=runtime_cfg["VOLUME_MULTIPLIER"],
    atr_ratio_min=runtime_cfg["ATR_RATIO_MIN"],
    cooldown_hours=runtime_cfg["COOLDOWN_HOURS"],
    ai_threshold=runtime_cfg["AI_THRESHOLD"],
    top_limit=runtime_cfg["TOP_LIMIT"],
    mtf_enabled=runtime_cfg["MTF_ENABLED"]
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    engine_version = runtime_cfg.get("ENGINE_VERSION")
    deriv_cfg = runtime_cfg.get("DERIVATIVE_CONFIG", {})
    pre_buffer = deriv_cfg.get("pre_buffer", 1)
    bias_scale_map = deriv_cfg.get("bias_scale", {
        "15m": 0.6,
        "1h": 0.8,
        "4h": 1.0
    })
    engine_metadata = {
    "engine_version": engine_version,
    "mtf_version": 2.1,
    "mtf_structure": "2-layer ATR normalized",
    "regime_mode": "penalty",
    "regime_penalty": 0.3,
    "weight_profile": "default_v1",
    "score_scaling": "linear_v1",
    "signal": "trigger_price",
    "indicator_snapshot_version": 1,
    "snapshot_features": ["ema50", "ema200", "ema200_slope", "rsi", "rsi_slope", "atr_percentile", "bb_width"],
    "derivative": {"enabled": True,"pre_buffer": pre_buffer,"bias_scale": bias_scale_map}
    }
    scan_run = ScanRun(
        timeframe=timeframe,
        config_id=config.id,
        scan_time       = utc_now(),
        engine_metadata=engine_metadata
    )
    db.add(scan_run)
    db.commit()   # ✅ FIX CHÍNH Ở ĐÂY
    db.refresh(scan_run)

    symbols         = get_top_symbols(runtime_cfg["TOP_LIMIT"])
    SCORE_THRESHOLD = runtime_cfg["SCORE_THRESHOLD"]
    BATCH_SIZE      = 100
    BATCH_SLEEP     = 1
    server_now = get_binance_server_time()

    scan_stats = {
        "timeframe":            timeframe,
        "total_symbols":        0,
        "pattern_detected":     0,
        "score_reject":         0,
        "regime_blocked":       0,
        "open_signal_blocked":  0,   # ← CHANGED: tách riêng khỏi cooldown
        "duplicate_blocked":    0,
        "cooldown_blocked":     0,
        "ml_blocked":           0,
        "htf_blocked":          0,
        "funding_blocked":      0,
        "pending_created":      0,
        "sent":                 0,
        "otf_blocked":          0
    }

    debug_rows = []

    print(f"\n🔄 ===== SCAN {timeframe} | Time: {get_hanoi_time()} =====")

    mtf_map = MTFCalculator.get_timeframe_map(timeframe)
    trend_tf = mtf_map["trend"]
    context_tf = mtf_map["context"]

    trend_cache = {}
    context_cache = {}

    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i:i + BATCH_SIZE]

        for symbol in batch:

            scan_stats["total_symbols"] += 1

            try:
                # ================= DATA =================
                
                lookback = HTF_BLOCK_CONFIG.get(timeframe, {}).get("lookback", 200)
                
                # ✅ FIX: đảm bảo tối thiểu 50 để vol_ma(20) và atr(14) warm-up đủ
                lookback = max(lookback, 50)
                
                df = get_klines_closed(symbol, interval=timeframe, limit=lookback,server_now=server_now)

                if df is None or df.empty or len(df) < 3:
                    continue

                df = add_indicators_advanced(
                    df,
                    ema_period=200,
                    rsi_period=14,
                    atr_period=14,
                    volume_ma_period=20
                )
                last = df.iloc[-1]

                # ================= MTF =================

                trend_df = None
                context_df = None

                if runtime_cfg.get("MTF_ENABLED"):

                    # ---- TREND TF ----
                    if trend_tf:
                        if symbol not in trend_cache:

                            raw_trend = get_klines_closed(
                                symbol, interval=trend_tf, limit=250,server_now=server_now
                            )

                            if raw_trend is not None and len(raw_trend) >= 50:
                                trend_cache[symbol] = add_indicators_advanced(raw_trend)
                            else:
                                trend_cache[symbol] = None

                        trend_df = trend_cache[symbol]

                    # ---- CONTEXT TF ----
                    if context_tf:
                        if symbol not in context_cache:

                            raw_ctx = get_klines_closed(
                                symbol, interval=context_tf, limit=250,server_now=server_now
                            )

                            if raw_ctx is not None and len(raw_ctx) >= 50:
                                context_cache[symbol] = add_indicators_advanced(raw_ctx)
                            else:
                                context_cache[symbol] = None

                        context_df = context_cache[symbol]

                # ================= REGIME =================
                regime = detect_regime_advanced(
                    df,
                    method="hybrid",
                    lookback=10,
                    threshold=0.002
                )

                # ================= Strategy Multi =================

                # ── STRATEGY ENGINE ──────────────────────────────
                active_strats = get_active_strategies(runtime_cfg)

                signal_candidates = []
            

                for strat in active_strats:
                    try:
                        sig = strat.detect(df, timeframe)
                        if not sig or not sig.valid:
                            continue
                        sig = strat.score(
                            df=df, signal=sig, timeframe=timeframe,
                            trend_df=trend_df, context_df=context_df,
                            regime=regime, cfg=runtime_cfg
                        )
                        signal_candidates.append(sig)
                    except Exception as e:
                        print(f"[STRATEGY ERR] {strat.STRATEGY_NAME} {symbol}: {e}")

                if not signal_candidates:
                    continue

                best = max(signal_candidates, key=lambda s: s.final_score)
                pattern       = best.pattern
                strategy_name = best.strategy_name
                direction     = best.direction
                components    = best.components

                scan_stats["pattern_detected"] += 1

                # ================= SCORE =================
                
                score = best.final_score

                # ================= derivative buff score =================
                technical_score = score

                technical_floor = SCORE_THRESHOLD - pre_buffer

                if technical_score < technical_floor:
                    scan_stats["score_reject"] += 1
                    continue

                raw_bias = compute_derivative_bias(
                    symbol=symbol,
                    timeframe=timeframe,
                    direction=direction
                )

                bias_scale = bias_scale_map.get(timeframe, 0.6)

                derivative_bias = raw_bias * bias_scale
                # Final Score đã được buff các chỉ số liên quan đến Funding, OL...
                score = round(
                    max(0, min(10, technical_score + derivative_bias)),
                    2
                )

                # ================= INDICATOR SNAPSHOT =================

                indicators_snapshot = build_indicator_snapshot(df,engine_version)

                # ================= CREATE DEBUG (DB) =================
                debug = ScanDebug(
                    scan_id=scan_run.id,
                    symbol=symbol,
                    pattern=pattern,
                    strategy_name=strategy_name,
                    direction=direction,
                    trend_score=float(components.get("trend_score", 0)),
                    momentum_score=float(components.get("momentum_score", 0)),
                    volume_score=float(components.get("volume_score", 0)),
                    pattern_score=float(components.get("pattern_score", 0)),
                    mtf_score=float(components.get("mtf_score", 0)),
                    penalty=float(components.get("penalty_norm", 0)),
                    total_score=float(score),
                    passed_score=score >= SCORE_THRESHOLD,
                    derivative_bias=float(derivative_bias),
                    block_reason=None,
                    regime=regime,
                    candle_time=pd_ts_to_utc(last["time"]),
                    ml_prob=None,
                    rule_score_raw=float(components.get("rule_score_raw", 0)),
                    indicators_snapshot=indicators_snapshot
                )

                db.add(debug)
                db.flush()

                # ================= DEBUG LOG =================
                debug_rows.append({
                    "symbol": symbol,
                    "pattern": pattern,
                    "direction": direction,
                    "trend": components.get("trend_score"),
                    "momentum": components.get("momentum_score"),
                    "volume": components.get("volume_score"),
                    "pattern_score": components.get("pattern_score"),
                    "mtf": components.get("mtf_score"),
                    "penalty": components.get("penalty_norm"),
                    "total_score": score,
                    "passed_score": score >= SCORE_THRESHOLD,
                    "block_reason": None,
                    "candle_time": last["time"].to_pydatetime(),
                    "ml_prob": None,
                    "regime": regime,
                    "derivative_bias": derivative_bias,
                })

                # ================= FILTER =================
                if score < SCORE_THRESHOLD:
                    debug.block_reason = "score_threshold"
                    debug_rows[-1]["block_reason"] = "score_threshold"
                    scan_stats["score_reject"] += 1
                    continue

                # ── OTF CHECK ────────────────────────────────────
                otf = get_open_trade_filter(runtime_cfg.get("OPEN_TRADE_FILTER"))
                _atr_r = None
                if last.get("atr") and last.get("close") and float(last["close"]) > 0:
                    _atr_r = float(last["atr"]) / float(last["close"])

                otf_ok, otf_reason = otf.check(
                    symbol=symbol, direction=direction,
                    strategy_name=strategy_name, pattern=pattern,
                    timeframe=timeframe, regime=regime, score=score,
                    ml_prob=None, components=components,
                    atr_ratio=_atr_r, db=db
                )
                
                if not otf_ok:
                    debug.block_reason = f"OTF::{otf_reason}"
                    debug_rows[-1]["block_reason"] = f"OTF::{otf_reason}"
                    scan_stats["otf_blocked"] = scan_stats.get("otf_blocked", 0) + 1
                    continue

                # ── Open signal check ────────────────────────

                from app.core.trading_mode import get_trading_mode
                mode_manager = get_trading_mode()
                mode = mode_manager.get_mode()
                rule = mode_manager.get_conflict_rule()

                open_cond = rule.get_open_signal_block_condition(
                    symbol, strategy_name, timeframe, mode
                )
                existing_open = db.query(Signal).filter_by(**open_cond).first()

                if existing_open:
                    debug.block_reason = "open_exist"
                    debug_rows[-1]["block_reason"] = "open_signal"
                    scan_stats["open_signal_blocked"] += 1
                    continue

                # Khong biet co y nghia gi khi xuat hien o day, tam comment

                #if df is None or len(df) < 2:
                #    continue
                #last = df.iloc[-1]

                # ================= DUPLICATE =================
                candle_time = pd_ts_to_utc(last["time"])

                if is_duplicate(db, symbol, timeframe, candle_time):
                    debug.block_reason = "duplicate"
                    debug_rows[-1]["block_reason"] = "duplicate"
                    scan_stats["duplicate_blocked"] += 1
                    continue

                if _in_cooldown_v2(db, symbol, timeframe, strategy_name,hours=runtime_cfg["COOLDOWN_HOURS"]):
                    debug.block_reason = "cooldown"
                    debug_rows[-1]["block_reason"] = "cooldown"
                    scan_stats["cooldown_blocked"] += 1
                    continue

                # ================= ML =================
                features = build_features_from_row(last, components, direction)
                prob = predict_prob(features)

                debug.ml_prob = float(prob) if prob is not None else None

                if prob is not None and prob < runtime_cfg["AI_THRESHOLD"]:
                    debug.block_reason = "ml_threshold"
                    debug_rows[-1]["block_reason"] = "ml_threshold"
                    scan_stats["ml_blocked"] += 1
                    continue

                # ================= HTF BLOCK: Kiểm tra nếu gia đã tăng quá hoặc giảm quá 25 30% thì ko Long Short đuổi nữa=================

                # ================= HTF ATR BLOCK =================

                block, reason = check_htf_atr_block(
                    df=df,
                    direction=direction,
                    timeframe=timeframe
                )

                if block:
                    debug.block_reason = f"HTF::{reason}"
                    debug_rows[-1]["block_reason"] = f"HTF::{reason}"
                    scan_stats["htf_blocked"] += 1
                    continue


                # ================= FUNDING BLOCK =================

                block, reason = check_funding_block(
                    symbol=symbol,
                    direction=direction,
                    timeframe=timeframe
                )

                if block:
                    debug.block_reason = f"FUNDING::{reason}"
                    debug_rows[-1]["block_reason"] = f"FUNDING::{reason}"
                    scan_stats["funding_blocked"] += 1
                    continue

                # ============================================================
                # ================= CREATE PENDING (FINAL) ===================
                # ============================================================

                pending_cfg = runtime_cfg.get("PENDING_CONFIG", {})

                if not pending_cfg.get("enabled", False):
                    continue  # nếu pending bị tắt thì skip (hoặc bạn có thể fallback market entry)

                # ✅ BLOCK: nếu đã có pending WAIT cùng symbol + timeframe
                pending_cond = rule.get_pending_block_condition(
                    symbol, strategy_name, timeframe, mode
                )
                existing_pending = db.query(PendingSignal).filter_by(
                    **pending_cond
                ).first()

                if existing_pending:
                    debug.block_reason = "pending_exist"
                    debug_rows[-1]["block_reason"] = "pending_exist"
                    continue

                atr_val = float(last["atr"])
                #close_price = float(last["close"])
                
                price_map = get_all_prices()
                current_price = price_map.get(symbol)

                if not current_price:
                    continue

                close_price = float(current_price)

                if atr_val <= 0:
                    continue

                # ✅ ATR ENTRY MULTIPLIER
                atr_mult_entry = pending_cfg.get("atr_entry_multiplier", {}).get(timeframe, 0.5)
                expire_hours = pending_cfg.get("expire_hours", {}).get(timeframe, 4)

                # ================= ENTRY CALC =================

                if direction == "LONG":
                    trigger_price = close_price - atr_val * atr_mult_entry
                else:
                    trigger_price = close_price + atr_val * atr_mult_entry

                # ================= SL / TP CALC FROM TRIGGER =================

                """ SL tính theo ATR, chuyển lại ve fix%
                risk_cfg = runtime_cfg.get("RISK_CONFIG", {}).get(
                    timeframe,
                    {"sl_mult": 1.5, "tp_mult": 3}
                )

                sl_mult = risk_cfg["sl_mult"]
                tp_mult = risk_cfg["tp_mult"]

                if direction == "LONG":
                    sl = trigger_price - atr_val * sl_mult
                    tp = trigger_price + atr_val * tp_mult
                else:
                    sl = trigger_price + atr_val * sl_mult
                    tp = trigger_price - atr_val * tp_mult

                rr = None
                """

                risk_cfg = runtime_cfg.get("RISK_CONFIG", {}).get(
                    timeframe,
                    {"sl_mult": 0.02, "tp_mult": 0.04}
                )

                sl_pct = risk_cfg["sl_mult"]
                tp_pct = risk_cfg["tp_mult"]

                if direction == "LONG":
                    sl = trigger_price * (1 - sl_pct)
                    tp = trigger_price * (1 + tp_pct)
                else:
                    sl = trigger_price * (1 + sl_pct)
                    tp = trigger_price * (1 - tp_pct)

                rr = tp_pct / sl_pct if sl_pct > 0 else 2.0

                if trigger_price != sl:
                    rr = abs((tp - trigger_price) / (trigger_price - sl))

                expire_at  = utc_after(hours=expire_hours)

                # ================= CREATE FULL CONTEXT PENDING =================

                pending = PendingSignal(
                    symbol=symbol,
                    timeframe=timeframe,
                    pattern=pattern,
                    strategy_name=strategy_name,
                    direction=direction,

                    # ===== SCORE =====
                    signal_score=score,
                    rule_score_raw=components.get("rule_score_raw"),
                    derivative_bias=derivative_bias,

                    trend_score=components.get("trend_score"),
                    momentum_score=components.get("momentum_score"),
                    volume_score=components.get("volume_score"),
                    pattern_score=components.get("pattern_score"),
                    mtf_score=components.get("mtf_score"),
                    penalty=components.get("penalty_norm"),

                    ml_prob=prob,
                    reprice_applied=False,

                    # ===== SNAPSHOT =====
                    indicators_snapshot=indicators_snapshot,
                    candle_time=pd_ts_to_utc(last["time"]),
                    engine_version=engine_version,          

                    # ===== ENTRY DATA =====
                    trigger_price=trigger_price,
                    stop_loss=sl,
                    take_profit=tp,
                    rr=rr,
                    atr_value=atr_val,
                    atr_mult_entry=atr_mult_entry,

                    regime=regime,

                    scan_id=scan_run.id,
                    scan_debug_id=debug.id,

                    expire_at=expire_at,

                    exchange_order_id=None,
                    exchange_status=None,
                    order_quantity=None,
                    executed_qty=0,
                    accounted_qty=0,
                    avg_fill_price=None,
                    signal_id=None,
                    sl_order_id=None,
                    tp_order_id=None,
                )

                db.add(pending)
                db.commit()

                print(f"🟡 PENDING CREATED: {symbol} {direction} @ {trigger_price:.4f}")

                scan_stats["pending_created"] += 1

                continue
                #create_signal() # Fall back if want to continue Market Signal

            except Exception as e:
                db.rollback()
                print(f"❌ Error {symbol}: {type(e).__name__} - {e}")
        db.commit()

        time.sleep(BATCH_SLEEP)

    # ← CHANGED: bỏ db.close() ở đây, caller dùng context manager lo

    # ============================================================
    # DEBUG DASHBOARD
    # ============================================================

    BLOCK_EMOJI = {
        "score_threshold": "📉 score_low",
        "regime_mismatch": "🌊 regime",
        "open_signal":     "🔒 open_signal",
        "duplicate":       "♻️  duplicate",
        "cooldown":        "⏳ cooldown",
        "ml_threshold":    "🤖 ml_prob",
        None:              "✅ PASSED",
    }

    print("\n===== DEBUG DASHBOARD =====")
    print(
        f"{'Symbol':<12}"
        f"{'Pattern':<22}"
        f"{'T':>3}"
        f"{'M':>4}"
        f"{'V':>5}"
        f"{'P':>6}"
        f"{'MTF':>5}"
        f"{'PEN':>5}"
        f"{'DER':>6}"
        f"{'Score':>7}"
        f"  {'Bar':<12}"
        f"  Block Reason"
    )
    print("─" * 105)

    for row in sorted(debug_rows, key=lambda x: x.get("total_score") or 0, reverse=True):
        total        = row.get("total_score")
        bar          = score_bar(total)
        reason_raw   = row.get("block_reason")
        reason_label = BLOCK_EMOJI.get(reason_raw, str(reason_raw))

        print(
            f"{str(row.get('symbol',  '')):<12}"
            f"{str(row.get('pattern', '')):<22}"
            f"{fmt(row.get('trend'),          3, decimals=0)}"
            f"{fmt(row.get('momentum'),       4, decimals=1)}"
            f"{fmt(row.get('volume'),         5, decimals=2)}"
            f"{fmt(row.get('pattern_score'),  6, decimals=2)}"
            f"{fmt(row.get('mtf'),            5, decimals=2)}"
            f"{fmt(row.get('penalty'),        5, decimals=1)}"
            f"{fmt(row.get('derivative_bias'), 6, decimals=2)}"
            f"{fmt(total,                     7, decimals=2)}"
            f"  {bar:<12}"
            f"  {reason_label}"
        )

    # ============================================================
    # SCORE DISTRIBUTION
    # 📊 PHÂN TÍCH PHÂN PHỐI ĐIỂM (PERCENTILES)
    # ============================================================

    # Trích xuất list điểm từ debug_rows
    valid_scores = [row.get("total_score") for row in debug_rows if row.get("total_score") is not None]

    if valid_scores:
        print("\n📊 SCORE DISTRIBUTION ANALYSIS:")
        print(f"Total Signals Evaluated: {len(valid_scores)}")
        print(f"Min: {min(valid_scores):.2f} | Max: {max(valid_scores):.2f} | Avg: {sum(valid_scores)/len(valid_scores):.2f}")
        #print("\n🎯 Gợi ý đặt SCORE_THRESHOLD trong DB:")
        #for p in [50, 70, 80, 90, 95]:
        #    threshold_val = np.percentile(valid_scores, p)
        #    print(f"- Nếu muốn lấy Top {100-p}% tín hiệu đẹp nhất -> Đặt SCORE_THRESHOLD = {threshold_val:.2f}")
    else:
        print("\n⚠️ Không có signal nào được tính điểm.")

    # ============================================================
    # RUNTIME CONFIG
    # ============================================================

    """print("\n===== RUNTIME FILTER CONFIG =====")
    for k, v in runtime_cfg.items():
        print(f"  {k}: {v}")
    print("=================================\n")"""

    # ============================================================
    # SCAN SUMMARY
    # ============================================================

    total_sym = scan_stats["total_symbols"]
    passed    = scan_stats["sent"]

    def pct(n, denom):
        return f"{n/denom*100:.1f}%" if denom > 0 else "0%"

    print("=" * 45)
    print(f"📊 SCAN SUMMARY [{timeframe}]")
    print("=" * 45)
    print(f"  🔍 Total symbols scanned : {total_sym}")
    print(f"  🕯️  Pattern detected       : {scan_stats['pattern_detected']} ({pct(scan_stats['pattern_detected'], total_sym)})")
    print("-" * 45)
    print("  Filtered out:")
    print(f"  📉 Score too low         : {scan_stats['score_reject']}  ({pct(scan_stats['score_reject'],        total_sym)})")
    #print(f"  🌊 Regime mismatch       : {scan_stats['regime_blocked']}  ({pct(scan_stats['regime_blocked'],      total_sym)})")
    print(f"  🔒 Has open signal       : {scan_stats['open_signal_blocked']}  ({pct(scan_stats['open_signal_blocked'], total_sym)})")
    print(f"  ♻️  Duplicate candle      : {scan_stats['duplicate_blocked']}  ({pct(scan_stats['duplicate_blocked'],  total_sym)})")
    print(f"  ⏳ Cooldown active       : {scan_stats['cooldown_blocked']}  ({pct(scan_stats['cooldown_blocked'],    total_sym)})")
    print(f"  🤖 ML prob too low       : {scan_stats['ml_blocked']}  ({pct(scan_stats['ml_blocked'],          total_sym)})")
    print(f"  🚫 HTF Block           : {scan_stats['htf_blocked']}  ({pct(scan_stats['htf_blocked'], total_sym)})")
    print(f"  💰 Funding Block       : {scan_stats['funding_blocked']}  ({pct(scan_stats['funding_blocked'], total_sym)})")
    print(f"   ✅ Pending Created     : {scan_stats['pending_created']}  ({pct(scan_stats['pending_created'], total_sym)})")
    print("-" * 45)
    #print(f"  Signal Pending           : {passed}  ({pct(passed, total_sym)})")
    print("=" * 45)

    # Warnings
    """if scan_stats["open_signal_blocked"] > 20:
        print(f"\n⚠️  WARNING: {scan_stats['open_signal_blocked']} symbols bị block vì open signal")
        print("   → Xem xét tăng tốc close lệnh cũ")

    if scan_stats["cooldown_blocked"] > passed * 3:
        print(f"\n⚠️  WARNING: Cooldown block ({scan_stats['cooldown_blocked']}) >> sent ({passed})")
        print("   → Xem xét giảm COOLDOWN_HOURS")

    if scan_stats["pattern_detected"] > 0 and scan_stats["ml_blocked"] > scan_stats["pattern_detected"] * 0.5:
        print(f"\n⚠️  WARNING: ML block {scan_stats['ml_blocked']}/{scan_stats['pattern_detected']} patterns")
        print("   → Model filter quá aggressive, kiểm tra AI_THRESHOLD")"""

   
    return scan_stats