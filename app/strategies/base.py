from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, Dict, Tuple, List
import pandas as pd
import numpy as np


@dataclass
class SignalResult:
    strategy_name:   str
    direction:       str
    pattern:         Optional[str]
    trend_score:     float = 0.0
    momentum_score:  float = 0.0
    volume_score:    float = 0.0
    pattern_score:   float = 0.0
    structure_score: float = 0.0
    mtf_score:       float = 0.0
    penalty_norm:    float = 0.0
    rule_score_raw:  float = 0.0
    final_score:     float = 0.0
    components:      Dict  = field(default_factory=dict)
    valid:           bool  = True
    skip_reason:     Optional[str] = None


@dataclass
class StrategyWeights:
    trend:     float = 0.30
    momentum:  float = 0.20
    volume:    float = 0.10
    pattern:   float = 0.15
    mtf:       float = 0.25
    structure: float = 0.0

    def validate(self) -> bool:
        total = self.trend+self.momentum+self.volume+self.pattern+self.mtf+self.structure
        return abs(total - 1.0) < 0.01


class BaseStrategy(ABC):
    STRATEGY_NAME:        str       = "base"
    SUPPORTED_TIMEFRAMES: List[str] = ["15m", "1h", "4h"]
    WEIGHTS: Dict[str, StrategyWeights] = {}
    DEFAULT_THRESHOLD: float = 8.0
    PATTERN_THRESHOLDS: Dict[str, float] = {}

    PENALTY_WEIGHTS = {
        "body": 0.5, "volume": 0.5, "atr": 0.5,
        "regime_mismatch": 0.3, "regime_sideways": 0.1,
    }
    MAX_PENALTY   = sum(PENALTY_WEIGHTS.values())
    MAX_TREND     = 3.0
    MAX_MOMENTUM  = 2.5
    MAX_VOLUME    = 2.5
    MAX_PATTERN   = 2.5
    MAX_STRUCTURE = 2.0

    @abstractmethod
    def detect(self, df: pd.DataFrame, timeframe: str, symbol: str = None,
               trend_df=None, context_df=None, cfg=None) -> Optional[SignalResult]:
        pass

    @abstractmethod
    def score(self, df, signal, timeframe, symbol=None, trend_df=None,
              context_df=None, regime="SIDEWAYS", cfg=None) -> SignalResult:
        pass

    def get_weights(self, timeframe: str) -> StrategyWeights:
        return self.WEIGHTS.get(timeframe, self.WEIGHTS.get("1h", StrategyWeights()))

    def get_min_bars(self) -> int: return 50

    def _calc_trend_score(self, df: pd.DataFrame, direction: str) -> float:
        last = df.iloc[-1]
        try:
            ema200 = float(last.get("ema200") or 0)
            ema50  = float(last.get("ema50")  or 0)
            atr    = float(last.get("atr")    or 0)
            close  = float(last.get("close")  or 0)
        except (TypeError, ValueError):
            return 0.0
        if pd.isna(ema200) or ema200 == 0 or pd.isna(atr) or atr <= 0:
            return 0.0
        dist_atr = (close - ema200) / atr
        dist_comp = max(0.0, min(1.0, dist_atr / 2.0)) if direction == "LONG"                     else max(0.0, min(1.0, -dist_atr / 2.0))
        trend_dist = 2 * dist_comp
        struct_comp = 0.0
        if ema50 and not pd.isna(ema50) and ema200 != 0:
            ema_gap = (ema50 - ema200) / ema200
            if direction == "LONG" and ema_gap > 0:
                struct_comp = min(1.0, ema_gap * 50)
            elif direction == "SHORT" and ema_gap < 0:
                struct_comp = min(1.0, -ema_gap * 50)
        return trend_dist + struct_comp

    def _calc_momentum_score(self, df: pd.DataFrame, direction: str) -> float:
        rsi = df.iloc[-1].get("rsi")
        if rsi is None or pd.isna(rsi): return 0.0
        rsi = float(rsi); score = 0.0
        if direction == "LONG":
            if rsi < 30: score += 0.5
            if rsi < 35: score += 2.0
            elif 35 <= rsi <= 45: score += 1.0
        else:
            if rsi > 70: score += 0.5
            if rsi > 65: score += 2.0
            elif 55 <= rsi <= 65: score += 1.0
        return score

    def _calc_volume_score(self, df, cfg) -> Tuple[float, Optional[float]]:
        last = df.iloc[-1]
        vol_ma = last.get("vol_ma"); volume = last.get("volume")
        score = 0.0; vol_ratio = None
        if vol_ma and not pd.isna(vol_ma) and float(vol_ma) > 0 and volume:
            vol_ratio = float(volume) / float(vol_ma)
            mult = cfg.get("VOLUME_MULTIPLIER", 1.15)
            if vol_ratio >= 2: score += 2.0
            elif vol_ratio >= mult: score += 1.0
            if vol_ratio > 1.5: score += 0.5
        return score, vol_ratio

    def _calc_mtf_score(self, direction, trend_df, context_df, cfg) -> float:
        if not cfg.get("MTF_ENABLED", False): return 0.0
        if trend_df is None or len(trend_df) < 50: return 0.0
        try:
            from app.services.mtf_service import MTFCalculator
            return MTFCalculator.compute_mtf_score(
                direction=direction, trend_df=trend_df, context_df=context_df)
        except Exception as e:
            print(f"[MTF ERROR] {e}"); return 0.0

    def _calc_penalty(self, df, direction, regime, vol_ratio, cfg,
                      body_ratio=None) -> Tuple[float, float]:
        last = df.iloc[-1]; total = 0.0
        if body_ratio is not None:
            if body_ratio < cfg.get("BODY_RATIO_THRESHOLD", 0.35):
                total -= self.PENALTY_WEIGHTS["body"]
        if vol_ratio is None:
            total -= self.PENALTY_WEIGHTS["volume"]
        elif vol_ratio < cfg.get("VOLUME_MULTIPLIER", 1.15):
            total -= self.PENALTY_WEIGHTS["volume"]
        try:
            atr = float(last.get("atr") or 0); close = float(last.get("close") or 0)
            if atr > 0 and close > 0:
                if atr/close < cfg.get("ATR_RATIO_MIN", 0.0015):
                    total -= self.PENALTY_WEIGHTS["atr"]
        except: pass
        if regime == "BULL" and direction == "SHORT":
            total -= self.PENALTY_WEIGHTS["regime_mismatch"]
        elif regime == "BEAR" and direction == "LONG":
            total -= self.PENALTY_WEIGHTS["regime_mismatch"]
        elif regime == "SIDEWAYS":
            total -= self.PENALTY_WEIGHTS["regime_sideways"]
        norm = total / self.MAX_PENALTY if self.MAX_PENALTY > 0 else 0
        return total, norm

    def _apply_weights_and_scale(self, trend_n, momentum_n, volume_n,
                                  pattern_n, mtf_n, structure_n,
                                  penalty_n, weights) -> Tuple[float, float]:
        rule = (weights.trend * trend_n + weights.momentum * momentum_n +
                weights.volume * volume_n + weights.pattern * pattern_n +
                weights.mtf * mtf_n + weights.structure * structure_n) + penalty_n
        final = round(max(0.0, min(10.0, (rule + 1) * 5)), 2)
        return rule, final

    def _normalize(self, value: float, max_val: float) -> float:
        if max_val <= 0: return 0.0
        return max(0.0, min(1.0, float(value) / max_val))

    def _build_components(self, signal: SignalResult, weights: StrategyWeights) -> Dict:
        return {
            "trend_score": signal.trend_score, "momentum_score": signal.momentum_score,
            "volume_score": signal.volume_score, "pattern_score": signal.pattern_score,
            "structure_score": signal.structure_score, "mtf_score": signal.mtf_score,
            "penalty_norm": signal.penalty_norm, "rule_score_raw": signal.rule_score_raw,
            "rule_score_scaled": signal.final_score, "strategy_name": signal.strategy_name,
            "weights_used": {
                "trend": weights.trend, "momentum": weights.momentum,
                "volume": weights.volume, "pattern": weights.pattern,
                "mtf": weights.mtf, "structure": weights.structure,
            }
        }
    def get_strategy_config(self, cfg: dict) -> Dict:
        cfg = cfg or {}
        strategy_cfg = cfg.get("STRATEGY_CONFIG") or {}
        block = strategy_cfg.get(self.STRATEGY_NAME)
        return block if isinstance(block, dict) else {}

    def default_pattern_thresholds(self) -> Dict[str, float]:
        patterns = {}
        maybe_thresholds = getattr(self, "PATTERN_THRESHOLDS", None)
        if isinstance(maybe_thresholds, dict):
            for key, value in maybe_thresholds.items():
                if not isinstance(key, str) or not key:
                    continue
                try:
                    patterns[key] = float(value)
                except (TypeError, ValueError):
                    patterns[key] = 8.0

        maybe_scores = getattr(self, "PATTERN_SCORES", None)
        if isinstance(maybe_scores, dict):
            for key in maybe_scores.keys():
                if isinstance(key, str) and key:
                    patterns.setdefault(key, 8.0)

        for attr in dir(self):
            if not (attr.startswith("PATTERN_") or attr.startswith("PAT_")):
                continue
            if attr == "PATTERN_SCORES":
                continue
            val = getattr(self, attr)
            if isinstance(val, str) and val:
                patterns.setdefault(val, 8.0)

        return patterns

    def get_default_strategy_config(self, default_threshold: float = 8.0) -> Dict[str, object]:
        threshold = getattr(self, "DEFAULT_THRESHOLD", default_threshold)
        return {
            "threshold": float(threshold),
            "patterns": self.default_pattern_thresholds(),
            "symbols": [],
        }

    def _parse_symbol_list(self, raw) -> List[str]:
        if isinstance(raw, str):
            items = raw.split(",")
        elif isinstance(raw, (list, tuple, set)):
            items = list(raw)
        else:
            return []

        result = []
        seen = set()
        for item in items:
            if not isinstance(item, str):
                continue
            symbol = item.strip().upper()
            if not symbol:
                continue

            # user chỉ cần ghi BTC / ETH, tự nối USDT
            if not symbol.endswith("USDT") and symbol != "USDT":
                symbol = f"{symbol}USDT"

            if symbol in seen:
                continue
            seen.add(symbol)
            result.append(symbol)
        return result

    def is_symbol_allowed(self, symbol: str, cfg: dict) -> bool:
        strategy_cfg = self.get_strategy_config(cfg)
        allowed = strategy_cfg.get("symbols")
        if not allowed:
            return True

        allowed_symbols = self._parse_symbol_list(allowed)
        if not allowed_symbols:
            return True

        return (symbol or "").upper() in allowed_symbols

    def _invalidate(self, signal: SignalResult, reason: str) -> SignalResult:
        signal.valid = False
        signal.skip_reason = reason
        signal.final_score = 0.0
        signal.rule_score_raw = 0.0
        signal.components = signal.components or {}
        return signal
