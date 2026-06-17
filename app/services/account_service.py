"""
Account Service
===============
Exchange-truth account data from Binance Futures only.

Endpoints supported:
- info
- positions
- open-orders
- trades (requires symbol)
- income

Target:
- live
- testnet
"""

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
            "target": "testnet",
            "api_key": get_connection_value("BINANCE_TESTNET_API_KEY", ""),
            "api_secret": get_connection_value("BINANCE_TESTNET_API_SECRET", ""),
            "base_url": "https://testnet.binancefuture.com",
        }

    return {
        "target": "live",
        "api_key": get_connection_value("BINANCE_API_KEY", ""),
        "api_secret": get_connection_value("BINANCE_API_SECRET", ""),
        "base_url": "https://fapi.binance.com",
    }


def _signed_request(method: str, path: str, params: Optional[Dict[str, Any]] = None, target: Optional[str] = None):
    cfg = _get_binance_creds(target)

    api_key = cfg["api_key"]
    api_secret = cfg["api_secret"]
    base_url = cfg["base_url"]

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
        msg = data.get("msg") or str(data)
        raise RuntimeError(f"Binance request failed [{resp.status_code}] code={code} msg={msg}")

    return data


def _safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def _norm_symbol(symbol: Optional[str]) -> Optional[str]:
    if not symbol:
        return None
    s = str(symbol).strip().upper()
    if not s:
        return None
    if not s.endswith("USDT"):
        s = s + "USDT"
    return s


# ============================================================
# PUBLIC
# ============================================================

def get_account_info(target: Optional[str] = None) -> Dict:
    cfg = _get_binance_creds(target)
    target = cfg["target"]

    account = _signed_request("GET", "/fapi/v2/account", {}, target=target)

    positions = [
        p for p in account.get("positions", [])
        if abs(_safe_float(p.get("positionAmt", 0))) > 0
    ]

    return {
        "target": target,
        "can_trade": True,
        "totalWalletBalance": _safe_float(account.get("totalWalletBalance")),
        "totalUnrealizedProfit": _safe_float(account.get("totalUnrealizedProfit")),
        "totalMarginBalance": _safe_float(account.get("totalMarginBalance")),
        "availableBalance": _safe_float(account.get("availableBalance")),
        "totalPositionInitialMargin": _safe_float(account.get("totalPositionInitialMargin")),
        "totalOpenOrderInitialMargin": _safe_float(account.get("totalOpenOrderInitialMargin")),
        "positionsCount": len(positions),
    }


def get_positions(target: Optional[str] = None):
    cfg = _get_binance_creds(target)
    target = cfg["target"]

    raw = _signed_request("GET", "/fapi/v2/positionRisk", {}, target=target)

    positions = []
    for p in raw:
        amt = _safe_float(p.get("positionAmt", 0))
        if amt == 0:
            continue
        positions.append({
            "symbol": p.get("symbol"),
            "positionAmt": amt,  # giữ dấu + / - để FE phân biệt BUY/SELL
            "entryPrice": _safe_float(p.get("entryPrice")),
            "markPrice": _safe_float(p.get("markPrice")),
            "unrealizedProfit": _safe_float(p.get("unRealizedProfit")),
            "notional": abs(_safe_float(p.get("notional"))),
            "leverage": int(float(p.get("leverage", 1))),
            "marginType": p.get("marginType"),
            "liquidationPrice": _safe_float(p.get("liquidationPrice")),
            "isolatedMargin": _safe_float(p.get("isolatedMargin")),
            "updateTime": p.get("updateTime"),
        })

    return positions


def get_open_orders(target: Optional[str] = None, symbol: Optional[str] = None):
    cfg = _get_binance_creds(target)
    target = cfg["target"]
    symbol = _norm_symbol(symbol)

    params = {}
    if symbol:
        params["symbol"] = symbol

    normal = _signed_request("GET", "/fapi/v1/openOrders", params, target=target)
    algo = _signed_request("GET", "/fapi/v1/openAlgoOrders", params, target=target)

    rows = []

    # Normal orders
    for o in (normal if isinstance(normal, list) else []):
        rows.append({
            "symbol": o.get("symbol"),
            "side": o.get("side"),
            "type": o.get("type"),
            "origQty": _safe_float(o.get("origQty")),
            "price": _safe_float(o.get("price")),
            "stopPrice": _safe_float(o.get("stopPrice")),
            "status": o.get("status"),
            "time": o.get("time"),
            "kind": "NORMAL",
        })

    # Algo orders
    for o in (algo if isinstance(algo, list) else []):
        rows.append({
            "symbol": o.get("symbol"),
            "side": o.get("side"),
            "type": o.get("orderType"),               # map sang field FE đang dùng
            "origQty": _safe_float(o.get("quantity")),
            "price": _safe_float(o.get("price")),
            "stopPrice": _safe_float(o.get("triggerPrice")),
            "status": o.get("algoStatus"),
            "time": o.get("createTime"),
            "kind": "ALGO",
        })

    return rows


def get_trades(
    target: Optional[str] = None,
    symbol: Optional[str] = None,
    limit: int = 500,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
):
    """
    Binance Futures userTrades requires symbol.
    """
    cfg = _get_binance_creds(target)
    target = cfg["target"]
    symbol = _norm_symbol(symbol)

    if not symbol:
        raise RuntimeError("symbol is required for account/trades")

    params = {
        "symbol": symbol,
        "limit": min(max(limit, 1), 1000),
    }
    if start_time:
        params["startTime"] = int(start_time)
    if end_time:
        params["endTime"] = int(end_time)

    data = _signed_request("GET", "/fapi/v1/userTrades", params, target=target)

    rows = []
    for t in (data if isinstance(data, list) else []):
        rows.append({
            "symbol": t.get("symbol"),
            "side": "BUY" if t.get("buyer") else "SELL",
            "price": _safe_float(t.get("price")),
            "qty": _safe_float(t.get("qty")),
            "quoteQty": _safe_float(t.get("quoteQty")),
            "realizedPnl": _safe_float(t.get("realizedPnl")),
            "commission": _safe_float(t.get("commission")),
            "commissionAsset": t.get("commissionAsset"),
            "time": t.get("time"),
        })

    return rows


def get_income(
    target: Optional[str] = None,
    symbol: Optional[str] = None,
    income_type: Optional[str] = None,
    limit: int = 500,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
):
    cfg = _get_binance_creds(target)
    target = cfg["target"]
    symbol = _norm_symbol(symbol)

    params = {"limit": min(max(limit, 1), 1000)}
    if symbol:
        params["symbol"] = symbol
    if income_type and income_type != "all":
        params["incomeType"] = income_type
    if start_time:
        params["startTime"] = int(start_time)
    if end_time:
        params["endTime"] = int(end_time)

    data = _signed_request("GET", "/fapi/v1/income", params, target=target)

    rows = []
    for i in (data if isinstance(data, list) else []):
        rows.append({
            "symbol": i.get("symbol"),
            "incomeType": i.get("incomeType"),
            "income": _safe_float(i.get("income")),
            "asset": i.get("asset"),
            "info": i.get("info"),
            "time": i.get("time"),
            "tranId": i.get("tranId"),
            "tradeId": i.get("tradeId"),
        })

    return rows