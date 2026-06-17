"""
Account Service
===============
Expose account-level data từ Binance Futures:
- info
- positions
- open orders
- trades
- income

Dùng key từ DB/env qua get_connection_value().
Mặc định target = live, có thể truyền target=testnet.
"""

import os
import time
import hmac
import hashlib
import requests
from typing import Optional, Dict, Any
from urllib.parse import urlencode

from app.services.config_service import get_connection_value
from app.core.trading_mode import get_current_mode, TradingMode


_HTTP = requests.Session()
SIGNED_TIMEOUT = 10


# ============================================================
# INTERNAL HELPERS
# ============================================================

def _resolve_target(target: Optional[str]) -> str:
    """
    target ưu tiên:
    1. query param target nếu có
    2. current trading mode nếu là TESTNET/LIVE
    3. fallback = live
    """
    if target:
        t = str(target).strip().lower()
        if t in ("live", "testnet"):
            return t

    mode = get_current_mode()
    if mode == TradingMode.TESTNET:
        return "testnet"
    if mode == TradingMode.LIVE:
        return "live"

    return "live"


def _get_binance_creds(target: Optional[str] = None) -> Dict[str, str]:
    t = _resolve_target(target)

    if t == "testnet":
        return {
            "target":    "testnet",
            "api_key":   get_connection_value("BINANCE_TESTNET_API_KEY", ""),
            "api_secret":get_connection_value("BINANCE_TESTNET_API_SECRET", ""),
            "base_url":  "https://testnet.binancefuture.com",
        }

    return {
        "target":     "live",
        "api_key":    get_connection_value("BINANCE_API_KEY", ""),
        "api_secret": get_connection_value("BINANCE_API_SECRET", ""),
        "base_url":   "https://fapi.binance.com",
    }


def _signed_request(method: str, path: str, params: Optional[Dict[str, Any]] = None, target: Optional[str] = None):
    cfg = _get_binance_creds(target)

    api_key    = cfg["api_key"]
    api_secret = cfg["api_secret"]
    base_url   = cfg["base_url"]

    if not api_key or not api_secret:
        raise RuntimeError(f"Missing Binance API credentials for target={cfg['target']}")

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

    headers = {"X-MBX-APIKEY": api_key}
    url = f"{base_url}{path}"

    resp = _HTTP.request(
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
        raise RuntimeError(f"Binance request failed [{resp.status_code}] code={code} msg={msg}")

    return data


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


# ============================================================
# PUBLIC API
# ============================================================

def get_account_info(target: Optional[str] = None) -> Dict:
    """
    Summary account info.
    """
    cfg = _get_binance_creds(target)
    target = cfg["target"]

    account = _signed_request("GET", "/fapi/v2/account", {}, target=target)

    balances = account.get("assets", [])
    usdt = next((a for a in balances if a.get("asset") == "USDT"), None)

    positions = [
        p for p in account.get("positions", [])
        if abs(_safe_float(p.get("positionAmt", 0))) > 0
    ]

    return {
        "target": target,
        "can_trade": True,
        "assets_count": len(balances),
        "positions_count": len(positions),
        "usdt": {
            "walletBalance":      _safe_float(usdt.get("walletBalance"))      if usdt else 0,
            "availableBalance":   _safe_float(usdt.get("availableBalance"))   if usdt else 0,
            "marginBalance":      _safe_float(usdt.get("marginBalance"))      if usdt else 0,
            "unrealizedProfit":   _safe_float(usdt.get("unrealizedProfit"))   if usdt else 0,
            "crossWalletBalance": _safe_float(usdt.get("crossWalletBalance")) if usdt else 0,
        },
        "totals": {
            "totalWalletBalance":    _safe_float(account.get("totalWalletBalance")),
            "totalMarginBalance":    _safe_float(account.get("totalMarginBalance")),
            "totalUnrealizedProfit": _safe_float(account.get("totalUnrealizedProfit")),
            "totalAvailableBalance": _safe_float(account.get("availableBalance")),
        }
    }


def get_positions(target: Optional[str] = None) -> Dict:
    cfg = _get_binance_creds(target)
    target = cfg["target"]

    raw = _signed_request("GET", "/fapi/v2/positionRisk", {}, target=target)

    positions = []
    for p in raw:
        amt = _safe_float(p.get("positionAmt", 0))
        if amt == 0:
            continue
        positions.append({
            "symbol":            p.get("symbol"),
            "side":              "LONG" if amt > 0 else "SHORT",
            "positionAmt":       abs(amt),
            "entryPrice":        _safe_float(p.get("entryPrice")),
            "markPrice":         _safe_float(p.get("markPrice")),
            "unRealizedProfit":  _safe_float(p.get("unRealizedProfit")),
            "liquidationPrice":  _safe_float(p.get("liquidationPrice")),
            "leverage":          int(float(p.get("leverage", 1))),
            "marginType":        p.get("marginType"),
            "isolatedMargin":    _safe_float(p.get("isolatedMargin")),
            "updateTime":        p.get("updateTime"),
        })

    return {
        "target": target,
        "count": len(positions),
        "items": positions,
    }


def get_open_orders(target: Optional[str] = None, symbol: Optional[str] = None) -> Dict:
    """
    Merge:
    - normal open orders
    - algo open orders
    """
    cfg = _get_binance_creds(target)
    target = cfg["target"]

    params = {}
    if symbol:
        params["symbol"] = symbol.upper()

    normal = _signed_request("GET", "/fapi/v1/openOrders", params, target=target)
    algo   = _signed_request("GET", "/fapi/v1/openAlgoOrders", params, target=target)

    normal_items = [{
        "kind":        "NORMAL",
        "orderId":     o.get("orderId"),
        "symbol":      o.get("symbol"),
        "side":        o.get("side"),
        "type":        o.get("type"),
        "status":      o.get("status"),
        "price":       _safe_float(o.get("price")),
        "stopPrice":   _safe_float(o.get("stopPrice")),
        "origQty":     _safe_float(o.get("origQty")),
        "executedQty": _safe_float(o.get("executedQty")),
        "time":        o.get("time"),
    } for o in (normal if isinstance(normal, list) else [])]

    algo_items = [{
        "kind":         "ALGO",
        "algoId":       o.get("algoId"),
        "clientAlgoId": o.get("clientAlgoId"),
        "symbol":       o.get("symbol"),
        "side":         o.get("side"),
        "orderType":    o.get("orderType"),
        "algoStatus":   o.get("algoStatus"),
        "triggerPrice": _safe_float(o.get("triggerPrice")),
        "price":        _safe_float(o.get("price")),
        "quantity":     _safe_float(o.get("quantity")),
        "actualOrderId":o.get("actualOrderId"),
        "workingType":  o.get("workingType"),
        "closePosition":o.get("closePosition"),
        "createTime":   o.get("createTime"),
        "updateTime":   o.get("updateTime"),
    } for o in (algo if isinstance(algo, list) else [])]

    return {
        "target": target,
        "symbol": symbol.upper() if symbol else None,
        "normal_count": len(normal_items),
        "algo_count": len(algo_items),
        "normal": normal_items,
        "algo": algo_items,
    }


def get_trades(
    target: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 100,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> Dict:
    """
    USER TRADES.
    Binance futures yêu cầu symbol.
    """
    cfg = _get_binance_creds(target)
    target = cfg["target"]

    if not symbol:
        raise RuntimeError("symbol is required for /api/account/trades")

    params = {
        "symbol": symbol.upper(),
        "limit": min(max(limit, 1), 1000),
    }
    if start_time:
        params["startTime"] = int(start_time)
    if end_time:
        params["endTime"] = int(end_time)

    data = _signed_request("GET", "/fapi/v1/userTrades", params, target=target)

    items = [{
        "symbol":      t.get("symbol"),
        "id":          t.get("id"),
        "orderId":     t.get("orderId"),
        "side":        t.get("side"),
        "price":       _safe_float(t.get("price")),
        "qty":         _safe_float(t.get("qty")),
        "quoteQty":    _safe_float(t.get("quoteQty")),
        "realizedPnl": _safe_float(t.get("realizedPnl")),
        "commission":  _safe_float(t.get("commission")),
        "commissionAsset": t.get("commissionAsset"),
        "time":        t.get("time"),
        "maker":       t.get("maker"),
        "buyer":       t.get("buyer"),
    } for t in (data if isinstance(data, list) else [])]

    return {
        "target": target,
        "symbol": symbol.upper(),
        "count": len(items),
        "items": items,
    }


def get_income(
    target: Optional[str] = None,
    symbol: Optional[str] = None,
    income_type: Optional[str] = None,
    limit: int = 100,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
) -> Dict:
    """
    Income history.
    incomeType examples:
      TRANSFER, WELCOME_BONUS, REALIZED_PNL, FUNDING_FEE, COMMISSION
    """
    cfg = _get_binance_creds(target)
    target = cfg["target"]

    params = {
        "limit": min(max(limit, 1), 1000),
    }
    if symbol:
        params["symbol"] = symbol.upper()
    if income_type:
        params["incomeType"] = income_type
    if start_time:
        params["startTime"] = int(start_time)
    if end_time:
        params["endTime"] = int(end_time)

    data = _signed_request("GET", "/fapi/v1/income", params, target=target)

    items = [{
        "symbol":     i.get("symbol"),
        "incomeType": i.get("incomeType"),
        "income":     _safe_float(i.get("income")),
        "asset":      i.get("asset"),
        "info":       i.get("info"),
        "time":       i.get("time"),
        "tranId":     i.get("tranId"),
        "tradeId":    i.get("tradeId"),
    } for i in (data if isinstance(data, list) else [])]

    return {
        "target": target,
        "symbol": symbol.upper() if symbol else None,
        "incomeType": income_type,
        "count": len(items),
        "items": items,
    }