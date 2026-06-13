from typing import Optional, Dict
import pandas as pd
from app.strategies.base import BaseStrategy, SignalResult, StrategyWeights


class TrendFollowingStrategy(BaseStrategy):
    STRATEGY_NAME = "trend_following"
    WEIGHTS = {
        "15m": StrategyWeights(trend=0.35, momentum=0.20, volume=0.15, pattern=0.0, mtf=0.25, structure=0.05),
        "1h":  StrategyWeights(trend=0.35, momentum=0.20, volume=0.15, pattern=0.0, mtf=0.25, structure=0.05),
        "4h":  StrategyWeights(trend=0.35, momentum=0.15, volume=0.15, pattern=0.0, mtf=0.30, structure=0.05),
    }
    MIN_VOL_SURGE = 1.2

    def detect(self, df, timeframe):
        if len(df) < self.get_min_bars(): return None
        curr = df.iloc[-2]; prev = df.iloc[-3]
        ema50_c = curr.get("ema50"); ema200_c = curr.get("ema200")
        ema50_p = prev.get("ema50"); ema200_p = prev.get("ema200")
        vol_ma = curr.get("vol_ma"); volume = float(curr.get("volume") or 0)
        if not all([ema50_c, ema200_c, ema50_p, ema200_p]): return None
        ema50_c = float(ema50_c); ema200_c = float(ema200_c)
        ema50_p = float(ema50_p); ema200_p = float(ema200_p)
        vol_surge = volume / float(vol_ma) if vol_ma and float(vol_ma) > 0 else 0
        if vol_surge < self.MIN_VOL_SURGE: return None
        if ema50_p <= ema200_p and ema50_c > ema200_c:
            return SignalResult(strategy_name=self.STRATEGY_NAME, direction="LONG",
                pattern="Golden Cross", structure_score=min(2.0, vol_surge), valid=True)
        if ema50_p >= ema200_p and ema50_c < ema200_c:
            return SignalResult(strategy_name=self.STRATEGY_NAME, direction="SHORT",
                pattern="Death Cross", structure_score=min(2.0, vol_surge), valid=True)
        return None

    def score(self, df, signal, timeframe, trend_df=None, context_df=None, regime="SIDEWAYS", cfg=None):
        cfg = cfg or {}; weights = self.get_weights(timeframe); direction = signal.direction
        trend_s = self._calc_trend_score(df, direction)
        mom_s   = self._calc_momentum_score(df, direction)
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
