"""
Order Execution Service
=======================
Paper:   ghi DB only
Testnet: Binance Testnet API
Live:    Binance Mainnet API

Install: pip install binance-futures-connector
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Tuple

from app.core.trading_mode import get_trading_mode, TradingMode


@dataclass
class OrderResult:
    success:         bool
    order_id:        Optional[str]   = None
    actual_entry:    Optional[float] = None
    actual_quantity: Optional[float] = None
    fee:             float = 0.0
    error:           Optional[str]   = None
    mode:            str   = "PAPER"
    leverage:        int   = 1
    sl_order_id:     Optional[str]   = None
    tp_order_id:     Optional[str]   = None


class PositionSizer:
    def __init__(self, account_balance=10000, risk_pct=0.01, max_leverage=3):
        self.balance      = account_balance
        self.risk_pct     = risk_pct
        self.max_leverage = max_leverage

    def calc(self, entry_price, stop_loss) -> Tuple[float, int]:
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


class BinanceExecutor:
    """Wrapper cho Binance Futures API."""

    def __init__(self, testnet=False):
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
        print(f"✅ Binance client init ({'Testnet' if testnet else 'Mainnet'})")

    @property
    def ready(self):
        return self._client is not None

    def get_balance(self) -> float:
        if not self.ready: return 0.0
        try:
            account = self._client.account()
            for asset in account.get("assets", []):
                if asset["asset"] == "USDT":
                    return float(asset["availableBalance"])
        except Exception as e:
            print(f"[EXEC] Balance error: {e}")
        return 0.0

    def set_leverage(self, symbol, leverage) -> bool:
        if not self.ready: return False
        try:
            self._client.change_leverage(symbol=symbol, leverage=leverage)
            return True
        except Exception as e:
            print(f"[EXEC] Leverage error {symbol}: {e}")
            return False

    def get_symbol_info(self, symbol) -> Optional[Dict]:
        if not self.ready: return None
        try:
            info = self._client.exchange_info()
            for s in info.get("symbols", []):
                if s["symbol"] == symbol:
                    return s
        except Exception as e:
            print(f"[EXEC] Info error {symbol}: {e}")
        return None

    def round_quantity(self, symbol, quantity, symbol_info=None) -> float:
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

    def round_price(self, symbol, price, symbol_info=None) -> float:
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

    def market_order(self, symbol, side, quantity, reduce_only=False) -> Optional[Dict]:
        if not self.ready: return None
        try:
            params = {"symbol": symbol, "side": side,
                      "type": "MARKET", "quantity": quantity}
            if reduce_only:
                params["reduceOnly"] = "true"
            return self._client.new_order(**params)
        except Exception as e:
            print(f"[EXEC] Market order error {symbol} {side}: {e}")
            return None

    def stop_market(self, symbol, side, stop_price) -> Optional[Dict]:
        if not self.ready: return None
        try:
            return self._client.new_order(
                symbol=symbol, side=side,
                type="STOP_MARKET",
                stopPrice=stop_price,
                closePosition="true"
            )
        except Exception as e:
            print(f"[EXEC] Stop order error {symbol}: {e}")
            return None

    def take_profit_market(self, symbol, side, stop_price) -> Optional[Dict]:
        if not self.ready: return None
        try:
            return self._client.new_order(
                symbol=symbol, side=side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=stop_price,
                closePosition="true"
            )
        except Exception as e:
            print(f"[EXEC] TP order error {symbol}: {e}")
            return None

    def cancel_all_orders(self, symbol) -> bool:
        if not self.ready: return False
        try:
            self._client.cancel_open_orders(symbol=symbol)
            return True
        except Exception as e:
            print(f"[EXEC] Cancel error {symbol}: {e}")
            return False

    def get_position_size(self, symbol) -> float:
        if not self.ready: return 0.0
        try:
            positions = self._client.get_position_risk(symbol=symbol)
            if positions:
                return abs(float(positions[0]["positionAmt"]))
        except Exception as e:
            print(f"[EXEC] Position error {symbol}: {e}")
        return 0.0

    def get_position_info(self, symbol) -> Optional[Dict]:
        if not self.ready: return None
        try:
            positions = self._client.get_position_risk(symbol=symbol)
            if positions:
                p = positions[0]
                amt = float(p.get("positionAmt", 0))
                if amt != 0:
                    return {
                        "symbol": symbol,
                        "positionAmt": amt,
                        "entryPrice": float(p.get("entryPrice", 0)),
                        "unrealizedProfit": float(p.get("unRealizedProfit", 0)),
                        "leverage": int(p.get("leverage", 1)),
                        "direction": "LONG" if amt > 0 else "SHORT",
                    }
        except Exception as e:
            print(f"[EXEC] Position info error: {e}")
        return None

    def get_open_orders(self, symbol) -> list:
        if not self.ready: return []
        try:
            return self._client.get_orders(symbol=symbol)
        except Exception as e:
            print(f"[EXEC] Open orders error: {e}")
            return []

    def close_position(self, symbol, direction) -> Optional[Dict]:
        size = self.get_position_size(symbol)
        if size <= 0: return None
        close_side = "SELL" if direction == "LONG" else "BUY"
        self.cancel_all_orders(symbol)
        return self.market_order(symbol, close_side, size, reduce_only=True)


# Cache executor singleton
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
# PUBLIC: OPEN POSITION
# ============================================================

def open_position(pending, price_map: Dict) -> OrderResult:
    mode = get_trading_mode()

    if mode.is_paper:
        return OrderResult(
            success=True,
            order_id=f"PAPER_{pending.id}",
            actual_entry=pending.trigger_price,
            mode="PAPER"
        )

    executor = get_executor()
    if not executor or not executor.ready:
        return OrderResult(success=False, error="Executor not ready",
                          mode=mode.get_mode().value)

    try:
        balance = executor.get_balance()
        if balance <= 10:
            return OrderResult(success=False, error=f"Low balance: ${balance:.2f}",
                              mode=mode.get_mode().value)

        risk_pct = float(os.getenv("RISK_PER_TRADE_PCT", "0.01"))
        max_lev  = int(os.getenv("DEFAULT_LEVERAGE", "3"))
        max_pos  = float(os.getenv("MAX_POSITION_USDT", "500"))

        sizer = PositionSizer(
            account_balance=balance,
            risk_pct=risk_pct,
            max_leverage=max_lev
        )

        usdt_notional, leverage = sizer.calc(
            entry_price=pending.trigger_price,
            stop_loss=pending.stop_loss
        )

        usdt_notional = min(usdt_notional, max_pos)

        symbol_info = executor.get_symbol_info(pending.symbol)
        executor.set_leverage(pending.symbol, leverage)

        current_price = float(
            price_map.get(pending.symbol, pending.trigger_price)
        )
        raw_qty  = usdt_notional / current_price
        quantity = executor.round_quantity(
            pending.symbol, raw_qty, symbol_info
        )

        if quantity <= 0:
            return OrderResult(success=False,
                error=f"Qty too small: {raw_qty:.8f}",
                mode=mode.get_mode().value)

        entry_side = "BUY" if pending.direction == "LONG" else "SELL"
        sl_side    = "SELL" if pending.direction == "LONG" else "BUY"

        sl_price = executor.round_price(
            pending.symbol, pending.stop_loss, symbol_info
        )
        tp_price = executor.round_price(
            pending.symbol, pending.take_profit, symbol_info
        )

        entry_order = executor.market_order(
            pending.symbol, entry_side, quantity
        )

        if not entry_order:
            return OrderResult(success=False, error="Entry order failed",
                              mode=mode.get_mode().value)

        actual_entry = float(entry_order.get("avgPrice", current_price)) or current_price
        order_id     = str(entry_order.get("orderId", ""))

        sl_order = executor.stop_market(pending.symbol, sl_side, sl_price)
        tp_order = executor.take_profit_market(pending.symbol, sl_side, tp_price)

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
            sl_order_id=str(sl_order.get("orderId","")) if sl_order else None,
            tp_order_id=str(tp_order.get("orderId","")) if tp_order else None,
        )

    except Exception as e:
        import traceback; traceback.print_exc()
        return OrderResult(success=False, error=str(e),
                          mode=mode.get_mode().value)


# ============================================================
# PUBLIC: CLOSE POSITION
# ============================================================

def close_position(trade, reason: str) -> OrderResult:
    mode = get_trading_mode()

    if mode.is_paper:
        return OrderResult(success=True, mode="PAPER")

    executor = get_executor()
    if not executor or not executor.ready:
        return OrderResult(success=False, error="Executor not ready",
                          mode=mode.get_mode().value)

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
            return OrderResult(success=False, error="Close failed",
                              mode=mode.get_mode().value)

    except Exception as e:
        import traceback; traceback.print_exc()
        return OrderResult(success=False, error=str(e),
                          mode=mode.get_mode().value)


# ============================================================
# PUBLIC: SYNC POSITION (for live monitoring)
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
