"""Pre-Fill Validation Engine"""
from dataclasses import dataclass, field
from typing import Tuple, Optional, Dict
from datetime import datetime, timedelta
import pandas as pd
from app.core.time_utils import utc_now

DEFAULT_CONFIG = {
    "enabled": True,
    "price_context": {"enabled": True,
        "max_adverse_move_pct": {"15m": 1.5, "1h": 2.5, "4h": 4.0}},
    "candle_invalidation": {"enabled": True, "adverse_body_atr_mult": 1.5},
    "momentum_check": {"enabled": True, "rsi_reject_long_above": 75, "rsi_reject_short_below": 25},
    "volatility_guard": {"enabled": True, "atr_spike_multiplier": 2.5},
    "regime_check": {"enabled": True},
}


@dataclass
class ValidationResult:
    passed: bool
    reason: Optional[str] = None
    checks_passed: int = 0
    checks_total: int = 0
    details: Dict = field(default_factory=dict)


class PreFillValidator:
    def __init__(self, config=None):
        if config is None:
            try:
                from app.services.config_service import get_runtime_config
                config = get_runtime_config().get("PREFILL_CONFIG", DEFAULT_CONFIG)
            except: config = DEFAULT_CONFIG
        self.cfg = {**DEFAULT_CONFIG, **config}
        self._data_cache: Dict = {}

    def _check_whitelist(self, pending):
        """
        Whitelist check:
        - Nếu whitelist rỗng hoặc không có → pass tất cả
        - Nếu có danh sách → chỉ symbol trong list mới pass
        """
        info = {}
        wl = self.cfg.get("whitelist", [])

        # Không có whitelist → pass
        if not wl:
            return True, "no_whitelist", info

        # Normalize: "BTC" → "BTCUSDT"
        normalized = set()
        for s in wl:
            s = str(s).strip().upper()
            if not s:
                continue
            if not s.endswith("USDT"):
                s = s + "USDT"
            normalized.add(s)

        if not normalized:
            return True, "empty_whitelist", info

        info["whitelist_size"] = len(normalized)
        info["symbol"] = pending.symbol

        if pending.symbol in normalized:
            return True, "whitelisted", info

        return False, f"not_in_whitelist", info

    def validate(self, pending, current_price: float) -> ValidationResult:
        if not self.cfg.get("enabled", True):
            return ValidationResult(passed=True, reason="disabled")
        self._data_cache = {}
        checks = []; details = {}

        checks_config = [
            ("whitelist",           lambda: self._check_whitelist(pending)),
            ("price_context",      lambda: self._check_price(pending, current_price)),
            ("candle_invalidation",lambda: self._check_candle(pending, current_price)),
            ("momentum_check",     lambda: self._check_momentum(pending)),
            ("volatility_guard",   lambda: self._check_volatility(pending)),
            ("regime_check",       lambda: self._check_regime(pending)),
        ]

        for name, fn in checks_config:
            if not self.cfg.get(name, {}).get("enabled", True): continue
            ok, reason, info = fn()
            checks.append(ok); details[name] = {"passed": ok, "reason": reason, **info}
            if not ok:
                return ValidationResult(passed=False, reason=f"PREFILL::{name}::{reason}",
                    checks_passed=sum(checks)-1, checks_total=len(checks), details=details)

        return ValidationResult(passed=True, checks_passed=sum(checks),
            checks_total=len(checks), details=details)

    def _check_price(self, pending, current_price):
        info = {}
        snap = pending.indicators_snapshot or {}
        scan_close = snap.get("close")
        if scan_close is None: return True, "no_scan_price", info
        scan_close = float(scan_close); change = (current_price - scan_close)/scan_close*100
        adverse = -change if pending.direction == "LONG" else change
        info.update({"scan_close": scan_close, "adverse_pct": round(adverse, 3)})
        max_adv = self.cfg["price_context"]["max_adverse_move_pct"].get(pending.timeframe, 2.5)
        if adverse > max_adv: return False, f"adverse_{adverse:.2f}pct", info
        return True, "ok", info

    def _check_candle(self, pending, current_price):
        info = {}
        df = self._get_data(pending.symbol, pending.timeframe, 10)
        if df is None or len(df) < 3: return True, "no_data", info
        atr = pending.atr_value
        if not atr or atr <= 0:
            last_atr = df.iloc[-1].get("atr"); atr = float(last_atr) if last_atr else 0
        if atr <= 0: return True, "no_atr", info
        mult = self.cfg["candle_invalidation"]["adverse_body_atr_mult"]
        for i in range(-3, 0):
            if abs(i) > len(df): continue
            candle = df.iloc[i]; body = float(candle["close"]) - float(candle["open"])
            if pending.direction == "LONG" and body < 0 and abs(body) > atr*mult:
                return False, f"adverse_candle_{abs(body)/atr:.1f}ATR", info
            elif pending.direction == "SHORT" and body > 0 and abs(body) > atr*mult:
                return False, f"adverse_candle_{abs(body)/atr:.1f}ATR", info
        return True, "ok", info

    def _check_momentum(self, pending):
        info = {}
        df = self._get_data(pending.symbol, pending.timeframe, 50)
        if df is None or len(df) < 20: return True, "no_data", info
        rsi = df.iloc[-1].get("rsi")
        if rsi is None or pd.isna(rsi): return True, "no_rsi", info
        rsi = float(rsi); info["current_rsi"] = round(rsi, 2)
        cfg = self.cfg["momentum_check"]
        if pending.direction == "LONG" and rsi > cfg["rsi_reject_long_above"]:
            return False, f"rsi_too_high_{rsi:.1f}", info
        if pending.direction == "SHORT" and rsi < cfg["rsi_reject_short_below"]:
            return False, f"rsi_too_low_{rsi:.1f}", info
        return True, "ok", info

    def _check_volatility(self, pending):
        info = {}
        snap = pending.indicators_snapshot or {}
        scan_atr = snap.get("atr"); scan_close = snap.get("close")
        if not scan_atr or not scan_close: return True, "no_scan_atr", info
        scan_atr_pct = float(scan_atr)/float(scan_close)
        df = self._get_data(pending.symbol, pending.timeframe, 50)
        if df is None or len(df) < 20: return True, "no_data", info
        last = df.iloc[-1]
        c_atr = float(last.get("atr") or 0); c_cls = float(last.get("close") or 0)
        if c_cls <= 0 or c_atr <= 0: return True, "no_curr_atr", info
        curr_atr_pct = c_atr/c_cls
        if scan_atr_pct > 0:
            ratio = curr_atr_pct/scan_atr_pct; info["atr_spike_ratio"] = round(ratio, 2)
            mult = self.cfg["volatility_guard"]["atr_spike_multiplier"]
            if ratio > mult: return False, f"atr_spike_{ratio:.1f}x", info
        return True, "ok", info

    def _check_regime(self, pending):
        info = {"scan_regime": pending.regime}
        df = self._get_data(pending.symbol, pending.timeframe, 250)
        if df is None or len(df) < 50: return True, "no_data", info
        try:
            from app.services.indicator_service import add_indicators_advanced, detect_regime_advanced
            df = add_indicators_advanced(df)
            current = detect_regime_advanced(df, method="hybrid")
            info["current_regime"] = current
        except: return True, "error", info
        scan = pending.regime or "SIDEWAYS"
        if ((scan == "BULL" and current == "BEAR") or (scan == "BEAR" and current == "BULL")):
            if (pending.direction == "LONG" and current == "BEAR") or                (pending.direction == "SHORT" and current == "BULL"):
                return False, f"regime_flipped_{scan}_to_{current}", info
        return True, "ok", info

    def _get_data(self, symbol, timeframe, limit=250):
        key = f"{symbol}_{timeframe}"
        if key in self._data_cache: return self._data_cache[key]
        try:
            from app.services.binance_service import get_klines_closed
            from app.services.indicator_service import add_indicators_advanced
            df = get_klines_closed(symbol, interval=timeframe, limit=limit)
            if df is not None and not df.empty and len(df) >= 5:
                df = add_indicators_advanced(df)
            self._data_cache[key] = df; return df
        except Exception as e:
            print(f"[PREFILL] Data error {symbol}: {e}")
            self._data_cache[key] = None; return None


def validate_before_fill(pending, current_price: float) -> ValidationResult:
    return PreFillValidator().validate(pending, current_price)

