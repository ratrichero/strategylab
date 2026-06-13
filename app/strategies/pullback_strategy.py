from typing import Optional, Dict
import pandas as pd
from app.strategies.base import BaseStrategy, SignalResult, StrategyWeights


class PullBackStrategy(BaseStrategy):
    STRATEGY_NAME = "pullback"
    WEIGHTS = {
        "15m": StrategyWeights(trend=0.35, momentum=0.20, volume=0.10, pattern=0.0, mtf=0.25, structure=0.10),
        "1h":  StrategyWeights(trend=0.35, momentum=0.20, volume=0.10, pattern=0.0, mtf=0.25, structure=0.10),
        "4h":  StrategyWeights(trend=0.35, momentum=0.15, volume=0.10, pattern=0.0, mtf=0.30, structure=0.10),
    }
    MIN_EMA_GAP = 0.002; PROXIMITY_ATR = 1.5
    RSI_LONG = (30, 55); RSI_SHORT = (45, 70)

    def detect(self, df, timeframe):
        if len(df) < self.get_min_bars(): return None
        curr = df.iloc[-2]
        ema50 = curr.get("ema50"); ema200 = curr.get("ema200")
        atr = curr.get("atr"); close = curr.get("close"); rsi = curr.get("rsi")
        if not all([ema50, ema200, atr, close, rsi]): return None
        ema50 = float(ema50); ema200 = float(ema200)
        atr = float(atr); close = float(close); rsi = float(rsi)
        if ema200 == 0 or atr <= 0: return None
        ema_gap = (ema50 - ema200) / ema200
        dist = abs(close - ema50)
        if (ema_gap > self.MIN_EMA_GAP and close > ema200 and
                dist <= atr * self.PROXIMITY_ATR and
                self.RSI_LONG[0] < rsi < self.RSI_LONG[1]):
            return SignalResult(strategy_name=self.STRATEGY_NAME, direction="LONG",
                pattern="Bullish Pullback",
                structure_score=self._pb_structure(close, ema50, ema200, atr, ema_gap, "LONG"),
                valid=True)
        if (ema_gap < -self.MIN_EMA_GAP and close < ema200 and
                dist <= atr * self.PROXIMITY_ATR and
                self.RSI_SHORT[0] < rsi < self.RSI_SHORT[1]):
            return SignalResult(strategy_name=self.STRATEGY_NAME, direction="SHORT",
                pattern="Bearish Pullback",
                structure_score=self._pb_structure(close, ema50, ema200, atr, ema_gap, "SHORT"),
                valid=True)
        return None

    def score(self, df, signal, timeframe, trend_df=None, context_df=None, regime="SIDEWAYS", cfg=None):
        cfg = cfg or {}; weights = self.get_weights(timeframe); direction = signal.direction
        trend_s = self._calc_trend_score(df, direction)
        mom_s   = self._pb_momentum(df, direction)
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

    def _pb_momentum(self, df, direction):
        rsi = df.iloc[-1].get("rsi")
        if rsi is None or pd.isna(rsi): return 0.0
        rsi = float(rsi)
        if direction == "LONG":
            if 40 <= rsi <= 55: return 2.5
            elif 35 <= rsi < 40: return 2.0
            elif 30 <= rsi < 35: return 1.5
            elif rsi < 30: return 1.0
        else:
            if 45 <= rsi <= 60: return 2.5
            elif 60 < rsi <= 65: return 2.0
            elif 65 < rsi <= 70: return 1.5
            elif rsi > 70: return 1.0
        return 0.5

    def _pb_structure(self, close, ema50, ema200, atr, ema_gap, direction):
        score = min(1.0, abs(ema_gap)/0.02) * 1.0
        score += max(0, 1 - abs(close-ema50)/atr/2) * 1.0
        return min(2.0, score)
