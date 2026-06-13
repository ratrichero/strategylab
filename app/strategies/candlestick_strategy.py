from typing import Optional, Dict, Tuple
import pandas as pd
from app.strategies.base import BaseStrategy, SignalResult, StrategyWeights


class CandlestickStrategy(BaseStrategy):
    STRATEGY_NAME = "candlestick"
    WEIGHTS = {
        "15m": StrategyWeights(trend=0.25, momentum=0.25, volume=0.10, pattern=0.15, mtf=0.25),
        "1h":  StrategyWeights(trend=0.30, momentum=0.20, volume=0.10, pattern=0.15, mtf=0.25),
        "4h":  StrategyWeights(trend=0.30, momentum=0.15, volume=0.10, pattern=0.10, mtf=0.35),
    }
    BULLISH = {"Bullish Engulfing", "Hammer", "Morning Star", "Bullish Marubozu"}
    BEARISH = {"Bearish Engulfing", "Shooting Star", "Evening Star", "Bearish Marubozu"}
    PATTERN_SCORES = {
        "Morning Star": 2.0, "Evening Star": 2.0,
        "Bullish Engulfing": 2.0, "Bearish Engulfing": 2.0,
        "Hammer": 1.5, "Shooting Star": 1.5,
        "Bullish Marubozu": 1.5, "Bearish Marubozu": 1.5,
    }

    def detect(self, df: pd.DataFrame, timeframe: str) -> Optional[SignalResult]:
        if len(df) < self.get_min_bars(): return None
        pattern = self._detect_pattern(df)
        if not pattern: return None
        if pattern in self.BULLISH: direction = "LONG"
        elif pattern in self.BEARISH: direction = "SHORT"
        else: return None
        return SignalResult(strategy_name=self.STRATEGY_NAME,
                            direction=direction, pattern=pattern, valid=True)

    def score(self, df, signal, timeframe, trend_df=None,
              context_df=None, regime="SIDEWAYS", cfg=None) -> SignalResult:
        cfg = cfg or {}; weights = self.get_weights(timeframe); direction = signal.direction
        trend_s = self._calc_trend_score(df, direction)
        mom_s   = self._calc_momentum_score(df, direction)
        vol_s, vol_ratio = self._calc_volume_score(df, cfg)
        pat_s, body_ratio = self._calc_pattern_score(df, signal.pattern, direction)
        mtf_s   = self._calc_mtf_score(direction, trend_df, context_df, cfg)
        _, pen_n = self._calc_penalty(df, direction, regime, vol_ratio, cfg, body_ratio)
        t_n = self._normalize(trend_s, self.MAX_TREND)
        m_n = self._normalize(mom_s,   self.MAX_MOMENTUM)
        v_n = self._normalize(vol_s,   self.MAX_VOLUME)
        p_n = self._normalize(pat_s,   self.MAX_PATTERN)
        raw, final = self._apply_weights_and_scale(t_n, m_n, v_n, p_n, mtf_s, 0.0, pen_n, weights)
        signal.trend_score = trend_s; signal.momentum_score = mom_s
        signal.volume_score = vol_s; signal.pattern_score = pat_s
        signal.mtf_score = mtf_s; signal.penalty_norm = pen_n
        signal.rule_score_raw = raw; signal.final_score = final
        signal.components = self._build_components(signal, weights)
        return signal

    def _detect_pattern(self, df: pd.DataFrame) -> Optional[str]:
        if len(df) < 5: return None
        prev2 = df.iloc[-4]; prev = df.iloc[-3]; curr = df.iloc[-2]
        if (prev["close"] < prev["open"] and curr["close"] > curr["open"] and
                curr["open"] <= prev["close"] and curr["close"] >= prev["open"]):
            return "Bullish Engulfing"
        if (prev["close"] > prev["open"] and curr["close"] < curr["open"] and
                curr["open"] >= prev["close"] and curr["close"] <= prev["open"]):
            return "Bearish Engulfing"
        body = abs(curr["close"] - curr["open"])
        full_range = curr["high"] - curr["low"]
        if full_range == 0: return None
        upper_wick = curr["high"] - max(curr["close"], curr["open"])
        lower_wick = min(curr["close"], curr["open"]) - curr["low"]
        if lower_wick > body * 2 and upper_wick < body: return "Hammer"
        if upper_wick > body * 2 and lower_wick < body: return "Shooting Star"
        if (prev2["close"] < prev2["open"] and
                abs(prev["close"] - prev["open"]) < abs(prev2["close"] - prev2["open"]) * 0.5 and
                curr["close"] > curr["open"] and curr["close"] > prev2["open"]):
            return "Morning Star"
        if (prev2["close"] > prev2["open"] and
                abs(prev["close"] - prev["open"]) < abs(prev2["close"] - prev2["open"]) * 0.5 and
                curr["close"] < curr["open"] and curr["close"] < prev2["open"]):
            return "Evening Star"
        if body / full_range > 0.9 and curr["close"] > curr["open"]: return "Bullish Marubozu"
        if body / full_range > 0.9 and curr["close"] < curr["open"]: return "Bearish Marubozu"
        return None

    def _calc_pattern_score(self, df, pattern, direction) -> Tuple[float, float]:
        last = df.iloc[-1]
        base = self.PATTERN_SCORES.get(pattern or "", 0)
        body = abs(float(last["close"]) - float(last["open"]))
        full_range = float(last["high"]) - float(last["low"])
        body_ratio = body / full_range if full_range > 0 else 0
        pat_score  = base * body_ratio
        bb_pos = last.get("bb_position")
        if bb_pos is not None and not pd.isna(bb_pos):
            bb_pos = float(bb_pos)
            if direction == "LONG"  and bb_pos < 0.2: pat_score += 0.5
            elif direction == "SHORT" and bb_pos > 0.8: pat_score += 0.5
        return pat_score, body_ratio
