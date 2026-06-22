import asyncio
import json
import os
import threading
import time
from typing import Dict, Optional

import requests
from sqlalchemy import text

import app.core.env_bootstrap
from app.core.trading_mode import TradingMode, get_current_mode, get_trading_mode
from app.db.session import SessionLocal


KEEPALIVE_INTERVAL = int(os.getenv("BINANCE_USER_STREAM_KEEPALIVE_SECONDS", "1800"))
RECONNECT_DELAY = int(os.getenv("BINANCE_USER_STREAM_RECONNECT_SECONDS", "5"))
RECV_TIMEOUT = int(os.getenv("BINANCE_USER_STREAM_RECV_TIMEOUT_SECONDS", "900"))

LIVE_WS_BASE = os.getenv("BINANCE_USER_STREAM_WS_BASE", "wss://fstream.binance.com/private/ws")
TESTNET_WS_BASE = os.getenv("BINANCE_TESTNET_USER_STREAM_WS_BASE", "wss://stream.binancefuture.com/ws")


class BinanceUserStreamService:
    """
    Observe-only Binance USD-M Futures user data stream.

    Phase 1 intentionally does not mutate pending/signals. It stores exchange
    order events so reconciliation can later use real exchange evidence before
    falling back to algo detail queries.
    """

    def __init__(self):
        self._lock = threading.RLock()
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._http = requests.Session()

        self._running = False
        self._connected = False
        self._mode = "stopped"
        self._listen_key: Optional[str] = None
        self._listen_key_created_at: Optional[float] = None
        self._listen_key_keepalive_at: Optional[float] = None
        self._started_at: Optional[float] = None
        self._connected_at: Optional[float] = None
        self._last_event_at: Optional[float] = None
        self._last_event_type: Optional[str] = None
        self._last_error: Optional[str] = None
        self._last_error_at: Optional[float] = None
        self._reconnect_count = 0
        self._events_saved = 0
        self._pending_updates = 0

    def start(self):
        if self._running:
            return
        mode = get_current_mode()
        if mode == TradingMode.PAPER:
            self._mode = "disabled_paper"
            return
        self._running = True
        self._started_at = time.time()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name="BinanceUserStream",
        )
        self._thread.start()
        print(f"[USER STREAM] starting mode={mode.value}")

    def stop(self):
        self._running = False
        self._connected = False
        self._mode = "stopped"
        listen_key = self._listen_key
        if listen_key:
            try:
                self._close_listen_key(listen_key)
            except Exception as e:
                self._set_error(f"close listenKey error: {type(e).__name__}: {e}")
        print("[USER STREAM] stopped")

    def restart(self):
        self.stop()
        time.sleep(1)
        self.start()

    def get_stats(self) -> Dict:
        with self._lock:
            now = time.time()

            def age(ts):
                return round(now - ts, 1) if ts else None

            return {
                "service": "binance_user_stream",
                "mode": self._mode,
                "running": self._running,
                "connected": self._connected,
                "trading_mode": get_current_mode().value,
                "listen_key_present": bool(self._listen_key),
                "listen_key_age_s": age(self._listen_key_created_at),
                "listen_key_keepalive_ago_s": age(self._listen_key_keepalive_at),
                "started_ago_s": age(self._started_at),
                "connected_ago_s": age(self._connected_at),
                "last_event_ago_s": age(self._last_event_at),
                "last_event_type": self._last_event_type,
                "last_error": self._last_error,
                "last_error_ago_s": age(self._last_error_at),
                "reconnect_count": self._reconnect_count,
                "events_saved": self._events_saved,
                "pending_updates": self._pending_updates,
            }

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._main())
        except Exception as e:
            self._set_error(f"loop error: {type(e).__name__}: {e}")
            print(f"[USER STREAM] loop error: {e}")
        finally:
            self._loop.close()

    async def _main(self):
        self._ensure_table()

        while self._running:
            try:
                listen_key = self._create_listen_key()
                with self._lock:
                    self._listen_key = listen_key
                    self._listen_key_created_at = time.time()
                    self._listen_key_keepalive_at = self._listen_key_created_at

                keepalive_task = asyncio.create_task(self._keepalive_loop(listen_key))
                try:
                    await self._ws_session(listen_key)
                finally:
                    keepalive_task.cancel()
                    await asyncio.gather(keepalive_task, return_exceptions=True)

            except Exception as e:
                self._connected = False
                self._reconnect_count += 1
                self._set_error(f"stream error: {type(e).__name__}: {e}")
                print(f"[USER STREAM] stream error: {type(e).__name__}: {e}")
                if self._running:
                    await asyncio.sleep(min(RECONNECT_DELAY * self._reconnect_count, 60))

    async def _ws_session(self, listen_key: str):
        import websockets

        url = f"{self._ws_base().rstrip('/')}/{listen_key}"
        self._mode = "ws_connecting"

        async with websockets.connect(
            url,
            ping_interval=20,
            ping_timeout=10,
            open_timeout=10,
            close_timeout=5,
            max_size=5 * 1024 * 1024,
            compression=None,
        ) as ws:
            self._connected = True
            self._connected_at = time.time()
            self._mode = "ws_private"
            self._reconnect_count = 0
            print("[USER STREAM] connected")

            while self._running:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=RECV_TIMEOUT)
                    await self._handle_message(raw)
                except asyncio.TimeoutError:
                    raise TimeoutError(f"no user stream payload for {RECV_TIMEOUT}s")

    async def _handle_message(self, raw):
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        event = json.loads(raw)
        if not isinstance(event, dict):
            return

        event_type = event.get("e") or "UNKNOWN"
        with self._lock:
            self._last_event_at = time.time()
            self._last_event_type = event_type

        if event_type in {"ORDER_TRADE_UPDATE", "ACCOUNT_UPDATE", "listenKeyExpired"}:
            self._save_event(event)
            if event_type == "ORDER_TRADE_UPDATE":
                self._apply_entry_order_update(event)

        if event_type == "listenKeyExpired":
            raise RuntimeError("listenKey expired")

    async def _keepalive_loop(self, listen_key: str):
        while self._running:
            await asyncio.sleep(KEEPALIVE_INTERVAL)
            self._keepalive_listen_key(listen_key)
            with self._lock:
                self._listen_key_keepalive_at = time.time()

    def _create_listen_key(self) -> str:
        cfg = get_trading_mode().get_binance_config()
        api_key = cfg.get("api_key")
        base_url = cfg.get("base_url")
        if not api_key or not base_url:
            raise RuntimeError("Binance API key/base_url missing for user stream")

        resp = self._http.post(
            f"{base_url}/fapi/v1/listenKey",
            headers={"X-MBX-APIKEY": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        listen_key = data.get("listenKey")
        if not listen_key:
            raise RuntimeError("listenKey missing in Binance response")
        return listen_key

    def _keepalive_listen_key(self, listen_key: str):
        cfg = get_trading_mode().get_binance_config()
        api_key = cfg.get("api_key")
        base_url = cfg.get("base_url")
        resp = self._http.put(
            f"{base_url}/fapi/v1/listenKey",
            headers={"X-MBX-APIKEY": api_key},
            timeout=10,
        )
        resp.raise_for_status()

    def _close_listen_key(self, listen_key: str):
        cfg = get_trading_mode().get_binance_config()
        api_key = cfg.get("api_key")
        base_url = cfg.get("base_url")
        if not api_key or not base_url:
            return
        self._http.delete(
            f"{base_url}/fapi/v1/listenKey",
            headers={"X-MBX-APIKEY": api_key},
            timeout=10,
        )

    def _ws_base(self) -> str:
        if get_current_mode() == TradingMode.TESTNET:
            return TESTNET_WS_BASE
        return LIVE_WS_BASE

    def _save_event(self, event: Dict):
        order = event.get("o") or {}
        event_type = event.get("e")
        event_time_ms = _safe_int(event.get("E"))
        transaction_time_ms = _safe_int(event.get("T") or order.get("T"))
        order_id = _safe_str(order.get("i"))
        trade_id = _safe_str(order.get("t"))
        execution_type = _safe_str(order.get("x"))
        order_status = _safe_str(order.get("X"))

        unique_event_key = "|".join([
            _safe_str(event_type),
            str(event_time_ms or ""),
            str(transaction_time_ms or ""),
            order_id or "",
            trade_id or "",
            execution_type or "",
            order_status or "",
        ])

        with SessionLocal() as db:
            db.execute(text("""
                INSERT INTO exchange_order_events (
                    unique_event_key, event_type, event_time_ms, transaction_time_ms,
                    symbol, order_id, client_order_id, side, order_type,
                    execution_type, order_status, avg_price, last_filled_qty,
                    accumulated_filled_qty, last_filled_price, realized_pnl,
                    reduce_only, close_position, raw, created_at
                )
                VALUES (
                    :unique_event_key, :event_type, :event_time_ms, :transaction_time_ms,
                    :symbol, :order_id, :client_order_id, :side, :order_type,
                    :execution_type, :order_status, :avg_price, :last_filled_qty,
                    :accumulated_filled_qty, :last_filled_price, :realized_pnl,
                    :reduce_only, :close_position, CAST(:raw AS JSONB), NOW()
                )
                ON CONFLICT (unique_event_key) DO NOTHING
            """), {
                "unique_event_key": unique_event_key,
                "event_type": event_type,
                "event_time_ms": event_time_ms,
                "transaction_time_ms": transaction_time_ms,
                "symbol": _safe_str(order.get("s")),
                "order_id": order_id,
                "client_order_id": _safe_str(order.get("c")),
                "side": _safe_str(order.get("S")),
                "order_type": _safe_str(order.get("o")),
                "execution_type": execution_type,
                "order_status": order_status,
                "avg_price": _safe_float(order.get("ap")),
                "last_filled_qty": _safe_float(order.get("l")),
                "accumulated_filled_qty": _safe_float(order.get("z")),
                "last_filled_price": _safe_float(order.get("L")),
                "realized_pnl": _safe_float(order.get("rp")),
                "reduce_only": _safe_bool(order.get("R")),
                "close_position": _safe_bool(order.get("cp")),
                "raw": json.dumps(event, separators=(",", ":")),
            })
            db.commit()

        with self._lock:
            self._events_saved += 1

    def _apply_entry_order_update(self, event: Dict):
        """
        Update pending exchange tracking from QRL_ENTRY_<pending_id> events.

        This deliberately does not set PendingSignal.status. Reconciler remains
        the lifecycle owner and will create/update signals from these fields.
        """
        order = event.get("o") or {}
        client_order_id = _safe_str(order.get("c")) or ""
        if not client_order_id.startswith("QRL_ENTRY_"):
            return

        raw_id = client_order_id.replace("QRL_ENTRY_", "", 1).split("_", 1)[0]
        try:
            pending_id = int(raw_id)
        except Exception:
            return

        order_id = _safe_str(order.get("i"))
        order_status = _safe_str(order.get("X"))
        orig_qty = _safe_float(order.get("q"))
        executed_qty = _safe_float(order.get("z"))
        avg_price = _safe_float(order.get("ap"))

        try:
            with SessionLocal() as db:
                result = db.execute(text("""
                    UPDATE pending_signals
                    SET
                        client_order_id = COALESCE(:client_order_id, client_order_id),
                        exchange_order_id = COALESCE(:order_id, exchange_order_id),
                        exchange_status = COALESCE(:order_status, exchange_status),
                        placed_at = COALESCE(placed_at, NOW()),
                        order_quantity = CASE
                            WHEN :orig_qty IS NOT NULL AND :orig_qty > 0 THEN :orig_qty
                            ELSE order_quantity
                        END,
                        executed_qty = CASE
                            WHEN :executed_qty IS NOT NULL THEN GREATEST(COALESCE(executed_qty, 0), :executed_qty)
                            ELSE executed_qty
                        END,
                        avg_fill_price = CASE
                            WHEN :avg_price IS NOT NULL AND :avg_price > 0 THEN :avg_price
                            ELSE avg_fill_price
                        END,
                        last_exchange_sync_at = NOW(),
                        next_retry_at = NULL,
                        last_place_error = NULL
                    WHERE id = :pending_id
                      AND status = 'WAIT'
                """), {
                    "pending_id": pending_id,
                    "client_order_id": client_order_id,
                    "order_id": order_id,
                    "order_status": order_status,
                    "orig_qty": orig_qty,
                    "executed_qty": executed_qty,
                    "avg_price": avg_price,
                })
                db.commit()

            if result.rowcount:
                with self._lock:
                    self._pending_updates += 1
                print(
                    f"[USER STREAM] pending update id={pending_id} "
                    f"status={order_status} executed={executed_qty} avg={avg_price}"
                )
        except Exception as e:
            self._set_error(f"pending update error: {type(e).__name__}: {e}")
            print(f"[USER STREAM] pending update error pending={pending_id}: {e}")

    def _ensure_table(self):
        with SessionLocal() as db:
            db.execute(text("""
                CREATE TABLE IF NOT EXISTS exchange_order_events (
                    id BIGSERIAL PRIMARY KEY,
                    unique_event_key TEXT NOT NULL UNIQUE,
                    event_type TEXT,
                    event_time_ms BIGINT,
                    transaction_time_ms BIGINT,
                    symbol TEXT,
                    order_id TEXT,
                    client_order_id TEXT,
                    side TEXT,
                    order_type TEXT,
                    execution_type TEXT,
                    order_status TEXT,
                    avg_price NUMERIC,
                    last_filled_qty NUMERIC,
                    accumulated_filled_qty NUMERIC,
                    last_filled_price NUMERIC,
                    realized_pnl NUMERIC,
                    reduce_only BOOLEAN,
                    close_position BOOLEAN,
                    raw JSONB,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
            """))
            db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_exchange_order_events_symbol_time
                ON exchange_order_events (symbol, event_time_ms DESC)
            """))
            db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_exchange_order_events_order_id
                ON exchange_order_events (order_id)
            """))
            db.execute(text("""
                CREATE INDEX IF NOT EXISTS idx_exchange_order_events_type_status
                ON exchange_order_events (event_type, execution_type, order_status)
            """))
            db.commit()

    def _set_error(self, msg: str):
        with self._lock:
            self._last_error = msg
            self._last_error_at = time.time()


def _safe_str(v):
    if v is None:
        return None
    return str(v)


def _safe_int(v):
    try:
        return int(v)
    except Exception:
        return None


def _safe_float(v):
    try:
        return float(v)
    except Exception:
        return None


def _safe_bool(v):
    if isinstance(v, bool):
        return v
    if v is None:
        return None
    return str(v).lower() == "true"


_user_stream = BinanceUserStreamService()


def get_user_stream() -> BinanceUserStreamService:
    return _user_stream


def start_user_stream():
    _user_stream.start()


def stop_user_stream():
    _user_stream.stop()


def restart_user_stream():
    _user_stream.restart()
