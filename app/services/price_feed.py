# app/services/price_feed.py

import asyncio
import json
import time
import threading
from typing import Dict, Optional, Callable, List

WS_URL = "wss://fstream.binance.com/ws/!markPrice@arr@1s"
RECONNECT_DELAY = 5
MAX_RECONNECT = 10
STALE_THRESHOLD = 15
HTTP_FALLBACK_INTERVAL = 3


class PriceFeedManager:

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

    def add_callback(self, callback: Callable):
        self._callbacks.append(callback)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="PriceFeedWS"
        )
        self._thread.start()
        print("📡 Price Feed starting...")

    def stop(self):
        self._running = False
        self._mode = "stopped"
        self._connected = False
        print("🛑 Price Feed stopped")

    def get_price(self, symbol: str) -> Optional[float]:
        with self._lock:
            return self._price_map.get(symbol)

    def get_all_prices(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._price_map)

    def is_healthy(self) -> bool:
        if not self._connected and self._mode != "http":
            return False
        return time.time() - self._last_update < STALE_THRESHOLD

    def get_stats(self) -> Dict:
        with self._lock:
            return {
                "mode": self._mode,
                "connected": self._connected,
                "symbols_count": len(self._price_map),
                "last_update_ago_s": round(
                    time.time() - self._last_update, 1
                ) if self._last_update else None,
                "reconnect_count": self._reconnect_count,
                "healthy": self.is_healthy(),
                "callbacks": len(self._callbacks),
            }

    def wait_ready(self, timeout: float = 10.0) -> bool:
        start = time.time()
        while time.time() - start < timeout:
            if self._price_map:
                return True
            time.sleep(0.5)
        return False

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            print(f"[PRICE FEED] Loop error: {e}")
        finally:
            self._loop.close()

    async def _main(self):
        while self._running:
            try:
                await self._ws_session()
            except Exception as e:
                self._connected = False
                print(f"[PRICE FEED] WS error: {e}")
                if not self._running:
                    break
                self._reconnect_count += 1
                if self._reconnect_count >= MAX_RECONNECT:
                    print("[PRICE FEED] Max reconnects → HTTP fallback")
                    await self._http_fallback()
                    return
                delay = min(RECONNECT_DELAY * self._reconnect_count, 60)
                print(f"[PRICE FEED] Reconnect in {delay}s...")
                await asyncio.sleep(delay)

    async def _ws_session(self):
        import websockets
        print("[PRICE FEED] Connecting...")
        async with websockets.connect(
            WS_URL, ping_interval=30, ping_timeout=10,
            max_size=10 * 1024 * 1024
        ) as ws:
            self._connected = True
            self._reconnect_count = 0
            self._mode = "ws"
            print("✅ [PRICE FEED] Connected")
            async for raw in ws:
                if not self._running:
                    return
                await self._process(raw)

    async def _process(self, raw: str):
        try:
            data = json.loads(raw)
            if not isinstance(data, list):
                return
            updates = {}
            for item in data:
                if "s" in item and "p" in item:
                    updates[item["s"]] = float(item["p"])
            if not updates:
                return
            with self._lock:
                self._price_map.update(updates)
                self._last_update = time.time()
            if self._callbacks:
                snapshot = self.get_all_prices()
                await self._fire_callbacks(snapshot)
        except Exception:
            pass

    async def _http_fallback(self):
        self._mode = "http"
        print(f"[PRICE FEED] HTTP fallback every {HTTP_FALLBACK_INTERVAL}s")
        while self._running:
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        "https://fapi.binance.com/fapi/v1/ticker/price",
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        data = await resp.json()
                prices = {}
                for item in data:
                    if "symbol" in item and "price" in item:
                        prices[item["symbol"]] = float(item["price"])
                if prices:
                    with self._lock:
                        self._price_map.update(prices)
                        self._last_update = time.time()
                        self._connected = True
                    await self._fire_callbacks(prices)
            except Exception as e:
                print(f"[PRICE FEED] HTTP error: {e}")
                self._connected = False
            await asyncio.sleep(HTTP_FALLBACK_INTERVAL)

    async def _fire_callbacks(self, price_map: Dict):
        for cb in self._callbacks:
            try:
                if asyncio.iscoroutinefunction(cb):
                    await cb(price_map)
                else:
                    cb(price_map)
            except Exception as e:
                print(f"[PRICE FEED] Callback error: {e}")


# ── Singleton ─────────────────────────────────────────────────

_price_feed = PriceFeedManager()


def get_price_feed() -> PriceFeedManager:
    return _price_feed


def start_price_feed():
    _price_feed.start()


def stop_price_feed():
    _price_feed.stop()


def add_price_callback(cb: Callable):
    _price_feed.add_callback(cb)


def get_current_price(symbol: str) -> Optional[float]:
    price = _price_feed.get_price(symbol)
    if price is not None:
        return price
    try:
        from app.services.binance_service import get_all_prices
        return get_all_prices().get(symbol)
    except Exception:
        return None


def get_all_current_prices() -> Dict[str, float]:
    if _price_feed.is_healthy() and _price_feed.get_all_prices():
        return _price_feed.get_all_prices()
    try:
        from app.services.binance_service import get_all_prices
        return get_all_prices()
    except Exception:
        return {}