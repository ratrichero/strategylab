import numpy as np
from typing import Tuple
import pandas as pd

# ============================================================
# HTF ATR BLOCK CONFIG (Stable Version)
# ============================================================
from app.services.derivatives_service import get_derivative_data
HTF_BLOCK_CONFIG = {
    "15m": {
        "lookback": 400,      # ~4 ngày
        "soft_extension": 3.0,
        "hard_extension": 4.5,
        "percentile_threshold": 85
    },
    "1h": {
        "lookback": 300,      # ~16 ngày
        "soft_extension": 4.0,
        "hard_extension": 6.0,
        "percentile_threshold": 85
    },
    "4h": {
        "lookback": 200,      # ~33 ngày
        "soft_extension": 4.5,
        "hard_extension": 7.0,
        "percentile_threshold": 80
    }
}


# ============================================================
# ✅ HTF ATR BLOCK (Stable – No Overfit)
# ============================================================

def check_htf_atr_block(
    df: pd.DataFrame,
    direction: str,
    timeframe: str
) -> Tuple[bool, str]:
    """
    Block khi:
    1. Hard extension (>= hard_extension)
    OR
    2. Soft extension + High ATR% percentile
    """

    cfg = HTF_BLOCK_CONFIG.get(timeframe)
    lookback = cfg["lookback"]
    
    if not cfg:
        return False, "NO_CONFIG"

    if df is None or len(df) < 100:
        return False, "NOT_ENOUGH_DATA"

    last = df.iloc[-1]

    close = float(last.get("close", 0))
    ema200 = float(last.get("ema200", 0))
    atr = float(last.get("atr", 0))

    if close == 0 or ema200 == 0 or atr == 0:
        return False, "INVALID_DATA"

    # ================= EXTENSION =================

    extension_atr = (close - ema200) / atr

    # Adjust theo direction
    if direction == "LONG":
        ext = extension_atr
    else:
        ext = -extension_atr

    # ================= HARD BLOCK =================

    if ext >= cfg["hard_extension"]:
        return True, f"HARD_EXT_{round(ext,2)}ATR"

    # ================= ATR% Percentile =================

    atr_pct_series = (df["atr"] / df["close"]).dropna().values

    if len(atr_pct_series) < 100:
        return False, "NOT_ENOUGH_ATR_DATA"

    current_atr_pct = atr / close

    percentile = (
        np.sum(atr_pct_series < current_atr_pct)
        / len(atr_pct_series)
        * 100
    )

    # ================= SOFT BLOCK =================

    if (
        ext >= cfg["soft_extension"]
        and percentile >= cfg["percentile_threshold"]
    ):
        return True, f"SOFT_EXT_{round(ext,2)}ATR_P{round(percentile,1)}"

    return False, "SAFE"


# ============================================================
# ✅ FUNDING EXTREME BLOCK (Stable)
# ============================================================

FUNDING_BLOCK_CONFIG = {
    "enabled": True,
    "extreme_negative": -0.2,
    "extreme_positive": 0.2
}


def check_funding_block(
    symbol: str,
    direction: str,
    timeframe: str
):
    """
    Block khi funding extreme.
    Dùng get_derivative_data để tránh double API call.
    """

    data = get_derivative_data(symbol, timeframe)

    funding = float(data.get("funding_rate", 0))

    # Không SHORT khi funding cực âm
    if direction == "SHORT" and funding <= -0.2:
        return True, f"FUNDING_NEG_{funding}"

    # Không LONG khi funding cực dương
    if direction == "LONG" and funding >= 0.2:
        return True, f"FUNDING_POS_{funding}"

    return False, "SAFE"