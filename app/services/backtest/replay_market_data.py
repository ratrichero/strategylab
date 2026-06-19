"""
Backtest Replay — Market Data Fetcher
=======================================
Fetch Binance Futures Mark Price Klines 1m.
"""

import time
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from app.core.time_utils import ensure_utc


HORIZON_MAP = {
    "15m": timedelta(hours=24),
    "1h": timedelta(hours=72),
    "4h": timedelta(days=7),
}


def get_horizon(timeframe: str) -> timedelta:
    return HORIZON_MAP.get(timeframe, timedelta(hours=24))


def fetch_mark_klines_1m(
    symbol: str,
    start_time: datetime,
    end_time: datetime,
    max_retries: int = 3,
) -> Optional[pd.DataFrame]:
    """
    Fetch Binance Futures Mark Price Klines 1m.
    Endpoint: /fapi/v1/markPriceKlines
    """
    from app.core.config import BINANCE_BASE
    import requests

    start_time = ensure_utc(start_time)
    end_time = ensure_utc(end_time)

    start_ms = int(start_time.timestamp() * 1000)
    end_ms = int(end_time.timestamp() * 1000)

    all_rows = []
    current_start = start_ms

    session = requests.Session()

    while current_start < end_ms:
        params = {
            "symbol": symbol,
            "interval": "1m",
            "startTime": current_start,
            "endTime": end_ms,
            "limit": 1500,
        }

        for attempt in range(max_retries):
            try:
                resp = session.get(
                    f"{BINANCE_BASE}/fapi/v1/markPriceKlines",
                    params=params,
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2)
                else:
                    print(f"[BACKTEST] Mark klines fetch failed {symbol}: {e}")
                    return None

        if not data or not isinstance(data, list):
            break

        all_rows.extend(data)

        last_time = int(data[-1][0])
        if last_time <= current_start:
            break

        current_start = last_time + 60_000

        if len(data) < 1500:
            break

        time.sleep(0.3)

    if not all_rows:
        return None

    df = pd.DataFrame(all_rows, columns=[
        "time", "open", "high", "low", "close", "volume",
        "_1", "_2", "_3", "_4", "_5", "_6"
    ])

    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)

    df = df[["time", "open", "high", "low", "close"]].drop_duplicates(subset="time")
    df = df.sort_values("time").reset_index(drop=True)

    return df