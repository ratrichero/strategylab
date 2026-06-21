import asyncio
import json
import os
import threading
import time
from typing import Callable, Dict, List, Optional

import app.core.env_bootstrap


MARKET_WS_URL = os.getenv(
    "BINANCE_MARKET_WS_URL",
    "wss://fstream.binance.com/market/ws/!markPrice@arr@1s",
)

# AUTO | WS | HTTP
PRICE_FEED_MODE = os.getenv("PRICE_FEED_MODE", "AUTO").upper()

# MARK | LAST
HTTP_PRICE_SOURCE = os.getenv("HTTP_PRICE_SOURCE", "MARK").upper()

RECONNECT_DELAY = 5
MAX_RECONNECT = 5
STALE_THRESHOLD = 15
FIRST_MSG_TIMEOUT = 12
RECV_TIMEOUT = 12

HTTP_INTERVAL = float(os.getenv("PRICE_FEED_HTTP_INTERVAL", "1.5"))
WS_RECOVERY_INTERVAL = float(os.getenv("PRICE_FEED_WS_RECOVERY_INTERVAL", "60"))


class BinanceWsPriceFeed:
    """
    Binance USD-M Futures price feed using the routed market stream endpoint.

    Binance migrated market streams such as markPrice to the /market route. The
    old unrouted /ws path can handshake but not push market-route payloads.
    """

    def __init__(self):
        self._price_map: Dict[str, float] = {}
        self._last_update: float = 0
        self._lock = threading.RLock()

        self._running = False
        self._connected = False
        self._mode = "stopped"
        self._reconnect_count = 0

        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._callbacks: List[Callable] = []

        self._started_at: Optional[float] = None
        self._handshake_at: Optional[float] = None
        self._first_payload_at: Optional[float] = None
        self._last_error: Optional[str] = None
        self._last_error_at: Optional[float] = None
        self._ws_sessions_ok = 0
        self._http_cycles_ok = 0

    def add_callback(self, callback: Callable):
        self._callbacks.append(callback)

    def start(self):
        if self._running:
            return
        self._running = True
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="BinanceWsPriceFeed",
        )
        self._thread.start()
        print(f"[PRICE FEED] starting mode={PRICE_FEED_MODE} ws={MARKET_WS_URL}")

    def stop(self):
        self._running = False
        self._mode = "stopped"
        self._connected = False
        print("[PRICE FEED] stopped")

    def restart(self):
        self.stop()
        time.sleep(1)
        self.start()

    def get_price(self, symbol: str) -> Optional[float]:
        with self._lock:
            return self._price_map.get(str(symbol or "").upper())

    def get_all_prices(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._price_map)

    def is_healthy(self) -> bool:
        if not self._connected or not self._last_update:
            return False
        return (time.time() - self._last_update) < STALE_THRESHOLD

    def wait_ready(self, timeout: float = 10.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            if self._price_map and self.is_healthy():
                return True
            time.sleep(0.5)
        return False

    def get_stats(self) -> Dict:
        with self._lock:
            now = time.time()

            def age(ts):
                return round(now - ts, 1) if ts else None

            return {
                "service": "binance_ws_price_feed",
                "mode": self._mode,
                "configured_mode": PRICE_FEED_MODE,
                "ws_url": MARKET_WS_URL,
                "http_price_source": HTTP_PRICE_SOURCE,
                "connected": self._connected,
                "healthy": self.is_healthy(),
                "running": self._running,
                "symbols_count": len(self._price_map),
                "callbacks": len(self._callbacks),
                "reconnect_count": self._reconnect_count,
                "started_at_ts": self._started_at,
                "handshake_at_ts": self._handshake_at,
                "first_payload_at_ts": self._first_payload_at,
                "last_update_ts": self._last_update,
                "last_error_at_ts": self._last_error_at,
                "started_ago_s": age(self._started_at),
                "handshake_ago_s": age(self._handshake_at),
                "first_payload_ago_s": age(self._first_payload_at),
                "last_update_ago_s": age(self._last_update),
                "last_error_ago_s": age(self._last_error_at),
                "last_error": self._last_error,
                "ws_sessions_ok": self._ws_sessions_ok,
                "http_cycles_ok": self._http_cycles_ok,
            }

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            self._set_error(f"Loop error: {type(e).__name__}: {e}")
            print(f"[PRICE FEED] loop error: {e}")
        finally:
            self._loop.close()

    async def _main(self):
        if PRICE_FEED_MODE == "HTTP":
            await self._http_primary_loop()
        elif PRICE_FEED_MODE == "WS":
            await self._ws_main_loop(force_ws_only=True)
        else:
            await self._ws_main_loop(force_ws_only=False)

    async def _ws_main_loop(self, force_ws_only: bool):
        while self._running:
            try:
                await self._ws_session()
            except Exception as e:
                self._connected = False
                self._set_error(f"WS error: {type(e).__name__}: {e}")
                print(f"[PRICE FEED] WS error: {type(e).__name__}: {e}")

                if not self._running:
                    break

                self._reconnect_count += 1
                if not force_ws_only and self._reconnect_count >= MAX_RECONNECT:
                    print("[PRICE FEED] max WS reconnects reached, switching to HTTP")
                    await self._http_primary_loop()
                    self._reconnect_count = 0
                    continue

                await asyncio.sleep(min(RECONNECT_DELAY * self._reconnect_count, 60))

    async def _ws_session(self):
        import websockets

        self._connected = False
        self._mode = "ws_connecting"
        self._handshake_at = None
        self._first_payload_at = None

        async with websockets.connect(
            MARKET_WS_URL,
            ping_interval=20,
            ping_timeout=10,
            open_timeout=10,
            close_timeout=5,
            max_size=10 * 1024 * 1024,
            compression=None,
        ) as ws:
            self._handshake_at = time.time()
            raw = await asyncio.wait_for(ws.recv(), timeout=FIRST_MSG_TIMEOUT)
            first_count = await self._process_ws(raw)
            if first_count <= 0:
                raise RuntimeError("first WS payload empty or invalid")

            self._connected = True
            self._mode = "ws_market"
            self._reconnect_count = 0
            self._first_payload_at = time.time()
            self._ws_sessions_ok += 1
            print(f"[PRICE FEED] WS first payload OK: {first_count} symbols")

            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT)
                    await self._process_ws(raw)
                except asyncio.TimeoutError:
                    raise TimeoutError(f"no WS payload for {RECV_TIMEOUT}s")

    async def _process_ws(self, raw) -> int:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")

            payload = json.loads(raw)
            data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload

            if not isinstance(data, list):
                return 0

            updates = {}
            for item in data:
                symbol = item.get("s")
                price = item.get("p")
                if not symbol or price is None:
                    continue
                try:
                    updates[str(symbol).upper()] = float(price)
                except Exception:
                    continue

            if not updates:
                return 0

            self._apply_updates(updates)
            return len(updates)
        except Exception as e:
            self._set_error(f"WS process error: {type(e).__name__}: {e}")
            print(f"[PRICE FEED] WS process error: {type(e).__name__}: {e}")
            return 0

    async def _http_primary_loop(self):
        self._mode = "http_mark" if HTTP_PRICE_SOURCE == "MARK" else "http_last"
        self._connected = False
        last_ws_retry = time.time()

        while self._running:
            if PRICE_FEED_MODE == "AUTO" and (time.time() - last_ws_retry >= WS_RECOVERY_INTERVAL):
                try:
                    await self._ws_session()
                    return
                except Exception as e:
                    self._set_error(f"WS retry failed: {type(e).__name__}: {e}")
                last_ws_retry = time.time()

            try:
                prices = await self._fetch_http_prices()
                if prices:
                    self._apply_updates(prices)
                    self._connected = True
                    self._http_cycles_ok += 1
                else:
                    self._connected = False
            except Exception as e:
                self._connected = False
                self._set_error(f"HTTP error: {type(e).__name__}: {e}")
                print(f"[PRICE FEED] HTTP error: {type(e).__name__}: {e}")

            await asyncio.sleep(HTTP_INTERVAL)

    async def _fetch_http_prices(self) -> Dict[str, float]:
        import aiohttp

        url = (
            "https://fapi.binance.com/fapi/v1/premiumIndex"
            if HTTP_PRICE_SOURCE == "MARK"
            else "https://fapi.binance.com/fapi/v1/ticker/price"
        )
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                data = await resp.json()

        prices: Dict[str, float] = {}
        if not isinstance(data, list):
            return prices

        for item in data:
            symbol = item.get("symbol")
            raw_price = item.get("markPrice") if HTTP_PRICE_SOURCE == "MARK" else item.get("price")
            if not symbol or raw_price is None:
                continue
            try:
                prices[str(symbol).upper()] = float(raw_price)
            except Exception:
                continue
        return prices

    def _apply_updates(self, updates: Dict[str, float]):
        with self._lock:
            self._price_map.update(updates)
            self._last_update = time.time()

        if self._callbacks:
            snapshot = self.get_all_prices()
            asyncio.create_task(self._fire_callbacks(snapshot))

    async def _fire_callbacks(self, price_map: Dict[str, float]):
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(price_map)
                else:
                    cb(price_map)
            except Exception as e:
                self._set_error(f"Callback error: {type(e).__name__}: {e}")
                print(f"[PRICE FEED] callback error: {e}")

    def _set_error(self, msg: str):
        self._last_error = msg
        self._last_error_at = time.time()


_price_feed = BinanceWsPriceFeed()


def get_price_feed() -> BinanceWsPriceFeed:
    return _price_feed


def start_price_feed():
    _price_feed.start()


def stop_price_feed():
    _price_feed.stop()


def restart_price_feed():
    _price_feed.restart()


def add_price_callback(cb: Callable):
    _price_feed.add_callback(cb)


def get_current_price(symbol: str) -> Optional[float]:
    return _price_feed.get_price(symbol)


def get_all_current_prices() -> Dict[str, float]:
    return _price_feed.get_all_prices()
