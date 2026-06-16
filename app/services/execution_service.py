"""
Order Execution Service
=======================
Paper:     ghi DB only, fill tại fill_price
Testnet:   Binance Testnet API
Live:      Binance Mainnet API

Position sizing:
  - Đọc từ POSITION_SIZE_CONFIG trong app_config
  - 2 mode: fixed_usdt / risk_based
  - Toggle được từ dashboard, không cần restart

Entry (LIVE/TESTNET):
  - LIMIT order tại trigger_price (đã reprice)
  - SL/TP đặt cùng lúc với closePosition=true

Install: pip install binance-futures-connector
"""

import os
import traceback
from dataclasses import dataclass
from typing import Optional, Dict, Tuple

from app.core.trading_mode import get_trading_mode, TradingMode


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
# Position Sizer (risk-based mode)
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
# Order Size Calculator — đọc từ POSITION_SIZE_CONFIG
# ============================================================

def _calc_order_size(
    entry_price: float,
    stop_loss: float,
    balance: float
) -> Tuple[float, int]:
    """
    Tính notional + leverage theo POSITION_SIZE_CONFIG.

    2 mode:
      fixed_usdt:  cố định $ mỗi lệnh
      risk_based:  % vốn chịu rủi ro mỗi lệnh

    Config đọc từ app_config, toggle được từ dashboard.
    """
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
        # ── RISK BASED ────────────────────────────────
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
    """
    Lấy min notional từ exchangeInfo.
    Fallback = 5 USDT nếu không đọc được.
    """
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
# Binance Executor
# ============================================================

class BinanceExecutor:
    """Wrapper cho Binance Futures API."""

    def __init__(self, testnet: bool = False):
        self.testnet = testnet
        self._client = None
        self._init_client()

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

    # ── Orders ───────────────────────────────────────────

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

    def limit_order(
        self, symbol: str, side: str, quantity: float,
        price: float, tif: str = "GTC"
    ) -> Optional[Dict]:
        if not self.ready:
            return None
        try:
            return self._client.new_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                quantity=quantity,
                price=price,
                timeInForce=tif
            )
        except Exception as e:
            print(f"[EXEC] Limit order error {symbol} {side}: {e}")
            return None

    def stop_market(
        self, symbol: str, side: str, stop_price: float
    ) -> Optional[Dict]:
        if not self.ready:
            return None
        try:
            return self._client.new_order(
                symbol=symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=stop_price,
                closePosition="true"
            )
        except Exception as e:
            print(f"[EXEC] Stop order error {symbol}: {e}")
            return None

    def take_profit_market(
        self, symbol: str, side: str, stop_price: float
    ) -> Optional[Dict]:
        if not self.ready:
            return None
        try:
            return self._client.new_order(
                symbol=symbol,
                side=side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=stop_price,
                closePosition="true"
            )
        except Exception as e:
            print(f"[EXEC] TP order error {symbol}: {e}")
            return None

    def cancel_order(self, symbol: str, order_id: str) -> bool:
        if not self.ready:
            return False
        try:
            self._client.cancel_order(symbol=symbol, orderId=order_id)
            return True
        except Exception as e:
            print(f"[EXEC] Cancel order warning {symbol}/{order_id}: {e}")
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

    def get_open_orders(self, symbol: str) -> list:
        if not self.ready:
            return []
        try:
            return self._client.get_orders(symbol=symbol)
        except Exception as e:
            print(f"[EXEC] Open orders error: {e}")
            return []

    def close_position(
        self, symbol: str, direction: str
    ) -> Optional[Dict]:
        size = self.get_position_size(symbol)
        if size <= 0:
            return None

        close_side = "SELL" if direction == "LONG" else "BUY"
        self.cancel_all_orders(symbol)
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
# PUBLIC: OPEN POSITION (PAPER — backward compatible)
# ============================================================

def open_position(
    pending,
    price_map: Dict,
    fill_price: Optional[float] = None
) -> OrderResult:
    """
    PAPER: fill local tại fill_price hoặc trigger_price.
    LIVE/TESTNET legacy: market order (kept for backward compat).
    """
    mode = get_trading_mode()

    if mode.is_paper:
        actual = fill_price or float(pending.trigger_price)
        return OrderResult(
            success=True,
            order_id=f"PAPER_{pending.id}",
            actual_entry=actual,
            mode="PAPER"
        )

    # Legacy live/testnet market entry
    executor = get_executor()
    if not executor or not executor.ready:
        return OrderResult(
            success=False,
            error="Executor not ready",
            mode=mode.get_mode().value
        )

    try:
        balance = executor.get_balance()
        if balance <= 10:
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

        current_price = float(
            price_map.get(pending.symbol, pending.trigger_price)
        )
        raw_qty = usdt_notional / current_price
        quantity = executor.round_quantity(
            pending.symbol, raw_qty, symbol_info
        )

        if quantity <= 0:
            return OrderResult(
                success=False,
                error=f"Qty too small: {raw_qty:.8f}",
                mode=mode.get_mode().value
            )

        entry_side = "BUY"  if pending.direction == "LONG" else "SELL"
        close_side = "SELL" if pending.direction == "LONG" else "BUY"

        sl_price = executor.round_price(
            pending.symbol, float(pending.stop_loss), symbol_info
        )
        tp_price = executor.round_price(
            pending.symbol, float(pending.take_profit), symbol_info
        )

        entry_order = executor.market_order(
            pending.symbol, entry_side, quantity
        )
        if not entry_order:
            return OrderResult(
                success=False,
                error="Entry order failed",
                mode=mode.get_mode().value
            )

        actual_entry = (
            float(entry_order.get("avgPrice", current_price))
            or current_price
        )
        order_id = str(entry_order.get("orderId", ""))

        sl_order = executor.stop_market(
            pending.symbol, close_side, sl_price
        )
        tp_order = executor.take_profit_market(
            pending.symbol, close_side, tp_price
        )

        fee = quantity * actual_entry * 0.0004

        print(
            f"💰 LIVE ENTRY: {pending.symbol} {pending.direction} "
            f"@ {actual_entry:.4f} | Qty={quantity} | Lev={leverage}x | "
            f"SL={sl_price} TP={tp_price} | Fee=${fee:.2f}"
        )

        return OrderResult(
            success=True,
            order_id=order_id,
            actual_entry=actual_entry,
            actual_quantity=quantity,
            fee=fee,
            mode=mode.get_mode().value,
            leverage=leverage,
            sl_order_id=str(sl_order.get("orderId", "")) if sl_order else None,
            tp_order_id=str(tp_order.get("orderId", "")) if tp_order else None,
        )

    except Exception as e:
        traceback.print_exc()
        return OrderResult(
            success=False,
            error=str(e),
            mode=mode.get_mode().value
        )


# ============================================================
# PUBLIC: CLOSE POSITION
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
# PUBLIC: SYNC POSITION
# ============================================================

def sync_position(trade) -> Optional[Dict]:
    mode = get_trading_mode()
    if mode.is_paper:
        return None
    executor = get_executor()
    if not executor or not executor.ready:
        return None
    return executor.get_position_info(trade.symbol)


def check_position_closed(trade) -> bool:
    mode = get_trading_mode()
    if mode.is_paper:
        return False
    executor = get_executor()
    if not executor or not executor.ready:
        return False
    size = executor.get_position_size(trade.symbol)
    return size == 0


# ============================================================
# LIMIT ENTRY FLOW — LIVE / TESTNET
# ============================================================

def place_limit_entry_order(pending) -> OrderResult:
    """
    Place LIMIT entry order on exchange.
    trigger_price / stop_loss / take_profit trong pending
    phải đã được reprice + round TRƯỚC khi gọi hàm này.
    """
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
        if balance <= 10:
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
            return OrderResult(
                success=False,
                error="Limit entry order failed",
                mode=mode.get_mode().value
            )

        order_id = str(order.get("orderId", ""))

        print(
            f"💰 LIMIT ENTRY PLACED: {pending.symbol} {pending.direction} "
            f"@ {price:.6f} | Qty={quantity} | Lev={leverage}x "
            f"| OrderID={order_id}"
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


def place_close_position_exit_orders(
    symbol: str,
    direction: str,
    stop_loss: float,
    take_profit: float
) -> Dict:
    """
    Place STOP_MARKET + TAKE_PROFIT_MARKET with closePosition=true.
    Nếu exchange reject vì chưa có position: trả None IDs.
    """
    mode = get_trading_mode()
    if mode.is_paper:
        return {"sl_order_id": None, "tp_order_id": None}

    executor = get_executor()
    if not executor or not executor.ready:
        return {"sl_order_id": None, "tp_order_id": None}

    symbol_info = executor.get_symbol_info(symbol)
    close_side = "SELL" if direction == "LONG" else "BUY"

    sl_price = executor.round_price(symbol, float(stop_loss), symbol_info)
    tp_price = executor.round_price(symbol, float(take_profit), symbol_info)

    sl_order = executor.stop_market(symbol, close_side, sl_price)
    tp_order = executor.take_profit_market(symbol, close_side, tp_price)

    return {
        "sl_order_id": str(sl_order.get("orderId", "")) if sl_order else None,
        "tp_order_id": str(tp_order.get("orderId", "")) if tp_order else None,
    }


def get_entry_order_status(symbol: str, order_id: str) -> Dict:
    """Query exchange entry LIMIT order status."""
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


def cancel_order_by_id(symbol: str, order_id: Optional[str]) -> bool:
    if not order_id:
        return False

    mode = get_trading_mode()
    if mode.is_paper:
        return True

    executor = get_executor()
    if not executor or not executor.ready:
        return False

    return executor.cancel_order(symbol, order_id)


# ============================================================
# CONVENIENCE HELPERS
# ============================================================

def cancel_exit_orders(pending) -> bool:
    ok1 = cancel_order_by_id(
        pending.symbol,
        getattr(pending, "sl_order_id", None)
    )
    ok2 = cancel_order_by_id(
        pending.symbol,
        getattr(pending, "tp_order_id", None)
    )
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