#btc_context_cache

from datetime import datetime, timezone
from copy import deepcopy

import pandas as pd

from app.services.binance_service import get_klines_closed
from app.services.indicator_service import add_indicators_advanced


# ─────────────────────────────────────────────
# GLOBAL CACHE
# ─────────────────────────────────────────────
_btc_snapshot_cache = None
_btc_snapshot_hour = None


# ─────────────────────────────────────────────
# HELPER
# ─────────────────────────────────────────────
def _current_hour_utc():
    now = datetime.utcnow()
    return now.replace(minute=0, second=0, microsecond=0)


def _classify_trend(ema50, ema200):
    if ema200 == 0:
        return "UNKNOWN"
    if ema50 > ema200 * 1.002:
        return "BULL"
    elif ema50 < ema200 * 0.998:
        return "BEAR"
    return "SIDEWAYS"


def _build_hourly_structure_snapshot():
    """
    Build BTC macro snapshot (1D + 4H + 1H)
    WITHOUT realtime price overlay.
    """

    snapshot_hour = _current_hour_utc()

    # ── Fetch data ──────────────────────────
    df_1d = get_klines_closed("BTCUSDT", interval="1d", limit=200)
    df_4h = get_klines_closed("BTCUSDT", interval="4h", limit=250)
    df_1h = get_klines_closed("BTCUSDT", interval="1h", limit=150)

    if df_1d is None or df_4h is None or df_1h is None:
        return None

    df_1d = add_indicators_advanced(df_1d)
    df_4h = add_indicators_advanced(df_4h)
    df_1h = add_indicators_advanced(df_1h)

    last_1d = df_1d.iloc[-1]
    last_4h = df_4h.iloc[-1]
    last_1h = df_1h.iloc[-1]

    # ── Macro 1D ────────────────────────────
    ema50_1d = float(last_1d.get("ema50") or 0)
    ema200_1d = float(last_1d.get("ema200") or 0)
    close_1d = float(last_1d.get("close") or 0)

    macro_trend = _classify_trend(ema50_1d, ema200_1d)

    # ── Structure 4H ────────────────────────
    ema50_4h = float(last_4h.get("ema50") or 0)
    ema200_4h = float(last_4h.get("ema200") or 0)
    close_4h = float(last_4h.get("close") or 0)

    structure_trend = _classify_trend(ema50_4h, ema200_4h)

    atr_4h = float(last_4h.get("atr") or 0)
    atr_pct_4h = round(atr_4h / close_4h, 5) if close_4h > 0 else None

    # ── Tactical 1H ─────────────────────────
    rsi_1h = float(last_1h.get("rsi") or 0) or None
    atr_1h = float(last_1h.get("atr") or 0)
    close_1h = float(last_1h.get("close") or 0)

    atr_pct_1h = round(atr_1h / close_1h, 5) if close_1h > 0 else None

    # ── Snapshot structure (no realtime price yet) ─────────
    return {
        "snapshot_at_hour": snapshot_hour.strftime("%Y-%m-%dT%H:%M:%SZ"),

        "macro_1d": {
            "trend": macro_trend,
            "ema50_vs_ema200_pct": round((ema50_1d - ema200_1d) / ema200_1d, 5)
            if ema200_1d else None,
            "distance_from_ema200_pct": round((close_1d - ema200_1d) / ema200_1d, 5)
            if ema200_1d else None,
        },

        "structure_4h": {
            "trend": structure_trend,
            "atr_pct": atr_pct_4h,
        },

        "tactical_1h": {
            "rsi": round(rsi_1h, 2) if rsi_1h else None,
            "atr_pct": atr_pct_1h,
        },
    }


# ─────────────────────────────────────────────
# PUBLIC FUNCTION
# ─────────────────────────────────────────────
def get_or_build_hourly_snapshot():
    global _btc_snapshot_cache, _btc_snapshot_hour

    current_hour = _current_hour_utc()

    if _btc_snapshot_hour != current_hour:
        snapshot = _build_hourly_structure_snapshot()
        if snapshot:
            _btc_snapshot_cache = snapshot
            _btc_snapshot_hour = current_hour

    return _btc_snapshot_cache


def build_event_context(snapshot_structure: dict, btc_price_now: float):
    """
    Overlay realtime BTC price on top of hourly structure snapshot.
    """

    if not snapshot_structure:
        return None

    snapshot = deepcopy(snapshot_structure)

    btc_price_at_hour_start = None

    # Ta có thể dùng close_1h của snapshot hour làm reference
    # hoặc chỉ lấy btc_price_now làm reference
    btc_price_at_hour_start = btc_price_now  # đơn giản nhất

    snapshot["btc_price"] = btc_price_now
    snapshot["btc_price_at_hour_start"] = btc_price_at_hour_start
    snapshot["btc_hourly_return_since_snapshot_pct"] = 0.0  # placeholder

    return snapshot