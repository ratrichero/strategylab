"""
Strategy Debug Scanner
======================
Chạy tất cả strategies, ghi score ra CSV.
Không tạo pending, không tạo signal, không ghi DB.
"""

import os
import csv
import time
from datetime import datetime, timezone

from app.services.binance_service import (
    get_top_symbols, get_klines_closed, get_binance_server_time
)
from app.services.indicator_service import (
    add_indicators_advanced, detect_regime_advanced
)
from app.services.config_service import get_runtime_config
from app.services.mtf_service import MTFCalculator
from app.services.derivatives_service import compute_derivative_bias
from app.services.block_service import HTF_BLOCK_CONFIG
from app.strategies.registry import _REGISTRY
from app.core.time_utils import utc_now, vn_now_str


CSV_DIR  = "debug_logs"
CSV_FILE = os.path.join(CSV_DIR, "strategy_scores.csv")

CSV_HEADERS = [
    "scan_time", "symbol", "timeframe", "strategy", "pattern",
    "direction", "regime",
    "trend_score", "momentum_score", "volume_score",
    "pattern_score", "mtf_score", "penalty_norm",
    "rule_score_raw", "technical_score", "derivative_bias",
    "final_score",
    "rsi", "atr_ratio", "volume_ratio",
    "candle_time",
]


def run_debug_scan():
    """
    Scan tất cả strategy, ghi CSV.
    Không đụng DB.
    """
    cfg = get_runtime_config()
    timeframes = ["15m", "1h", "4h"]

    all_strategies = list(_REGISTRY.values())
    symbols = get_top_symbols(cfg.get("TOP_LIMIT", 200))
    server_now = get_binance_server_time()
    scan_time = vn_now_str()

    results = []

    for tf in timeframes:
        mtf_map = MTFCalculator.get_timeframe_map(tf)
        trend_tf = mtf_map["trend"]
        context_tf = mtf_map["context"]
        trend_cache = {}
        context_cache = {}

        for symbol in symbols:
            try:
                lookback = max(HTF_BLOCK_CONFIG.get(tf, {}).get("lookback", 200), 50)
                df = get_klines_closed(
                    symbol, interval=tf, limit=lookback,
                    server_now=server_now
                )
                if df is None or df.empty or len(df) < 3:
                    continue

                df = add_indicators_advanced(df)
                last = df.iloc[-1]

                # MTF
                trend_df = None
                context_df = None

                if cfg.get("MTF_ENABLED"):
                    if trend_tf and symbol not in trend_cache:
                        raw = get_klines_closed(
                            symbol, interval=trend_tf, limit=250,
                            server_now=server_now
                        )
                        trend_cache[symbol] = (
                            add_indicators_advanced(raw)
                            if raw is not None and len(raw) >= 50
                            else None
                        )
                    trend_df = trend_cache.get(symbol)

                    if context_tf and symbol not in context_cache:
                        raw = get_klines_closed(
                            symbol, interval=context_tf, limit=250,
                            server_now=server_now
                        )
                        context_cache[symbol] = (
                            add_indicators_advanced(raw)
                            if raw is not None and len(raw) >= 50
                            else None
                        )
                    context_df = context_cache.get(symbol)

                regime = detect_regime_advanced(
                    df, method="hybrid", lookback=10, threshold=0.002
                )

                # Chạy TẤT CẢ strategies
                for strat in all_strategies:
                    try:
                        sig = strat.detect(df, tf)
                        if not sig or not sig.valid:
                            continue

                        sig = strat.score(
                            df=df, signal=sig, timeframe=tf,
                            trend_df=trend_df, context_df=context_df,
                            regime=regime, cfg=cfg
                        )

                        deriv_cfg = cfg.get("DERIVATIVE_CONFIG", {})
                        bias_scale_map = deriv_cfg.get("bias_scale", {
                            "15m": 0.6, "1h": 0.8, "4h": 1.0
                        })
                        raw_bias = compute_derivative_bias(
                            symbol=symbol, timeframe=tf,
                            direction=sig.direction
                        )
                        derivative_bias = raw_bias * bias_scale_map.get(tf, 0.6)
                        final_score = round(
                            max(0, min(10, sig.final_score + derivative_bias)), 2
                        )

                        comp = sig.components or {}

                        vol_ma = last.get("vol_ma")
                        vol_ratio = (
                            round(float(last["volume"]) / float(vol_ma), 2)
                            if vol_ma and float(vol_ma) > 0 else 0
                        )

                        close_val = float(last.get("close") or 1)
                        atr_val = float(last.get("atr") or 0)

                        results.append({
                            "scan_time":      scan_time,
                            "symbol":         symbol,
                            "timeframe":      tf,
                            "strategy":       strat.STRATEGY_NAME,
                            "pattern":        sig.pattern,
                            "direction":      sig.direction,
                            "regime":         regime,
                            "trend_score":    round(float(comp.get("trend_score", 0)), 3),
                            "momentum_score": round(float(comp.get("momentum_score", 0)), 3),
                            "volume_score":   round(float(comp.get("volume_score", 0)), 3),
                            "pattern_score":  round(float(comp.get("pattern_score", 0)), 3),
                            "mtf_score":      round(float(comp.get("mtf_score", 0)), 3),
                            "penalty_norm":   round(float(comp.get("penalty_norm", 0)), 3),
                            "rule_score_raw": round(float(comp.get("rule_score_raw", 0)), 3),
                            "technical_score":round(float(sig.final_score), 2),
                            "derivative_bias":round(float(derivative_bias), 3),
                            "final_score":    final_score,
                            "rsi":            round(float(last.get("rsi") or 0), 1),
                            "atr_ratio":      round(atr_val / close_val, 5) if close_val > 0 else 0,
                            "volume_ratio":   vol_ratio,
                            "candle_time":    str(last.get("time")),
                        })

                    except Exception:
                        continue

            except Exception:
                continue

        time.sleep(1)

    # Ghi CSV append
    if results:
        _append_csv(results)
        print(
            f"[DEBUG SCAN] {scan_time} | "
            f"{len(results)} signals → {CSV_FILE}"
        )
    else:
        print(f"[DEBUG SCAN] {scan_time} | No signals detected")


def _append_csv(rows):
    """Append rows vào CSV. Tạo file + header nếu chưa có."""
    os.makedirs(CSV_DIR, exist_ok=True)

    file_exists = os.path.exists(CSV_FILE)

    with open(CSV_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        if not file_exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def get_csv_path():
    return CSV_FILE