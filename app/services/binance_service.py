import requests
import pandas as pd
import time
from app.core.config import BINANCE_BASE

# ✅ GLOBAL SESSION (reuse connection)
_session = requests.Session()

# ✅ OPTIONAL: Retry adapter (production safe)
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

retry_strategy = Retry(
    total=3,
    backoff_factor=1,
    status_forcelist=[429, 500, 502, 503, 504],
)

adapter = HTTPAdapter(max_retries=retry_strategy)
_session.mount("https://", adapter)
_session.mount("http://", adapter)

# ✅ CACHE
_valid_symbols_cache = None
_valid_symbols_ts = 0
VALID_SYMBOLS_TTL = 3600  # 1 giờ


# ─────────────────────────────────────────────
# PRICE MAP
# ─────────────────────────────────────────────
def get_all_prices():

    url = f"{BINANCE_BASE}/fapi/v1/ticker/price"

    try:
        response = _session.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[PRICE ERROR] {e}")
        return {}

    if not isinstance(data, list):
        return {}

    return {item["symbol"]: float(item["price"]) for item in data}


# ─────────────────────────────────────────────
# VALID SYMBOLS (CACHED)
# ─────────────────────────────────────────────
def get_valid_symbols():

    global _valid_symbols_cache, _valid_symbols_ts

    now = time.time()

    if _valid_symbols_cache and (now - _valid_symbols_ts < VALID_SYMBOLS_TTL):
        return _valid_symbols_cache

    url = f"{BINANCE_BASE}/fapi/v1/exchangeInfo"

    try:
        response = _session.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        print(f"[EXCHANGE INFO ERROR] {e}")

        if _valid_symbols_cache:
            return _valid_symbols_cache

        return []

    symbols = []

    for s in data.get("symbols", []):

        if (
            s.get("contractType") == "PERPETUAL"
            and s.get("quoteAsset") == "USDT"
            and s.get("status") == "TRADING"
            and s.get("underlyingType") == "COIN"
        ):
            base = s.get("baseAsset", "")

            if not base.isalpha() or len(base) > 12:
                continue

            symbols.append(s["symbol"])

    _valid_symbols_cache = symbols
    _valid_symbols_ts = now

    return symbols


# ─────────────────────────────────────────────
# TOP SYMBOLS
# ─────────────────────────────────────────────
def get_top_symbols(limit=30):

    url = f"{BINANCE_BASE}/fapi/v1/ticker/24hr"

    try:
        response = _session.get(url, timeout=10)
        response.raise_for_status()
        tickers = response.json()
    except Exception as e:
        print(f"[TICKER ERROR] {e}")
        return []

    valid = set(get_valid_symbols())

    usdt_pairs = [
        t for t in tickers
        if t["symbol"] in valid
    ]

    usdt_pairs = sorted(
        usdt_pairs,
        key=lambda x: float(x["quoteVolume"]),
        reverse=True
    )

    return [x["symbol"] for x in usdt_pairs[:limit]]


# ─────────────────────────────────────────────
# KLINES
# ─────────────────────────────────────────────
def get_klines(symbol, limit=200, interval=None, start_time=None, end_time=None):

    from app.services.config_service import get_runtime_config

    if interval is None:
        runtime_cfg = get_runtime_config()
        interval = runtime_cfg["TIMEFRAME"]

    params = {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    }

    if start_time:
        params["startTime"] = int(start_time.timestamp() * 1000)

    if end_time:
        params["endTime"] = int(end_time.timestamp() * 1000)

    url = f"{BINANCE_BASE}/fapi/v1/klines"

    for attempt in range(3):
        try:
            response = _session.get(url, params=params, timeout=(5, 15))
            response.raise_for_status()
            data = response.json()
            break
        except Exception as e:
            print(f"[KLINES RETRY {attempt+1}] {symbol} error: {e}")
            time.sleep(1)
    else:
        print(f"[KLINES FAILED] {symbol}")
        return pd.DataFrame()

    if not isinstance(data, list):
        return pd.DataFrame()

    df = pd.DataFrame(data, columns=[
        "time", "open", "high", "low", "close", "volume",
        "_", "_", "_", "_", "_", "_"
    ])

    if df.empty:
        return df

    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df["close"] = df["close"].astype(float)
    df["volume"] = df["volume"].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")

    return df.sort_values("time").reset_index(drop=True)


# ─────────────────────────────────────────────
# SERVER TIME
# ─────────────────────────────────────────────
def get_binance_server_time():

    url = f"{BINANCE_BASE}/fapi/v1/time"

    response = _session.get(url, timeout=5)
    response.raise_for_status()

    r = response.json()

    return pd.to_datetime(r["serverTime"], unit="ms")


# ─────────────────────────────────────────────
# CLOSED KLINES
# ─────────────────────────────────────────────
def get_candle_duration(interval: str):

    from datetime import timedelta

    mapping = {
        "15m": timedelta(minutes=15),
        "1h": timedelta(hours=1),
        "4h": timedelta(hours=4),
        "1d": timedelta(days=1)
    }

    return mapping[interval]


def get_klines_closed(symbol, limit=300, interval=None,
                      start_time=None, end_time=None,
                      server_now=None):

    df = get_klines(
        symbol=symbol,
        limit=limit,
        interval=interval,
        start_time=start_time,
        end_time=end_time
    )

    if df.empty:
        return df

    if server_now is None:
        server_now = get_binance_server_time()

    duration = get_candle_duration(interval)

    df = df[df["time"] + duration <= server_now]

    return df