"""
BTC Market Overview
===================
Tính regime BTC theo nhiều timeframe.
Cache 5 phút.
"""

import time
from typing import Dict, Optional

from app.services.binance_service import get_klines_closed, get_binance_server_time
from app.services.indicator_service import add_indicators_advanced, detect_regime_advanced


_cache: Optional[Dict] = None
_cache_ts: float = 0
CACHE_TTL = 300  # 5 phút


def get_btc_overview() -> Dict:
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < CACHE_TTL:
        return _cache

    server_now = get_binance_server_time()
    timeframes = ["15m", "1h", "4h", "1d"]
    result = {"timeframes": {}, "price": None, "summary": "UNKNOWN"}

    for tf in timeframes:
        try:
            df = get_klines_closed("BTCUSDT", interval=tf, limit=250, server_now=server_now)
            if df is None or df.empty or len(df) < 50:
                result["timeframes"][tf] = {"regime": "UNKNOWN", "rsi": None, "trend": "UNKNOWN"}
                continue

            df = add_indicators_advanced(df)
            last = df.iloc[-1]

            regime = detect_regime_advanced(df, method="hybrid", lookback=10, threshold=0.002)

            rsi = float(last.get("rsi") or 0)
            ema50 = float(last.get("ema50") or 0)
            ema200 = float(last.get("ema200") or 0)
            close = float(last.get("close") or 0)

            if ema50 > ema200 * 1.002:
                trend = "UP"
            elif ema50 < ema200 * 0.998:
                trend = "DOWN"
            else:
                trend = "FLAT"

            result["timeframes"][tf] = {
                "regime": regime,
                "rsi": round(rsi, 1),
                "trend": trend,
            }

            if tf == "1h" and close > 0:
                result["price"] = round(close, 2)

        except Exception as e:
            result["timeframes"][tf] = {"regime": "ERROR", "rsi": None, "trend": "ERROR"}

    # Summary: majority vote
    regimes = [v["regime"] for v in result["timeframes"].values() if v["regime"] in ("BULL", "BEAR", "SIDEWAYS")]
    if regimes:
        from collections import Counter
        counts = Counter(regimes)
        most_common = counts.most_common(1)[0]
        if most_common[1] >= 3:
            result["summary"] = most_common[0]
        elif counts.get("BULL", 0) >= 2 and counts.get("BEAR", 0) == 0:
            result["summary"] = "BULL"
        elif counts.get("BEAR", 0) >= 2 and counts.get("BULL", 0) == 0:
            result["summary"] = "BEAR"
        else:
            result["summary"] = "SIDEWAYS"

    from app.core.time_utils import utc_now
    result["updated_at"] = utc_now().isoformat()

    _cache = result
    _cache_ts = now

    return result