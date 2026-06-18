"""Pre-Fill Validation Engine"""

from dataclasses import dataclass, field
from typing import Optional, Dict
import pandas as pd

DEFAULT_CONFIG = {
    "enabled": True,

    "whitelist": [],

    "price_context": {
        "enabled": True,
        "max_adverse_move_pct": {
            "15m": 1.5,
            "1h": 2.5,
            "4h": 4.0
        }
    },

    "favorable_extension": {
        "enabled": True,
        "max_extension_atr": {
            "15m": 1.0,
            "1h": 1.2,
            "4h": 1.5
        }
    },

    "pattern_invalidation": {
        "enabled": True,
        "break_buffer_atr": 0.10,
        "confirm_closed_bars": 3,
        # pattern-specific overrides (nếu không có thì dùng generic)
        "patterns": {
            # Engulfing: body lớn bao trùm, invalid khi phá hẳn high/low
            "Bullish Engulfing": {
                "invalid_above": "signal_high",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.10
            },
            "Bearish Engulfing": {
                "invalid_above": "signal_high",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.10
            },
            # Hammer/Shooting Star: shadow dài, body nhỏ
            # Invalid chặt hơn vì setup yếu hơn engulfing
            "Hammer": {
                "invalid_above": "signal_high",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.05
            },
            "Shooting Star": {
                "invalid_above": "signal_high",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.05
            },
            # Morning/Evening Star: 3-bar pattern
            # Dùng high/low của cả cluster
            "Morning Star": {
                "invalid_above": "signal_high",
                "invalid_below": "cluster_low",
                "break_buffer_atr": 0.10,
                "cluster_bars": 3
            },
            "Evening Star": {
                "invalid_above": "cluster_high",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.10,
                "cluster_bars": 3
            },
            # Marubozu: full body, ít wick
            # Invalid khi phá body rõ ràng
            "Bullish Marubozu": {
                "invalid_above": "signal_high",
                "invalid_below": "signal_open",
                "break_buffer_atr": 0.08
            },
            "Bearish Marubozu": {
                "invalid_above": "signal_open",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.08
            },
            # Breakout patterns
            "Bullish Breakout": {
                "invalid_above": "signal_high",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.15
            },
            "Bearish Breakout": {
                "invalid_above": "signal_high",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.15
            },
            # Pullback patterns
            "Bullish Pullback": {
                "invalid_above": "signal_high",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.10
            },
            "Bearish Pullback": {
                "invalid_above": "signal_high",
                "invalid_below": "signal_low",
                "break_buffer_atr": 0.10
            },
        }
    },

    "candle_invalidation": {
        "enabled": True,
        "adverse_body_atr_mult": 1.5
    },
    "momentum_check": {
        "enabled": True,
        "rsi_reject_long_above": 75,
        "rsi_reject_short_below": 25
    },
    "volatility_guard": {
        "enabled": True,
        "atr_spike_multiplier": 2.5
    },
    "regime_check": {
        "enabled": True
    },
}


@dataclass
class ValidationResult:
    passed: bool
    reason: Optional[str] = None
    checks_passed: int = 0
    checks_total: int = 0
    details: Dict = field(default_factory=dict)


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class PreFillValidator:
    def __init__(self, config=None):
        if config is None:
            try:
                from app.services.config_service import get_runtime_config
                config = get_runtime_config().get("PREFILL_CONFIG", DEFAULT_CONFIG)
            except Exception:
                config = DEFAULT_CONFIG

        self.cfg = _deep_merge(DEFAULT_CONFIG, config if isinstance(config, dict) else {})
        self._data_cache: Dict = {}

    def validate(self, pending, current_price: float) -> ValidationResult:
        if not self.cfg.get("enabled", True):
            return ValidationResult(passed=True, reason="disabled")

        self._data_cache = {}
        checks = []
        details = {}

        checks_config = [
            ("whitelist",             lambda: self._check_whitelist(pending)),
            ("price_context",         lambda: self._check_price(pending, current_price)),
            ("favorable_extension",   lambda: self._check_favorable_extension(pending, current_price)),
            ("pattern_invalidation",  lambda: self._check_pattern_invalidation(pending, current_price)),
            ("candle_invalidation",   lambda: self._check_candle(pending, current_price)),
            ("momentum_check",        lambda: self._check_momentum(pending)),
            ("volatility_guard",      lambda: self._check_volatility(pending)),
            ("regime_check",          lambda: self._check_regime(pending)),
        ]

        for name, fn in checks_config:
            if name == "whitelist":
                ok, reason, info = fn()
            else:
                block_cfg = self.cfg.get(name, {})
                if isinstance(block_cfg, dict) and not block_cfg.get("enabled", True):
                    continue
                ok, reason, info = fn()

            checks.append(ok)
            details[name] = {"passed": ok, "reason": reason, **info}

            if not ok:
                return ValidationResult(
                    passed=False,
                    reason=f"PREFILL::{name}::{reason}",
                    checks_passed=sum(checks) - 1,
                    checks_total=len(checks),
                    details=details
                )

        return ValidationResult(
            passed=True,
            checks_passed=sum(checks),
            checks_total=len(checks),
            details=details
        )

    # ========================================================
    # CHECK 0 — WHITELIST
    # ========================================================

    def _check_whitelist(self, pending):
        info = {}
        wl = self.cfg.get("whitelist", [])

        if not wl:
            return True, "no_whitelist", info

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

        return False, "not_in_whitelist", info

    # ========================================================
    # CHECK 1 — PRICE CONTEXT
    # ========================================================

    def _check_price(self, pending, current_price):
        info = {}
        snap = pending.indicators_snapshot or {}
        scan_close = snap.get("close")

        if scan_close is None:
            return True, "no_scan_price", info

        scan_close = float(scan_close)
        change = (current_price - scan_close) / scan_close * 100
        adverse = -change if pending.direction == "LONG" else change

        info.update({
            "scan_close": scan_close,
            "adverse_pct": round(adverse, 3)
        })

        max_adv = self.cfg["price_context"]["max_adverse_move_pct"].get(
            pending.timeframe, 2.5
        )

        if adverse > max_adv:
            return False, f"adverse_{adverse:.2f}pct", info

        return True, "ok", info

    # ========================================================
    # CHECK 2 — FAVORABLE EXTENSION
    # ========================================================

    def _check_favorable_extension(self, pending, current_price):
        info = {}
        snap = pending.indicators_snapshot or {}
        scan_close = snap.get("close")

        if scan_close is None:
            return True, "no_scan_price", info

        scan_close = float(scan_close)

        atr = float(pending.atr_value or 0)
        if atr <= 0:
            scan_atr = snap.get("atr")
            if scan_atr:
                atr = float(scan_atr or 0)

        if atr <= 0:
            return True, "no_atr", info

        if pending.direction == "LONG":
            favorable_move = current_price - scan_close
        else:
            favorable_move = scan_close - current_price

        favorable_atr = favorable_move / atr
        info["favorable_extension_atr"] = round(favorable_atr, 3)

        max_ext = self.cfg["favorable_extension"]["max_extension_atr"].get(
            pending.timeframe, 1.0
        )

        if favorable_atr > max_ext:
            return False, f"favorable_extension_{favorable_atr:.2f}ATR", info

        return True, "ok", info

    # ========================================================
    # CHECK 3 — PATTERN INVALIDATION (pattern-specific)
    # ========================================================

    def _check_pattern_invalidation(self, pending, current_price):
        """
        Pattern-aware invalidation:
        Dựa vào signal candle high/low/open/close + cluster nếu cần.
        Mỗi pattern có rule riêng (break level + buffer ATR).
        """
        info = {}

        df = self._get_data(pending.symbol, pending.timeframe, 120)
        if df is None or df.empty:
            return True, "no_data", info

        signal_candle = self._find_signal_candle(df, pending)
        if signal_candle is None:
            return True, "signal_candle_not_found", info

        sig_high = float(signal_candle["high"])
        sig_low = float(signal_candle["low"])
        sig_open = float(signal_candle["open"])
        sig_close = float(signal_candle["close"])

        atr = self._resolve_atr(pending, signal_candle, df)
        if atr <= 0:
            return True, "no_atr", info

        # Lấy pattern-specific config
        pattern_name = pending.pattern or ""
        patterns_cfg = self.cfg["pattern_invalidation"].get("patterns", {})
        pat_cfg = patterns_cfg.get(pattern_name, None)

        if pat_cfg:
            break_buffer_atr = float(pat_cfg.get("break_buffer_atr", 0.10))
        else:
            break_buffer_atr = float(
                self.cfg["pattern_invalidation"].get("break_buffer_atr", 0.10)
            )

        buffer_value = atr * break_buffer_atr

        # Cluster high/low cho multi-bar patterns
        cluster_high = sig_high
        cluster_low = sig_low

        if pat_cfg and pat_cfg.get("cluster_bars"):
            cluster_bars = int(pat_cfg["cluster_bars"])
            cluster_high, cluster_low = self._get_cluster_levels(
                df, pending.candle_time, cluster_bars
            )

        # Resolve invalidation levels theo pattern config
        if pat_cfg:
            invalid_above_key = pat_cfg.get("invalid_above", "signal_high")
            invalid_below_key = pat_cfg.get("invalid_below", "signal_low")
        else:
            invalid_above_key = "signal_high"
            invalid_below_key = "signal_low"

        level_map = {
            "signal_high": sig_high,
            "signal_low": sig_low,
            "signal_open": sig_open,
            "signal_close": sig_close,
            "cluster_high": cluster_high,
            "cluster_low": cluster_low,
        }

        invalid_above = level_map.get(invalid_above_key, sig_high)
        invalid_below = level_map.get(invalid_below_key, sig_low)

        info.update({
            "pattern": pattern_name,
            "pattern_specific": pat_cfg is not None,
            "signal_high": sig_high,
            "signal_low": sig_low,
            "signal_open": sig_open,
            "signal_close": sig_close,
            "cluster_high": cluster_high,
            "cluster_low": cluster_low,
            "break_buffer_atr": break_buffer_atr,
            "buffer_value": round(buffer_value, 6),
        })

        # LONG: invalid nếu phá xuống dưới invalid_below
        if pending.direction == "LONG":
            invalid_level = invalid_below - buffer_value
            info["invalid_level"] = round(invalid_level, 6)

            if current_price < invalid_level:
                return False, f"broke_{invalid_below_key}_{current_price:.6f}", info

        # SHORT: invalid nếu phá lên trên invalid_above
        else:
            invalid_level = invalid_above + buffer_value
            info["invalid_level"] = round(invalid_level, 6)

            if current_price > invalid_level:
                return False, f"broke_{invalid_above_key}_{current_price:.6f}", info

        # Confirm bằng close của vài nến gần nhất
        confirm_bars = int(self.cfg["pattern_invalidation"].get("confirm_closed_bars", 3))
        recent = df.tail(confirm_bars)

        if not recent.empty:
            if pending.direction == "LONG":
                confirm_level = invalid_below - buffer_value
                if any(float(row["close"]) < confirm_level for _, row in recent.iterrows()):
                    return False, f"confirmed_close_below_{invalid_below_key}", info
            else:
                confirm_level = invalid_above + buffer_value
                if any(float(row["close"]) > confirm_level for _, row in recent.iterrows()):
                    return False, f"confirmed_close_above_{invalid_above_key}", info

        return True, "ok", info

    # ========================================================
    # CHECK 4 — CANDLE INVALIDATION
    # ========================================================

    def _check_candle(self, pending, current_price):
        info = {}
        df = self._get_data(pending.symbol, pending.timeframe, 10)

        if df is None or len(df) < 3:
            return True, "no_data", info

        atr = pending.atr_value
        if not atr or atr <= 0:
            last_atr = df.iloc[-1].get("atr")
            atr = float(last_atr) if last_atr else 0

        if atr <= 0:
            return True, "no_atr", info

        mult = self.cfg["candle_invalidation"]["adverse_body_atr_mult"]

        for i in range(-3, 0):
            if abs(i) > len(df):
                continue

            candle = df.iloc[i]
            body = float(candle["close"]) - float(candle["open"])

            if pending.direction == "LONG" and body < 0 and abs(body) > atr * mult:
                return False, f"adverse_candle_{abs(body)/atr:.1f}ATR", info

            elif pending.direction == "SHORT" and body > 0 and abs(body) > atr * mult:
                return False, f"adverse_candle_{abs(body)/atr:.1f}ATR", info

        return True, "ok", info

    # ========================================================
    # CHECK 5 — MOMENTUM
    # ========================================================

    def _check_momentum(self, pending):
        info = {}
        df = self._get_data(pending.symbol, pending.timeframe, 50)

        if df is None or len(df) < 20:
            return True, "no_data", info

        rsi = df.iloc[-1].get("rsi")
        if rsi is None or pd.isna(rsi):
            return True, "no_rsi", info

        rsi = float(rsi)
        info["current_rsi"] = round(rsi, 2)

        cfg = self.cfg["momentum_check"]

        if pending.direction == "LONG" and rsi > cfg["rsi_reject_long_above"]:
            return False, f"rsi_too_high_{rsi:.1f}", info

        if pending.direction == "SHORT" and rsi < cfg["rsi_reject_short_below"]:
            return False, f"rsi_too_low_{rsi:.1f}", info

        return True, "ok", info

    # ========================================================
    # CHECK 6 — VOLATILITY
    # ========================================================

    def _check_volatility(self, pending):
        info = {}
        snap = pending.indicators_snapshot or {}
        scan_atr = snap.get("atr")
        scan_close = snap.get("close")

        if not scan_atr or not scan_close:
            return True, "no_scan_atr", info

        scan_atr_pct = float(scan_atr) / float(scan_close)

        df = self._get_data(pending.symbol, pending.timeframe, 50)
        if df is None or len(df) < 20:
            return True, "no_data", info

        last = df.iloc[-1]
        c_atr = float(last.get("atr") or 0)
        c_cls = float(last.get("close") or 0)

        if c_cls <= 0 or c_atr <= 0:
            return True, "no_curr_atr", info

        curr_atr_pct = c_atr / c_cls

        if scan_atr_pct > 0:
            ratio = curr_atr_pct / scan_atr_pct
            info["atr_spike_ratio"] = round(ratio, 2)

            mult = self.cfg["volatility_guard"]["atr_spike_multiplier"]
            if ratio > mult:
                return False, f"atr_spike_{ratio:.1f}x", info

        return True, "ok", info

    # ========================================================
    # CHECK 7 — REGIME
    # ========================================================

    def _check_regime(self, pending):
        info = {"scan_regime": pending.regime}
        df = self._get_data(pending.symbol, pending.timeframe, 250)

        if df is None or len(df) < 50:
            return True, "no_data", info

        try:
            from app.services.indicator_service import add_indicators_advanced, detect_regime_advanced

            df = add_indicators_advanced(df)
            current = detect_regime_advanced(df, method="hybrid")
            info["current_regime"] = current
        except Exception:
            return True, "error", info

        scan = pending.regime or "SIDEWAYS"

        if ((scan == "BULL" and current == "BEAR") or
            (scan == "BEAR" and current == "BULL")):
            if ((pending.direction == "LONG" and current == "BEAR") or
                (pending.direction == "SHORT" and current == "BULL")):
                return False, f"regime_flipped_{scan}_to_{current}", info

        return True, "ok", info

    # ========================================================
    # HELPERS
    # ========================================================

    def _resolve_atr(self, pending, signal_candle, df):
        atr = float(pending.atr_value or 0)
        if atr > 0:
            return atr

        sig_atr = signal_candle.get("atr")
        if sig_atr is not None and not pd.isna(sig_atr):
            atr = float(sig_atr or 0)
            if atr > 0:
                return atr

        last_atr = df.iloc[-1].get("atr")
        if last_atr is not None and not pd.isna(last_atr):
            return float(last_atr or 0)

        return 0

    def _find_signal_candle(self, df, pending):
        if pending.candle_time is None:
            return None

        target = pd.Timestamp(pending.candle_time)
        if target.tzinfo is None:
            target = target.tz_localize("UTC")

        matched = df[df["time"] == target]
        if not matched.empty:
            return matched.iloc[-1]

        return None

    def _get_cluster_levels(self, df, candle_time, cluster_bars: int):
        """
        Lấy high/low của cluster (vài nến liên tiếp xung quanh signal candle).
        Dùng cho multi-bar patterns như Morning Star / Evening Star.
        """
        if candle_time is None:
            return 0.0, 0.0

        target = pd.Timestamp(candle_time)
        if target.tzinfo is None:
            target = target.tz_localize("UTC")

        idx_matches = df.index[df["time"] == target]
        if len(idx_matches) == 0:
            return 0.0, 0.0

        idx = idx_matches[-1]
        start_idx = max(0, idx - cluster_bars + 1)

        cluster = df.loc[start_idx:idx]

        if cluster.empty:
            return 0.0, 0.0

        return float(cluster["high"].max()), float(cluster["low"].min())

    # ========================================================
    # DATA FETCH
    # ========================================================

    def _get_data(self, symbol, timeframe, limit=250):
        key = f"{symbol}_{timeframe}"
        if key in self._data_cache:
            return self._data_cache[key]

        try:
            from app.services.binance_service import get_klines_closed
            from app.services.indicator_service import add_indicators_advanced

            df = get_klines_closed(symbol, interval=timeframe, limit=limit)
            if df is not None and not df.empty and len(df) >= 5:
                df = add_indicators_advanced(df)

            self._data_cache[key] = df
            return df

        except Exception as e:
            print(f"[PREFILL] Data error {symbol}: {e}")
            self._data_cache[key] = None
            return None


def validate_before_fill(pending, current_price: float) -> ValidationResult:
    return PreFillValidator().validate(pending, current_price)