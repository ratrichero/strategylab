#!/usr/bin/env python3
"""
Standalone WebSocket Probe for Binance Futures

Scope:
1) Market WS probe:
   - connect to markPrice stream
   - verify first payload arrives
   - keep receiving during duration

2) WS API probe:
   - connect to WS API endpoint
   - call session.status repeatedly
   - verify request/response path works

IMPORTANT:
- This file is standalone, does NOT modify core system.
- This probe does NOT test authenticated trading/order placement.
- WS API here only tests connectivity + basic usability.

Examples:
    pip install websockets

    # testnet
    python tools/ws_probe.py --env testnet --symbol BTCUSDT --duration 30

    # mainnet
    python tools/ws_probe.py --env mainnet --symbol BTCUSDT --duration 30

    # override market url manually if needed
    python tools/ws_probe.py --env testnet --symbol BTCUSDT --duration 30 \
      --market-url wss://stream.binancefuture.com/ws/btcusdt@markPrice
"""

import argparse
import asyncio
import json
import sys
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Optional, Any

try:
    import websockets
except ImportError:
    print("Missing dependency: pip install websockets", file=sys.stderr)
    raise


# ============================================================
# Helpers
# ============================================================

def utc_iso(ts: Optional[float] = None) -> str:
    if ts is None:
        ts = time.time()
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def mask_value(v: Optional[str]) -> Optional[str]:
    if not v:
        return v
    if len(v) <= 6:
        return "*" * len(v)
    return v[:2] + "*" * (len(v) - 4) + v[-2:]


def add_return_rate_limits_flag(url: str) -> str:
    if "returnRateLimits=" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}returnRateLimits=false"


def default_api_url(env: str) -> str:
    if env == "testnet":
        return "wss://testnet.binancefuture.com/ws-fapi/v1"
    return "wss://ws-fapi.binance.com/ws-fapi/v1"


def default_market_url(env: str, symbol: str) -> str:
    sym = symbol.lower()

    # NOTE:
    # Mainnet routed endpoint theo doc mới.
    # Testnet preset dùng endpoint phổ biến cũ/đang dùng thực tế nhiều nơi.
    # Nếu môi trường của anh khác route, override bằng --market-url.
    if env == "testnet":
        return f"wss://stream.binancefuture.com/ws/{sym}@markPrice"

    return f"wss://fstream.binance.com/market/ws/{sym}@markPrice"


def short_json(data: Any, limit: int = 240) -> str:
    try:
        s = json.dumps(data, ensure_ascii=False)
    except Exception:
        s = str(data)
    if len(s) > limit:
        return s[:limit] + "..."
    return s


# ============================================================
# Result Model
# ============================================================

@dataclass
class ProbeResult:
    name: str
    url: str
    ok: bool = False
    connected: bool = False
    connected_at: Optional[str] = None
    first_message_at: Optional[str] = None
    last_message_at: Optional[str] = None
    duration_s: float = 0.0
    message_count: int = 0
    error: Optional[str] = None
    last_summary: Optional[dict] = None


# ============================================================
# Market WS Probe
# ============================================================

def summarize_market_message(raw: Any) -> dict:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8", errors="replace")
        except Exception:
            return {"raw_preview": "<bytes>"}

    try:
        data = json.loads(raw)
    except Exception:
        return {"raw_preview": str(raw)[:200]}

    payload = data.get("data", data)

    summary = {
        "stream": data.get("stream"),
        "event": payload.get("e"),
        "symbol": payload.get("s") or payload.get("symbol"),
    }

    # futures markPrice thường có các field này
    for k in ("p", "i", "r", "E", "T"):
        if k in payload:
            summary[k] = payload.get(k)

    return summary


async def probe_market_ws(url: str, duration: int, verbose: bool) -> ProbeResult:
    res = ProbeResult(name="market_ws", url=url)
    started = time.monotonic()

    print(f"\n[MARKET] Connecting: {url}")

    try:
        async with websockets.connect(
            url,
            ping_interval=None,
            open_timeout=10,
            close_timeout=3,
            max_size=2_000_000,
        ) as ws:
            res.connected = True
            res.connected_at = utc_iso()
            print(f"[MARKET] Connected at {res.connected_at}")

            deadline = time.monotonic() + duration

            while time.monotonic() < deadline:
                timeout = min(10, max(0.1, deadline - time.monotonic()))
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except asyncio.TimeoutError:
                    continue

                now_iso = utc_iso()
                res.message_count += 1
                res.last_message_at = now_iso

                if res.first_message_at is None:
                    res.first_message_at = now_iso

                summary = summarize_market_message(raw)
                res.last_summary = summary

                if verbose or res.message_count <= 3:
                    print(f"[MARKET] msg#{res.message_count}: {short_json(summary)}")

            if res.message_count > 0:
                res.ok = True
            else:
                res.error = f"No market payload received within {duration}s"

    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"

    res.duration_s = round(time.monotonic() - started, 3)

    if res.ok:
        print(f"[MARKET] PASS | messages={res.message_count} | duration={res.duration_s}s")
    else:
        print(f"[MARKET] FAIL | error={res.error}")

    return res


# ============================================================
# WS API Probe
# ============================================================

async def ws_api_call(ws, method: str, params: Optional[dict] = None, timeout: int = 10) -> dict:
    req_id = str(uuid.uuid4())
    req = {
        "id": req_id,
        "method": method,
    }
    if params:
        req["params"] = params

    await ws.send(json.dumps(req))

    while True:
        raw = await asyncio.wait_for(ws.recv(), timeout=timeout)

        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="replace")

        data = json.loads(raw)

        # Chỉ bắt response đúng request id
        if data.get("id") == req_id:
            return data


def summarize_api_response(data: dict) -> dict:
    result = data.get("result") or {}
    return {
        "status": data.get("status"),
        "apiKey": mask_value(result.get("apiKey")),
        "authorizedSince": result.get("authorizedSince"),
        "connectedSince": result.get("connectedSince"),
        "serverTime": result.get("serverTime"),
    }


async def probe_api_ws(url: str, duration: int, verbose: bool) -> ProbeResult:
    res = ProbeResult(name="ws_api", url=url)
    started = time.monotonic()

    url = add_return_rate_limits_flag(url)

    print(f"\n[WS_API] Connecting: {url}")

    try:
        async with websockets.connect(
            url,
            ping_interval=None,
            open_timeout=10,
            close_timeout=3,
            max_size=2_000_000,
        ) as ws:
            res.connected = True
            res.connected_at = utc_iso()
            print(f"[WS_API] Connected at {res.connected_at}")

            deadline = time.monotonic() + duration
            req_interval = 10

            while time.monotonic() < deadline:
                resp = await ws_api_call(ws, "session.status", timeout=10)

                now_iso = utc_iso()
                res.message_count += 1
                res.last_message_at = now_iso

                if res.first_message_at is None:
                    res.first_message_at = now_iso

                summary = summarize_api_response(resp)
                res.last_summary = summary

                status_code = resp.get("status")
                if status_code != 200:
                    err = resp.get("error") or {}
                    res.error = f"session.status failed: status={status_code} code={err.get('code')} msg={err.get('msg')}"
                    res.ok = False
                    print(f"[WS_API] FAIL response: {short_json(resp)}")
                    break

                if verbose or res.message_count <= 3:
                    print(f"[WS_API] resp#{res.message_count}: {short_json(summary)}")

                res.ok = True

                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break

                await asyncio.sleep(min(req_interval, remaining))

            if res.message_count == 0 and not res.error:
                res.error = f"No API response received within {duration}s"
                res.ok = False

    except Exception as e:
        res.error = f"{type(e).__name__}: {e}"

    res.duration_s = round(time.monotonic() - started, 3)

    if res.ok:
        print(f"[WS_API] PASS | responses={res.message_count} | duration={res.duration_s}s")
    else:
        print(f"[WS_API] FAIL | error={res.error}")

    return res


# ============================================================
# Main
# ============================================================

async def async_main():
    parser = argparse.ArgumentParser(description="Binance Futures WebSocket probe")
    parser.add_argument("--env", choices=["mainnet", "testnet"], default="testnet")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--duration", type=int, default=30, help="seconds for each probe")
    parser.add_argument("--market-url", default=None, help="override market ws url")
    parser.add_argument("--api-url", default=None, help="override ws api url")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    market_url = args.market_url or default_market_url(args.env, args.symbol)
    api_url = args.api_url or default_api_url(args.env)

    print("=" * 72)
    print("BINANCE FUTURES WS PROBE")
    print("=" * 72)
    print(f"ENV           : {args.env}")
    print(f"SYMBOL        : {args.symbol}")
    print(f"DURATION      : {args.duration}s / probe")
    print(f"MARKET URL    : {market_url}")
    print(f"WS API URL    : {api_url}")
    if args.env == "testnet" and args.market_url is None:
        print("NOTE          : testnet market URL đang dùng preset phổ biến;")
        print("                nếu fail, hãy override bằng --market-url theo route môi trường thực tế.")
    print("=" * 72)

    market_res = await probe_market_ws(market_url, args.duration, args.verbose)
    api_res = await probe_api_ws(api_url, args.duration, args.verbose)

    summary = {
        "market_ws": asdict(market_res),
        "ws_api": asdict(api_res),
        "all_passed": bool(market_res.ok and api_res.ok),
    }

    print("\n" + "=" * 72)
    print("FINAL SUMMARY")
    print("=" * 72)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("=" * 72)

    if summary["all_passed"]:
        print("RESULT: PASS — websocket connectivity usable at transport level.")
        return 0

    print("RESULT: FAIL — ít nhất 1 probe chưa qua.")
    return 1


def main():
    try:
        code = asyncio.run(async_main())
        raise SystemExit(code)
    except KeyboardInterrupt:
        print("\nInterrupted by user")
        raise SystemExit(130)


if __name__ == "__main__":
    main()