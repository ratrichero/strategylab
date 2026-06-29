from typing import Optional, Dict
import pandas as pd
from app.strategies.base import BaseStrategy, SignalResult, StrategyWeights


class MeanReversionStrategy(BaseStrategy):
    STRATEGY_NAME = "mean_reversion"
    STRATEGY_DESCRIPTION = "RSI extreme + BB touch → đảo chiều (mean reversion)"
    DEFAULT_THRESHOLD = 99.0
    WEIGHTS = {
        "15m": StrategyWeights(trend=0.15, momentum=0.30, volume=0.15, pattern=0.0, mtf=0.20, structure=0.20),
        "1h":  StrategyWeights(trend=0.15, momentum=0.30, volume=0.15, pattern=0.0, mtf=0.20, structure=0.20),
        "4h":  StrategyWeights(trend=0.15, momentum=0.25, volume=0.15, pattern=0.0, mtf=0.25, structure=0.20),
    }
    RSI_OVERSOLD = 30; RSI_OVERBOUGHT = 70
    BB_LOWER = 0.10; BB_UPPER = 0.90
    MAX_EMA_DIST = 0.05
    PATTERN_THRESHOLDS = {
        "Mean Reversion Long": 99.0,
        "Mean Reversion Short": 99.0,
    }

    def detect(self, df, timeframe, symbol=None, trend_df=None, context_df=None, cfg=None):
        if len(df) < self.get_min_bars(): return None
        curr = df.iloc[-2]
        rsi = curr.get("rsi"); bb_pos = curr.get("bb_position")
        close = float(curr.get("close") or 0); ema200 = float(curr.get("ema200") or 0)
        if rsi is None or bb_pos is None: return None
        rsi = float(rsi); bb_pos = float(bb_pos)
        if ema200 > 0 and abs(close - ema200)/ema200 > self.MAX_EMA_DIST: return None
        if rsi <= self.RSI_OVERSOLD and bb_pos <= self.BB_LOWER:
            return SignalResult(strategy_name=self.STRATEGY_NAME, direction="LONG",
                pattern="Mean Reversion Long",
                structure_score=self._mr_structure(rsi, bb_pos, "LONG"), valid=True)
        if rsi >= self.RSI_OVERBOUGHT and bb_pos >= self.BB_UPPER:
            return SignalResult(strategy_name=self.STRATEGY_NAME, direction="SHORT",
                pattern="Mean Reversion Short",
                structure_score=self._mr_structure(rsi, bb_pos, "SHORT"), valid=True)
        return None

    def score(self, df, signal, timeframe, symbol=None, trend_df=None, context_df=None, regime="SIDEWAYS", cfg=None):
        cfg = cfg or {}; weights = self.get_weights(timeframe); direction = signal.direction
        trend_s = self._calc_trend_score(df, direction)
        mom_s   = self._mr_momentum(df, direction)
        vol_s, vol_ratio = self._calc_volume_score(df, cfg)
        mtf_s   = self._calc_mtf_score(direction, trend_df, context_df, cfg)
        _, pen_n = self._calc_penalty(df, direction, regime, vol_ratio, cfg)
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

    def _mr_momentum(self, df, direction):
        last = df.iloc[-1]; rsi = last.get("rsi"); bb_pos = last.get("bb_position")
        if rsi is None or pd.isna(rsi): return 0.0
        rsi = float(rsi); score = 0.0
        if direction == "LONG":
            if rsi <= 20: score += 2.5
            elif rsi <= 25: score += 2.0
            elif rsi <= 30: score += 1.5
            elif rsi <= 35: score += 1.0
            if bb_pos is not None and float(bb_pos) <= 0.05: score += 0.5
        else:
            if rsi >= 80: score += 2.5
            elif rsi >= 75: score += 2.0
            elif rsi >= 70: score += 1.5
            elif rsi >= 65: score += 1.0
            if bb_pos is not None and float(bb_pos) >= 0.95: score += 0.5
        return min(2.5, score)

    def _mr_structure(self, rsi, bb_pos, direction):
        score = 0.0
        if direction == "LONG":
            score += max(0, (self.RSI_OVERSOLD - rsi)/30) * 1.0
            score += max(0, (self.BB_LOWER - bb_pos)/0.1) * 1.0
        else:
            score += max(0, (rsi - self.RSI_OVERBOUGHT)/30) * 1.0
            score += max(0, (bb_pos - self.BB_UPPER)/0.1) * 1.0
        return min(2.0, score)
