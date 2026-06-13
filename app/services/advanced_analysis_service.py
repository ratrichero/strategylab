from app.services.binance_service import get_klines_closed, get_all_prices
from app.services.indicator_service import add_indicators_advanced, detect_regime_advanced
from app.services.derivatives_service import compute_derivative_bias, get_derivative_data
from app.services.block_service import check_htf_atr_block, check_funding_block
from app.services.signal_service import calculate_score
from app.services.config_service import get_runtime_config


def analyze_advanced(symbol: str, timeframe: str):

    runtime_cfg = get_runtime_config()

    lookback = 400
    df = get_klines_closed(symbol, interval=timeframe, limit=lookback)

    if df is None or df.empty:
        return {"error": "No data"}

    df = add_indicators_advanced(df)
    regime = detect_regime_advanced(df)

    last = df.iloc[-1]
    atr = float(last["atr"])
    ema200 = float(last["ema200"])

    price_map = get_all_prices()
    current_price = float(price_map.get(symbol, last["close"]))

    atr_pct = round(atr / current_price * 100, 2)
    ema_dist_pct = round((current_price - ema200) / ema200 * 100, 2)

    sl_pct = runtime_cfg["RISK_CONFIG"][timeframe]["sl_mult"]
    tp_pct = runtime_cfg["RISK_CONFIG"][timeframe]["tp_mult"]

    results = {}

    for direction, fake_pattern in [
        ("LONG", "Bullish Engulfing"),
        ("SHORT", "Bearish Engulfing"),
    ]:

        score, _, components = calculate_score(
            df=df,
            pattern=fake_pattern,
            cfg=runtime_cfg,
            symbol=symbol,
            timeframe=timeframe,
            regime=regime
        )

        derivative_bias = compute_derivative_bias(
            symbol=symbol,
            timeframe=timeframe,
            direction=direction
        )

        htf_block, _ = check_htf_atr_block(
            df=df,
            direction=direction,
            timeframe=timeframe
        )

        funding_block, _ = check_funding_block(
            symbol=symbol,
            direction=direction,
            timeframe=timeframe
        )

        # ✅ Entry = current price (analysis mode)
        entry = current_price

        if direction == "LONG":
            sl = entry * (1 - sl_pct)
            tp = entry * (1 + tp_pct)
        else:
            sl = entry * (1 + sl_pct)
            tp = entry * (1 - tp_pct)

        # ✅ Confidence score
        confidence = round(
            score / 10 * 0.7 +
            abs(derivative_bias) * 0.3,
            2
        )

        results[direction] = {
            "score": score,
            "derivative_bias": derivative_bias,
            "htf_block": htf_block,
            "funding_block": funding_block,
            "entry": round(entry, 4),
            "sl": round(sl, 4),
            "tp": round(tp, 4),
            "confidence": confidence
        }
        derivative_data = get_derivative_data(symbol, timeframe)
        funding_rate = derivative_data["funding_rate"]
        oi_change = derivative_data["oi_change_pct"]
        ls_ratio = derivative_data["long_short_ratio"]

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "regime": regime,
        "atr_pct": atr_pct,
        "ema_dist_pct": ema_dist_pct,
        "funding_rate": funding_rate,
        "oi_change": oi_change,
        "ls_ratio": ls_ratio,
        "long": results["LONG"],
        "short": results["SHORT"],
    }

def multi_tf_summary(symbol):

    timeframes = ["15m", "1h", "4h"]
    summary = {}

    for tf in timeframes:
        result = analyze_advanced(symbol, tf)
        if "error" in result:
            continue

        long_score = result["long"]["score"]
        short_score = result["short"]["score"]

        if long_score > short_score:
            summary[tf] = "🟢"
        elif short_score > long_score:
            summary[tf] = "🔴"
        else:
            summary[tf] = "⚪"

    return summary

from app.services.config_service import get_runtime_config
from app.services.signal_service import calculate_score
from app.services.indicator_service import add_indicators_advanced, detect_regime_advanced
from app.services.binance_service import get_klines_closed


def analyze_quick(symbol: str, timeframe: str):

    runtime_cfg = get_runtime_config()

    df = get_klines_closed(symbol, interval=timeframe, limit=200)

    if df is None or df.empty:
        return None, None

    df = add_indicators_advanced(df)
    regime = detect_regime_advanced(df)

    score_long, _, _ = calculate_score(
        df, "Bullish Engulfing", runtime_cfg, symbol, timeframe, regime=regime
    )

    score_short, _, _ = calculate_score(
        df, "Bearish Engulfing", runtime_cfg, symbol, timeframe, regime=regime
    )

    return score_long, score_short