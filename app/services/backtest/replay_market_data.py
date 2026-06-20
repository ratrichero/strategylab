"""
Backtest Replay — Market Data Fetcher
=======================================
Fetch Binance Futures Mark Price Klines 1m.

Supports:
- Single fetch
- Batch fetch with dedup + semaphore
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Tuple, List
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from app.core.time_utils import ensure_utc


HORIZON_MAP = {
    "15m": timedelta(hours=24),
    "1h": timedelta(hours=72),
    "4h": timedelta(days=7),
}

# Batch fetch config
MAX_CONCURRENT_FETCHES = 3
FETCH_DELAY_BETWEEN_SYMBOLS = 0.3


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
    Single symbol, single range.
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

        time.sleep(FETCH_DELAY_BETWEEN_SYMBOLS)

    if not all_rows:
        return None

    return _parse_klines(all_rows)


# ============================================================
# BATCH FETCH
# ============================================================

def batch_fetch_mark_klines(
    fetch_requests: List[Dict],
    max_concurrent: int = MAX_CONCURRENT_FETCHES,
    delay_between: float = FETCH_DELAY_BETWEEN_SYMBOLS,
    live_active: bool = False,
) -> Dict[str, pd.DataFrame]:
    """
    Batch fetch mark price klines với:
    - dedup theo (symbol, start_ms, end_ms)
    - semaphore giới hạn concurrent
    - throttle giữa các fetch

    Args:
        fetch_requests: list of {"symbol": str, "start_time": datetime, "end_time": datetime}
        max_concurrent: max concurrent fetches
        delay_between: delay giữa mỗi fetch
        live_active: nếu True, chạy chậm hơn

    Returns:
        Dict[cache_key, DataFrame]
    """
    # Dedup
    unique_requests = {}
    for req in fetch_requests:
        key = _cache_key(req["symbol"], req["start_time"], req["end_time"])
        if key not in unique_requests:
            unique_requests[key] = req

    total = len(unique_requests)
    deduped = len(fetch_requests) - total

    if live_active:
        effective_concurrent = max(1, max_concurrent - 1)
        effective_delay = max(delay_between, 1.0)
    else:
        effective_concurrent = max_concurrent
        effective_delay = delay_between

    print(
        f"[BACKTEST FETCH] Batch: {total} unique / {len(fetch_requests)} total "
        f"(dedup saved {deduped}) | concurrent={effective_concurrent} "
        f"| delay={effective_delay}s | live_active={live_active}"
    )

    results = {}
    semaphore = threading.Semaphore(effective_concurrent)
    lock = threading.Lock()
    completed = [0]

    def _fetch_one(key: str, req: dict):
        semaphore.acquire()
        try:
            df = fetch_mark_klines_1m(
                symbol=req["symbol"],
                start_time=req["start_time"],
                end_time=req["end_time"],
            )
            with lock:
                if df is not None and not df.empty:
                    results[key] = df
                completed[0] += 1

                if completed[0] % 10 == 0 or completed[0] == total:
                    print(f"[BACKTEST FETCH] Progress: {completed[0]}/{total}")

            time.sleep(effective_delay)
        finally:
            semaphore.release()

    with ThreadPoolExecutor(max_workers=effective_concurrent) as executor:
        futures = []
        for key, req in unique_requests.items():
            futures.append(executor.submit(_fetch_one, key, req))

        for f in as_completed(futures):
            try:
                f.result()
            except Exception as e:
                print(f"[BACKTEST FETCH] Thread error: {e}")

    print(
        f"[BACKTEST FETCH] Done: {len(results)}/{total} fetched OK"
    )

    return results


def _cache_key(symbol: str, start_time: datetime, end_time: datetime) -> str:
    s = ensure_utc(start_time)
    e = ensure_utc(end_time)
    return f"{symbol}_{int(s.timestamp())}_{int(e.timestamp())}"


def get_cache_key(symbol: str, start_time: datetime, end_time: datetime) -> str:
    """Public alias for replay_service to build keys."""
    return _cache_key(symbol, start_time, end_time)


# ============================================================
# HELPERS
# ============================================================

def _parse_klines(raw_rows: list) -> pd.DataFrame:
    df = pd.DataFrame(raw_rows, columns=[
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