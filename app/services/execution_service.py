"""
Order Execution Service
=======================
Paper:     ghi DB only, fill tại fill_price
Testnet:   Binance Testnet API
Live:      Binance Mainnet API

LIVE / TESTNET execution model:
- Entry: LIMIT order qua /fapi/v1/order
- Exits: Algo Orders qua /fapi/v1/algoOrder
         (STOP_MARKET / TAKE_PROFIT_MARKET + closePosition=true)
- workingType = MARK_PRICE

Position sizing:
- đọc từ POSITION_SIZE_CONFIG trong app_config
- 2 mode:
    + fixed_usdt   -> fixed_usdt_per_trade = margin budget
                      notional = fixed_usdt_per_trade * leverage
    + risk_based   -> risk % vốn
"""

import time
import hmac
import hashlib
import traceback
import requests
from dataclasses import dataclass
from typing import Optional, Dict, Tuple, List
from urllib.parse import urlencode

from app.core.trading_mode import get_trading_mode, TradingMode


# ============================================================
# CONSTANTS
# ============================================================

ALGO_WORKING_TYPE = "MARK_PRICE"
SIGNED_TIMEOUT = 10

_http = requests.Session()


# ============================================================
# Order Result
# ============================================================

@dataclass
class OrderResult:
    success:         bool
    order_id:        Optional[str]   = None
    actual_entry:    Optional[float] = None
    actual_quantity: Optional[float] = None
    fee:             float           = 0.0
    error:           Optional[str]   = None
    mode:            str             = "PAPER"
    leverage:        int             = 1
    sl_order_id:     Optional[str]   = None
    tp_order_id:     Optional[str]   = None


# ============================================================
# Position Sizer
# ============================================================

class PositionSizer:
    def __init__(
        self,
        account_balance: float = 10000,
        risk_pct:        float = 0.01,
        max_leverage:    int   = 3
    ):
        self.balance      = account_balance
        self.risk_pct     = risk_pct
        self.max_leverage = max_leverage

    def calc(self, entry_price: float, stop_loss: float) -> Tuple[float, int]:
        if entry_price <= 0 or stop_loss <= 0:
            return self.balance * 0.05, 1

        price_risk = abs(entry_price - stop_loss) / entry_price
        if price_risk <= 0:
            return self.balance * 0.05, 1

        risk_amount = self.balance * self.risk_pct
        safe_lev = min(self.max_leverage, max(1, int(0.02 / price_risk)))
        notional = (risk_amount / price_risk) * safe_lev

        max_notional = self.balance * 0.3
        notional = min(notional, max_notional)

        return round(notional, 2), safe_lev


# ============================================================
# Position Size Config
# ============================================================

def _calc_order_size(
    entry_price: float,
    stop_loss: float,
    balance: float
) -> Tuple[float, int]:
    from app.services.config_service import get_runtime_config

    cfg = get_runtime_config()
    pos_cfg = cfg.get("POSITION_SIZE_CONFIG", {})
    mode = pos_cfg.get("mode", "fixed_usdt")

    max_pos = float(pos_cfg.get("max_position_usdt", 500))
    max_lev = int(pos_cfg.get("default_leverage", 3))

    if mode == "fixed_usdt":
        fixed_margin = float(pos_cfg.get("fixed_usdt_per_trade", 200))
        leverage = max_lev
        notional = min(fixed_margin * leverage, max_pos)
    else:
        risk_pct = float(pos_cfg.get("risk_per_trade_pct", 0.01))
        sizer = PositionSizer(
            account_balance=balance,
            risk_pct=risk_pct,
            max_leverage=max_lev,
        )
        notional, leverage = sizer.calc(entry_price, stop_loss)
        notional = min(notional, max_pos)

    return notional, leverage


def _get_min_notional(symbol_info: Optional[Dict]) -> float:
    if not symbol_info:
        return 5.0

    for f in symbol_info.get("filters", []):
        ft = f.get("filterType")

        if ft == "MIN_NOTIONAL":
            try:
                return float(f.get("notional") or f.get("minNotional") or 5.0)
            except Exception:
                return 5.0

        if ft == "NOTIONAL":
            try:
                return float(f.get("minNotional") or 5.0)
            except Exception:
                return 5.0

    return 5.0


# ============================================================
# Raw Signed Binance HTTP for Algo Orders
# ============================================================

def _signed_request(method: str, path: str, params: Dict) -> Dict:
    mode = get_trading_mode()
    cfg = mode.get_binance_config()

    api_key = cfg.get("api_key")
    api_secret = cfg.get("api_secret")
    base_url = cfg.get("base_url")

    if not api_key or not api_secret or not base_url:
        raise RuntimeError("Missing Binance API credentials")

    payload = dict(params or {})
    payload["timestamp"] = int(time.time() * 1000)

    query = urlencode(payload, doseq=True)
    signature = hmac.new(
        api_secret.encode("utf-8"),
        query.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    full_params = dict(payload)
    full_params["signature"] = signature

    headers = {
        "X-MBX-APIKEY": api_key
    }

    url = f"{base_url}{path}"

    resp = _http.request(
        method.upper(),
        url,
        params=full_params,
        headers=headers,
        timeout=SIGNED_TIMEOUT,
    )

    try:
        data = resp.json()
    except Exception:
        data = {"raw_text": resp.text}

    if not resp.ok:
        code = data.get("code")
        msg  = data.get("msg") or str(data)
        raise RuntimeError(
            f"Binance signed request failed [{resp.status_code}] code={code} msg={msg}"
        )

    return data


# ============================================================
# Binance Executor
# ============================================================

class BinanceExecutor:
    """Wrapper cho Binance Futures API thường."""

    def __init__(self, testnet: bool = False):
        self.testnet = testnet
        self._client = None
        self._init_client()
        self._last_error = None

    def _init_client(self):
        try:
            from binance.um_futures import UMFutures
        except ImportError:
            print("⚠️ binance-futures-connector not installed")
            print("   pip install binance-futures-connector")
            return

        mode = get_trading_mode()
        cfg  = mode.get_binance_config()

        if not cfg["api_key"] or not cfg["api_secret"]:
            print("⚠️ Binance API key/secret not configured")
            return

        self._client = UMFutures(
            key=cfg["api_key"],
            secret=cfg["api_secret"],
            base_url=cfg["base_url"]
        )
        mode_label = "Testnet" if self.testnet else "Mainnet"
        print(f"✅ Binance client init ({mode_label})")

    @property
    def ready(self) -> bool:
        return self._client is not None

    # ── Account ──────────────────────────────────────────

    def get_balance(self) -> float:
        if not self.ready:
            return 0.0
        try:
            account = self._client.account()
            for asset in account.get("assets", []):
                if asset["asset"] == "USDT":
                    return float(asset["availableBalance"])
        except Exception as e:
            print(f"[EXEC] Balance error: {e}")
        return 0.0

    # ── Symbol Info ──────────────────────────────────────

    def get_symbol_info(self, symbol: str) -> Optional[Dict]:
        if not self.ready:
            return None
        try:
            info = self._client.exchange_info()
            for s in info.get("symbols", []):
                if s["symbol"] == symbol:
                    return s
        except Exception as e:
            print(f"[EXEC] Info error {symbol}: {e}")
        return None

    def round_quantity(
        self, symbol: str, quantity: float,
        symbol_info: Optional[Dict] = None
    ) -> float:
        if symbol_info is None:
            symbol_info = self.get_symbol_info(symbol)
        if not symbol_info:
            return round(quantity, 3)

        for f in symbol_info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                step = float(f["stepSize"])
                if step > 0:
                    quantity = round(quantity - (quantity % step), 8)
                break
        return quantity

    def round_price(
        self, symbol: str, price: float,
        symbol_info: Optional[Dict] = None
    ) -> float:
        if symbol_info is None:
            symbol_info = self.get_symbol_info(symbol)
        if not symbol_info:
            return round(price, 4)

        for f in symbol_info.get("filters", []):
            if f["filterType"] == "PRICE_FILTER":
                tick = float(f["tickSize"])
                if tick > 0:
                    price = round(price - (price % tick), 8)
                break
        return price

    # ── Leverage ─────────────────────────────────────────

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        if not self.ready:
            return False
        try:
            self._client.change_leverage(symbol=symbol, leverage=leverage)
            return True
        except Exception as e:
            print(f"[EXEC] Leverage error {symbol}: {e}")
            return False

    # ── Standard Orders ──────────────────────────────────

    def market_order(
        self, symbol: str, side: str, quantity: float,
        reduce_only: bool = False
    ) -> Optional[Dict]:
        if not self.ready:
            return None
        try:
            params = {
                "symbol":   symbol,
                "side":     side,
                "type":     "MARKET",
                "quantity": quantity,
            }
            if reduce_only:
                params["reduceOnly"] = "true"
            return self._client.new_order(**params)
        except Exception as e:
            print(f"[EXEC] Market order error {symbol} {side}: {e}")
            return None

    def limit_order(self, symbol, side, quantity, price, tif="GTC"):
        if not self.ready:
            return None
        try:
            self._last_error = None
            return self._client.new_order(
                symbol=symbol, side=side, type="LIMIT",
                quantity=quantity, price=price, timeInForce=tif
            )
        except Exception as e:
            self._last_error = str(e)
            print(f"[EXEC] Limit order error {symbol} {side}: {e}")
            return None

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        if not self.ready:
            return False
        try:
            self._client.cancel_order(symbol=symbol, orderId=order_id)
            return True
        except Exception as e:
            err_str = str(e)
            if "-2011" in err_str or "Unknown order" in err_str:
                return True
            print(f"[EXEC] Cancel order error {symbol}/{order_id}: {e}")
            return False

    def cancel_all_orders(self, symbol: str) -> bool:
        if not self.ready:
            return False
        try:
            self._client.cancel_open_orders(symbol=symbol)
            return True
        except Exception as e:
            print(f"[EXEC] Cancel all error {symbol}: {e}")
            return False

    def query_order(self, symbol: str, order_id: str) -> Optional[Dict]:
        if not self.ready:
            return None
        try:
            return self._client.query_order(symbol=symbol, orderId=order_id)
        except Exception as e:
            print(f"[EXEC] Query order error {symbol}/{order_id}: {e}")
            return None

    def get_open_orders(self, symbol: str) -> List[Dict]:
        if not self.ready:
            return []
        try:
            return self._client.get_orders(symbol=symbol)
        except Exception as e:
            print(f"[EXEC] Get open orders error {symbol}: {e}")
            return []

    # ── Position ─────────────────────────────────────────

    def get_position_size(self, symbol: str) -> float:
        if not self.ready:
            return 0.0
        try:
            positions = self._client.get_position_risk(symbol=symbol)
            if positions:
                return abs(float(positions[0]["positionAmt"]))
        except Exception as e:
            print(f"[EXEC] Position error {symbol}: {e}")
        return 0.0

    def get_position_info(self, symbol: str) -> Optional[Dict]:
        if not self.ready:
            return None
        try:
            positions = self._client.get_position_risk(symbol=symbol)
            if positions:
                p   = positions[0]
                amt = float(p.get("positionAmt", 0))
                if amt != 0:
                    return {
                        "symbol":           symbol,
                        "positionAmt":      amt,
                        "entryPrice":       float(p.get("entryPrice", 0)),
                        "unrealizedProfit": float(p.get("unRealizedProfit", 0)),
                        "leverage":         int(p.get("leverage", 1)),
                        "direction":        "LONG" if amt > 0 else "SHORT",
                    }
        except Exception as e:
            print(f"[EXEC] Position info error: {e}")
        return None

    def list_open_positions(self) -> List[Dict]:
        if not self.ready:
            return []
        out = []
        try:
            positions = self._client.get_position_risk()
            for p in positions or []:
                amt = float(p.get("positionAmt", 0) or 0)
                if amt == 0:
                    continue
                out.append({
                    "symbol":           p.get("symbol"),
                    "positionAmt":      amt,
                    "entryPrice":       float(p.get("entryPrice", 0)),
                    "unrealizedProfit": float(p.get("unRealizedProfit", 0)),
                    "leverage":         int(p.get("leverage", 1)),
                    "direction":        "LONG" if amt > 0 else "SHORT",
                })
        except Exception as e:
            print(f"[EXEC] list_open_positions error: {e}")
        return out

    def close_position(
        self, symbol: str, direction: str
    ) -> Optional[Dict]:
        size = self.get_position_size(symbol)
        if size <= 0:
            return None

        close_side = "SELL" if direction == "LONG" else "BUY"
        return self.market_order(symbol, close_side, size, reduce_only=True)


# ============================================================
# Executor Singleton
# ============================================================

_executor: Optional[BinanceExecutor] = None


def get_executor() -> Optional[BinanceExecutor]:
    global _executor
    mode = get_trading_mode()
    if mode.is_paper:
        return None
    if _executor is None:
        _executor = BinanceExecutor(testnet=mode.is_testnet)
    return _executor


def reset_executor():
    global _executor
    _executor = None


# ============================================================
# Paper / Legacy Entry
# ============================================================

def open_position(
    pending,
    price_map: Dict,
    fill_price: Optional[float] = None
) -> OrderResult:
    mode = get_trading_mode()

    if mode.is_paper:
        actual = fill_price or float(pending.trigger_price)
        return OrderResult(
            success=True,
            order_id=f"PAPER_{pending.id}",
            actual_entry=actual,
            mode="PAPER"
        )

    executor = get_executor()
    if not executor or not executor.ready:
        return OrderResult(
            success=False,
            error="Executor not ready",
            mode=mode.get_mode().value
        )

    try:
        balance = executor.get_balance()
        if balance <= 1:
            return OrderResult(
                success=False,
                error=f"Low balance: ${balance:.2f}",
                mode=mode.get_mode().value
            )

        usdt_notional, leverage = _calc_order_size(
            entry_price=float(pending.trigger_price),
            stop_loss=float(pending.stop_loss),
            balance=balance,
        )

        symbol_info = executor.get_symbol_info(pending.symbol)
        executor.set_leverage(pending.symbol, leverage)

        current_price = float(price_map.get(pending.symbol, pending.trigger_price))
        raw_qty = usdt_notional / current_price
        quantity = executor.round_quantity(pending.symbol, raw_qty, symbol_info)

        if quantity <= 0:
            return OrderResult(
                success=False,
                error=f"Qty too small: {raw_qty:.8f}",
                mode=mode.get_mode().value
            )

        entry_side = "BUY"  if pending.direction == "LONG" else "SELL"

        entry_order = executor.market_order(
            pending.symbol, entry_side, quantity
        )
        if not entry_order:
            return OrderResult(
                success=False,
                error="Entry order failed",
                mode=mode.get_mode().value
            )

        actual_entry = float(entry_order.get("avgPrice", current_price)) or current_price
        order_id = str(entry_order.get("orderId", ""))

        fee = quantity * actual_entry * 0.0004

        return OrderResult(
            success=True,
            order_id=order_id,
            actual_entry=actual_entry,
            actual_quantity=quantity,
            fee=fee,
            mode=mode.get_mode().value,
            leverage=leverage,
        )

    except Exception as e:
        traceback.print_exc()
        return OrderResult(
            success=False,
            error=str(e),
            mode=mode.get_mode().value
        )


# ============================================================
# LIMIT ENTRY — LIVE / TESTNET
# ============================================================

def place_limit_entry_order(pending) -> OrderResult:
    mode = get_trading_mode()

    if mode.is_paper:
        return OrderResult(success=True, mode="PAPER")

    executor = get_executor()
    if not executor or not executor.ready:
        return OrderResult(
            success=False,
            error="Executor not ready",
            mode=mode.get_mode().value
        )

    try:
        balance = executor.get_balance()
        if balance <= 1:
            return OrderResult(
                success=False,
                error=f"Low balance: ${balance:.2f}",
                mode=mode.get_mode().value
            )

        usdt_notional, leverage = _calc_order_size(
            entry_price=float(pending.trigger_price),
            stop_loss=float(pending.stop_loss),
            balance=balance,
        )

        symbol_info = executor.get_symbol_info(pending.symbol)
        executor.set_leverage(pending.symbol, leverage)

        raw_qty = usdt_notional / float(pending.trigger_price)
        quantity = executor.round_quantity(
            pending.symbol, raw_qty, symbol_info
        )

        if quantity <= 0:
            return OrderResult(
                success=False,
                error=f"Qty too small: {raw_qty:.8f}",
                mode=mode.get_mode().value
            )

        side = "BUY" if pending.direction == "LONG" else "SELL"
        price = executor.round_price(
            pending.symbol,
            float(pending.trigger_price),
            symbol_info
        )

        min_notional = _get_min_notional(symbol_info)
        actual_notional = float(price) * float(quantity)

        print(
            f"[LIMIT DEBUG] {pending.symbol} "
            f"price={price:.8f} qty={quantity:.8f} "
            f"notional={actual_notional:.4f} min={min_notional:.4f}"
        )

        if actual_notional < min_notional:
            return OrderResult(
                success=False,
                error=f"Actual notional too small: {actual_notional:.4f} < min {min_notional:.4f}",
                mode=mode.get_mode().value
            )

        order = executor.limit_order(
            pending.symbol, side, quantity, price
        )

        if not order:
            err = getattr(executor, "_last_error", None) or "Limit entry order failed"
            return OrderResult(
                success=False,
                error=err,
                mode=mode.get_mode().value
            )

        order_id = str(order.get("orderId", ""))

        print(
            f"💰 LIMIT ENTRY PLACED: {pending.symbol} {pending.direction} "
            f"@ {price:.6f} | Qty={quantity} | Lev={leverage}x | OrderID={order_id}"
        )

        return OrderResult(
            success=True,
            order_id=order_id,
            actual_entry=float(price),
            actual_quantity=float(quantity),
            leverage=leverage,
            mode=mode.get_mode().value
        )

    except Exception as e:
        traceback.print_exc()
        return OrderResult(
            success=False,
            error=str(e),
            mode=mode.get_mode().value
        )


# ============================================================
# ALGO ORDERS — SL / TP
# ============================================================

def _build_client_algo_id(prefix: str, symbol: str) -> str:
    ts = int(time.time())
    return f"QRL_{prefix}_{symbol}_{ts}"[:36]


def place_algo_stop_market_close_position(symbol: str, direction: str, trigger_price: float) -> Optional[Dict]:
    close_side = "SELL" if direction == "LONG" else "BUY"

    params = {
        "algoType": "CONDITIONAL",
        "symbol": symbol,
        "side": close_side,
        "type": "STOP_MARKET",
        "triggerPrice": trigger_price,
        "workingType": ALGO_WORKING_TYPE,
        "closePosition": "true",
        "priceProtect": "false",
        "clientAlgoId": _build_client_algo_id("SL", symbol),
    }

    return _signed_request("POST", "/fapi/v1/algoOrder", params)


def place_algo_take_profit_market_close_position(symbol: str, direction: str, trigger_price: float) -> Optional[Dict]:
    close_side = "SELL" if direction == "LONG" else "BUY"

    params = {
        "algoType": "CONDITIONAL",
        "symbol": symbol,
        "side": close_side,
        "type": "TAKE_PROFIT_MARKET",
        "triggerPrice": trigger_price,
        "workingType": ALGO_WORKING_TYPE,
        "closePosition": "true",
        "priceProtect": "false",
        "clientAlgoId": _build_client_algo_id("TP", symbol),
    }

    return _signed_request("POST", "/fapi/v1/algoOrder", params)


def place_close_position_exit_orders(symbol: str, direction: str, stop_loss: float, take_profit: float) -> Dict:
    mode = get_trading_mode()
    if mode.is_paper:
        return {"sl_order_id": None, "tp_order_id": None}

    executor = get_executor()
    if not executor or not executor.ready:
        return {"sl_order_id": None, "tp_order_id": None}

    symbol_info = executor.get_symbol_info(symbol)
    sl_price = executor.round_price(symbol, float(stop_loss), symbol_info)
    tp_price = executor.round_price(symbol, float(take_profit), symbol_info)

    sl_order = None
    tp_order = None

    try:
        sl_order = place_algo_stop_market_close_position(
            symbol=symbol,
            direction=direction,
            trigger_price=sl_price
        )
    except Exception as e:
        print(f"[EXEC] Algo SL order error {symbol}: {e}")

    try:
        tp_order = place_algo_take_profit_market_close_position(
            symbol=symbol,
            direction=direction,
            trigger_price=tp_price
        )
    except Exception as e:
        print(f"[EXEC] Algo TP order error {symbol}: {e}")

    return {
        "sl_order_id": str(sl_order.get("algoId", "")) if sl_order else None,
        "tp_order_id": str(tp_order.get("algoId", "")) if tp_order else None,
    }


def get_algo_order_status(algo_id: str) -> Dict:
    mode = get_trading_mode()
    if mode.is_paper:
        return {
            "algo_status": "UNKNOWN",
            "actual_order_id": None,
            "actual_price": None,
            "actual_qty": None,
        }

    try:
        data = _signed_request("GET", "/fapi/v1/algoOrder", {
            "algoId": algo_id
        })
        return {
            "algo_status": data.get("algoStatus"),
            "actual_order_id": data.get("actualOrderId"),
            "actual_price": float(data.get("actualPrice", 0) or 0),
            "actual_qty": float(data.get("actualQty", 0) or 0),
            "trigger_price": float(data.get("triggerPrice", 0) or 0),
            "working_type": data.get("workingType"),
            "trigger_time": data.get("triggerTime"),
            "raw": data,
        }
    except Exception as e:
        print(f"[EXEC] get_algo_order_status error algoId={algo_id}: {e}")
        return {
            "algo_status": "UNKNOWN",
            "actual_order_id": None,
            "actual_price": None,
            "actual_qty": None,
        }


def get_open_algo_orders(symbol: Optional[str] = None) -> list:
    mode = get_trading_mode()
    if mode.is_paper:
        return []

    try:
        params = {}
        if symbol:
            params["symbol"] = symbol
        data = _signed_request("GET", "/fapi/v1/openAlgoOrders", params)
        return data if isinstance(data, list) else []
    except Exception as e:
        print(f"[EXEC] get_open_algo_orders error {symbol}: {e}")
        return []


def cancel_algo_order(algo_id: str) -> bool:
    mode = get_trading_mode()
    if mode.is_paper:
        return True

    try:
        _signed_request("DELETE", "/fapi/v1/algoOrder", {
            "algoId": algo_id
        })
        return True
    except Exception as e:
        if "-2011" not in str(e):
            print(f"[EXEC] cancel_algo_order warning algoId={algo_id}: {e}")
        return False


def cancel_all_algo_orders(symbol: str) -> bool:
    mode = get_trading_mode()
    if mode.is_paper:
        return True

    try:
        _signed_request("DELETE", "/fapi/v1/algoOpenOrders", {
            "symbol": symbol
        })
        return True
    except Exception as e:
        print(f"[EXEC] cancel_all_algo_orders warning {symbol}: {e}")
        return False


# ============================================================
# ENTRY ORDER STATUS
# ============================================================

def get_entry_order_status(symbol: str, order_id: str) -> Dict:
    mode = get_trading_mode()
    if mode.is_paper:
        return {
            "status": "UNKNOWN",
            "avg_price": None,
            "executed_qty": 0.0,
            "orig_qty": 0.0,
        }

    executor = get_executor()
    if not executor or not executor.ready:
        return {
            "status": "UNKNOWN",
            "avg_price": None,
            "executed_qty": 0.0,
            "orig_qty": 0.0,
        }

    try:
        order = executor.query_order(symbol, order_id)
        if not order:
            return {
                "status": "UNKNOWN",
                "avg_price": None,
                "executed_qty": 0.0,
                "orig_qty": 0.0,
            }

        return {
            "status": order.get("status", "UNKNOWN"),
            "avg_price": float(order.get("avgPrice", 0) or 0),
            "executed_qty": float(order.get("executedQty", 0) or 0),
            "orig_qty": float(order.get("origQty", 0) or 0),
        }
    except Exception as e:
        print(f"[EXEC] get_entry_order_status error {symbol}/{order_id}: {e}")
        return {
            "status": "UNKNOWN",
            "avg_price": None,
            "executed_qty": 0.0,
            "orig_qty": 0.0,
        }


# ============================================================
# CANCEL HELPERS
# ============================================================

def cancel_order_by_id(symbol: str, order_id: Optional[str]) -> bool:
    if not order_id:
        return False

    mode = get_trading_mode()
    if mode.is_paper:
        return True

    executor = get_executor()
    if not executor or not executor.ready:
        return False

    if executor.cancel_order(symbol, order_id):
        return True

    return cancel_algo_order(order_id)


def cancel_exit_orders(pending) -> bool:
    ok1 = cancel_order_by_id(pending.symbol, getattr(pending, "sl_order_id", None))
    ok2 = cancel_order_by_id(pending.symbol, getattr(pending, "tp_order_id", None))
    return ok1 or ok2


def cancel_entry_and_exits(pending) -> bool:
    ok = False

    ok = cancel_order_by_id(
        pending.symbol,
        getattr(pending, "exchange_order_id", None)
    ) or ok

    ok = cancel_order_by_id(
        pending.symbol,
        getattr(pending, "sl_order_id", None)
    ) or ok

    ok = cancel_order_by_id(
        pending.symbol,
        getattr(pending, "tp_order_id", None)
    ) or ok

    return ok


# ============================================================
# CLOSE POSITION
# ============================================================

def close_position(trade, reason: str) -> OrderResult:
    mode = get_trading_mode()

    if mode.is_paper:
        return OrderResult(success=True, mode="PAPER")

    executor = get_executor()
    if not executor or not executor.ready:
        return OrderResult(
            success=False,
            error="Executor not ready",
            mode=mode.get_mode().value
        )

    try:
        executor.cancel_all_orders(trade.symbol)
        cancel_all_algo_orders(trade.symbol)

        result = executor.close_position(
            symbol=trade.symbol,
            direction=trade.direction
        )

        if result:
            actual_exit = float(result.get("avgPrice", 0)) or 0
            fee = float(result.get("commission", 0))
            print(
                f"💰 LIVE CLOSE: {trade.symbol} {trade.direction} "
                f"| Reason={reason} | Exit={actual_exit:.4f}"
            )
            return OrderResult(
                success=True,
                order_id=str(result.get("orderId", "")),
                actual_entry=actual_exit,
                fee=fee,
                mode=mode.get_mode().value
            )
        else:
            pos = executor.get_position_size(trade.symbol)
            if pos == 0:
                print(f"⚠️ Position already closed: {trade.symbol}")
                return OrderResult(success=True, mode=mode.get_mode().value)

            return OrderResult(
                success=False,
                error="Close failed",
                mode=mode.get_mode().value
            )

    except Exception as e:
        traceback.print_exc()
        return OrderResult(
            success=False,
            error=str(e),
            mode=mode.get_mode().value
        )


# ============================================================
# POSITION SYNC
# ============================================================

def sync_position(trade) -> Optional[Dict]:
    mode = get_trading_mode()
    if mode.is_paper:
        return None

    executor = get_executor()
    if not executor or not executor.ready:
        return None

    return executor.get_position_info(trade.symbol)


def get_position_info_by_symbol(symbol: str) -> Optional[Dict]:
    mode = get_trading_mode()
    if mode.is_paper:
        return None

    executor = get_executor()
    if not executor or not executor.ready:
        return None

    return executor.get_position_info(symbol)


def list_open_positions() -> List[Dict]:
    mode = get_trading_mode()
    if mode.is_paper:
        return []

    executor = get_executor()
    if not executor or not executor.ready:
        return []

    return executor.list_open_positions()


def check_position_closed(trade) -> bool:
    mode = get_trading_mode()
    if mode.is_paper:
        return False

    executor = get_executor()
    if not executor or not executor.ready:
        return False

    size = executor.get_position_size(trade.symbol)
    return size == 0


def get_open_orders(symbol: str) -> list:
    mode = get_trading_mode()
    if mode.is_paper:
        return []

    executor = get_executor()
    if not executor or not executor.ready:
        return []

    return executor.get_open_orders(symbol)