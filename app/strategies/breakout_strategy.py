from typing import Optional, Dict
import pandas as pd
from app.strategies.base import BaseStrategy, SignalResult, StrategyWeights


class BreakoutStrategy(BaseStrategy):
    STRATEGY_NAME = "breakout"
    WEIGHTS = {
        "15m": StrategyWeights(trend=0.20, momentum=0.15, volume=0.20, pattern=0.0, mtf=0.25, structure=0.20),
        "1h":  StrategyWeights(trend=0.25, momentum=0.15, volume=0.15, pattern=0.0, mtf=0.25, structure=0.20),
        "4h":  StrategyWeights(trend=0.25, momentum=0.10, volume=0.15, pattern=0.0, mtf=0.30, structure=0.20),
    }
    LOOKBACK = {"15m": 48, "1h": 24, "4h": 14}
    VOLUME_SURGE_MIN = 1.5
    BREAKOUT_MIN_PCT = 0.001

    def detect(self, df, timeframe, symbol=None, trend_df=None, context_df=None, cfg=None):
        lookback = self.LOOKBACK.get(timeframe, 24)
        if len(df) < lookback + 5: return None
        curr = df.iloc[-2]; window = df.iloc[-(lookback+5):-2]
        if len(window) < 10: return None
        swing_high = float(window["high"].max()); swing_low = float(window["low"].min())
        close = float(curr["close"]); vol_ma = float(curr.get("vol_ma") or 0)
        volume = float(curr.get("volume") or 0)
        vol_surge = volume / vol_ma if vol_ma > 0 else 0
        if vol_surge < self.VOLUME_SURGE_MIN: return None
        consol = swing_high - swing_low
        if close > swing_high * (1 + self.BREAKOUT_MIN_PCT):
            return SignalResult(strategy_name=self.STRATEGY_NAME, direction="LONG",
                pattern="Bullish Breakout",
                structure_score=self._calc_structure(swing_high, swing_low, close, consol, lookback, "LONG"),
                valid=True)
        if close < swing_low * (1 - self.BREAKOUT_MIN_PCT):
            return SignalResult(strategy_name=self.STRATEGY_NAME, direction="SHORT",
                pattern="Bearish Breakout",
                structure_score=self._calc_structure(swing_high, swing_low, close, consol, lookback, "SHORT"),
                valid=True)
        return None

    def score(self, df, signal, timeframe, symbol=None, trend_df=None, context_df=None, regime="SIDEWAYS", cfg=None):
        cfg = cfg or {}; weights = self.get_weights(timeframe); direction = signal.direction
        trend_s = self._calc_trend_score(df, direction)
        mom_s   = self._calc_momentum_breakout(df, direction)
        vol_s, vol_ratio = self._calc_volume_score(df, cfg)
        mtf_s   = self._calc_mtf_score(direction, trend_df, context_df, cfg)
        _, pen_n = self._calc_penalty(df, direction, regime, vol_ratio, cfg, body_ratio=None)
        t_n = self._normalize(trend_s, self.MAX_TREND)
        m_n = self._normalize(mom_s,   self.MAX_MOMENTUM)
        v_n = self._normalize(vol_s,   self.MAX_VOLUME)
        st_n = self._normalize(signal.structure_score, self.MAX_STRUCTURE)
        raw, final = self._apply_weights_and_scale(t_n, m_n, v_n, 0.0, mtf_s, st_n, pen_n, weights)
        signal.trend_score = trend_s; signal.momentum_score = mom_s
        signal.volume_score = vol_s; signal.mtf_score = mtf_s
        signal.penalty_norm = pen_n; signal.rule_score_raw = raw; signal.final_score = final
        signal.components = self._build_components(signal, weights)
        return signal

    def _calc_momentum_breakout(self, df, direction):
        rsi = df.iloc[-1].get("rsi")
        if rsi is None or pd.isna(rsi): return 0.0
        rsi = float(rsi)
        if direction == "LONG":
            if 50 <= rsi <= 70: return (rsi-50)/20*2.5
            elif rsi > 70: return max(0, 1.5-(rsi-70)/30*1.5)
            else: return max(0, (rsi-30)/20)
        else:
            if 30 <= rsi <= 50: return (50-rsi)/20*2.5
            elif rsi < 30: return max(0, 1.5-(30-rsi)/30*1.5)
            else: return max(0, (70-rsi)/20)

    def _calc_structure(self, swing_high, swing_low, close, consol, lookback, direction):
        score = min(1.0, lookback/48) * 0.5
        if direction == "LONG" and swing_high > 0:
            score += min(1.0, (close-swing_high)/swing_high*100) * 0.5
        elif direction == "SHORT" and swing_low > 0:
            score += min(1.0, (swing_low-close)/swing_low*100) * 0.5
        if swing_high > 0 and swing_low > 0:
            score += max(0, 1 - consol/swing_low*20) * 1.0
        return min(2.0, score)
