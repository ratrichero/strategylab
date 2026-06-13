import requests
import time
from app.core.config import BINANCE_BASE


# ============================================================
# SIMPLE MEMORY CACHE
# ============================================================

DERIVATIVE_CACHE = {}
CACHE_TTL = 300  # 5 phút


def _get_cached(symbol):
    item = DERIVATIVE_CACHE.get(symbol)
    if not item:
        return None

    data, ts = item

    if time.time() - ts > CACHE_TTL:
        del DERIVATIVE_CACHE[symbol]  # cleanup expired
        return None

    return data


def _set_cache(symbol, data):
    DERIVATIVE_CACHE[symbol] = (data, time.time())


# ============================================================
# FETCH DERIVATIVE DATA (FUTURES)
# ============================================================

def get_derivative_data(symbol, timeframe):
    """
    Return:
    {
        funding_rate: float,
        oi_change_pct: float,
        long_short_ratio: float
    }
    """

    cached = _get_cached(symbol)
    if cached:
        return cached

    try:
        period_map = {
            "15m": "15m",
            "1h": "1h",
            "4h": "4h"
        }

        period = period_map.get(timeframe, "15m")

        # ================= FUNDING =================
        funding_url = f"{BINANCE_BASE}/fapi/v1/fundingRate"
        funding_resp = requests.get(
            funding_url,
            params={"symbol": symbol, "limit": 1},
            timeout=5
        )
        funding_resp.raise_for_status()
        funding_data = funding_resp.json()

        funding_rate = (
            float(funding_data[0]["fundingRate"])
            if isinstance(funding_data, list) and funding_data
            else 0.0
        )

        # ================= OPEN INTEREST =================
        oi_url = f"{BINANCE_BASE}/futures/data/openInterestHist"
        oi_resp = requests.get(
            oi_url,
            params={
                "symbol": symbol,
                "period": period,
                "limit": 2
            },
            timeout=5
        )
        oi_resp.raise_for_status()
        oi_data = oi_resp.json()

        if isinstance(oi_data, list) and len(oi_data) >= 2:
            oi_prev = float(oi_data[-2]["sumOpenInterest"])
            oi_last = float(oi_data[-1]["sumOpenInterest"])

            oi_change_pct = (
                (oi_last - oi_prev) / oi_prev * 100
                if oi_prev > 0 else 0.0
            )
        else:
            oi_change_pct = 0.0

        # ================= LONG/SHORT RATIO =================
        ls_url = f"{BINANCE_BASE}/futures/data/globalLongShortAccountRatio"
        ls_resp = requests.get(
            ls_url,
            params={
                "symbol": symbol,
                "period": period,
                "limit": 1
            },
            timeout=5
        )
        ls_resp.raise_for_status()
        ls_data = ls_resp.json()

        long_short_ratio = (
            float(ls_data[0]["longShortRatio"])
            if isinstance(ls_data, list) and ls_data
            else 1.0
        )

        # Clamp extreme values
        long_short_ratio = max(0.3, min(3.0, long_short_ratio))

        result = {
            "funding_rate": funding_rate,
            "oi_change_pct": oi_change_pct,
            "long_short_ratio": long_short_ratio
        }

        _set_cache(symbol, result)

        return result

    except Exception as e:
        print(f"[DERIVATIVE ERROR] {symbol}: {e}")

        return {
            "funding_rate": 0.0,
            "oi_change_pct": 0.0,
            "long_short_ratio": 1.0
        }


# ============================================================
# COMPUTE DERIVATIVE BIAS
# ============================================================

def compute_derivative_bias(symbol, timeframe, direction):
    """
    Return raw_bias ∈ [-1, 1]
    Outer layer will multiply by bias_scale
    """

    data = get_derivative_data(symbol, timeframe)

    funding = float(data.get("funding_rate", 0))
    oi_change = float(data.get("oi_change_pct", 0))
    ls_ratio = float(data.get("long_short_ratio", 1))

    positive = 0.0
    negative = 0.0

    # ================= LONG =================
    if direction == "LONG":

        # Funding
        if funding < -0.01:
            positive += min(abs(funding) / 0.05, 1) * 0.4
        if funding > 0.03:
            negative += min(funding / 0.08, 1) * 0.5

        # OI change
        if oi_change > 1:
            positive += min(oi_change / 5, 1) * 0.4
        if oi_change < -2:
            negative += 0.3

        # Long/Short ratio
        if ls_ratio < 0.9:
            positive += min((0.9 - ls_ratio) / 0.3, 1) * 0.3
        if ls_ratio > 1.4:
            negative += min((ls_ratio - 1.4) / 0.6, 1) * 0.4

    # ================= SHORT =================
    elif direction == "SHORT":

        if funding > 0.01:
            positive += min(funding / 0.05, 1) * 0.4
        if funding < -0.03:
            negative += min(abs(funding) / 0.08, 1) * 0.5

        if oi_change > 1:
            positive += min(oi_change / 5, 1) * 0.4
        if oi_change < -2:
            negative += 0.3

        if ls_ratio > 1.1:
            positive += min((ls_ratio - 1.1) / 0.5, 1) * 0.3
        if ls_ratio < 0.7:
            negative += min((0.7 - ls_ratio) / 0.3, 1) * 0.4

    raw_bias = positive - negative

    # Clamp tuyệt đối
    raw_bias = max(-1.0, min(1.0, raw_bias))

    return round(raw_bias, 4)