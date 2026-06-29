from typing import Optional, Dict
import pandas as pd
from app.strategies.base import BaseStrategy, SignalResult, StrategyWeights


class TrendFollowingStrategy(BaseStrategy):
    STRATEGY_NAME = "trend_following"
    STRATEGY_DESCRIPTION = "EMA crossover + volume confirm → trend following"
    DEFAULT_THRESHOLD = 8.0
    WEIGHTS = {
        "15m": StrategyWeights(trend=0.35, momentum=0.20, volume=0.15, pattern=0.0, mtf=0.25, structure=0.05),
        "1h":  StrategyWeights(trend=0.35, momentum=0.20, volume=0.15, pattern=0.0, mtf=0.25, structure=0.05),
        "4h":  StrategyWeights(trend=0.35, momentum=0.15, volume=0.15, pattern=0.0, mtf=0.30, structure=0.05),
    }

    MIN_VOL_SURGE = 1.2
    MIN_EMA_GAP = 0.003
    ACCEL_EMA_GAP_GROWTH = 0.001

    PAT_GOLDEN_CROSS = "Golden Cross"
    PAT_DEATH_CROSS = "Death Cross"
    PAT_TREND_CONT_LONG = "Trend Continuation Long"
    PAT_TREND_CONT_SHORT = "Trend Continuation Short"
    PAT_MOMENTUM_ACCEL = "Momentum Acceleration"
    PATTERN_THRESHOLDS = {
        PAT_GOLDEN_CROSS: 8.0,
        PAT_DEATH_CROSS: 8.2,
        PAT_TREND_CONT_LONG: 8.0,
        PAT_TREND_CONT_SHORT: 8.2,
        PAT_MOMENTUM_ACCEL: 8.0,
    }

    def detect(self, df, timeframe, symbol=None, trend_df=None, context_df=None, cfg=None):
        if len(df) < self.get_min_bars():
            return None

        curr = df.iloc[-2]
        prev = df.iloc[-3]

        ema50_c = self._to_float(curr.get("ema50"))
        ema200_c = self._to_float(curr.get("ema200"))
        ema50_p = self._to_float(prev.get("ema50"))
        ema200_p = self._to_float(prev.get("ema200"))

        if None in [ema50_c, ema200_c, ema50_p, ema200_p]:
            return None
        if ema200_c == 0:
            return None

        vol_ma = self._to_float(curr.get("vol_ma"))
        volume = self._to_float(curr.get("volume")) or 0
        vol_surge = volume / vol_ma if vol_ma and vol_ma > 0 else 0

        close = self._to_float(curr.get("close"))
        open_ = self._to_float(curr.get("open"))
        rsi = self._to_float(curr.get("rsi"))
        ema200_slope = self._to_float(curr.get("ema200_slope"))
        rsi_slope = self._to_float(curr.get("rsi_slope"))

        if close is None or open_ is None:
            return None

        ema_gap_curr = (ema50_c - ema200_c) / ema200_c
        ema_gap_prev = (ema50_p - ema200_p) / ema200_p if ema200_p != 0 else 0

        # --- Pattern 1: Golden Cross ---
        if ema50_p <= ema200_p and ema50_c > ema200_c and vol_surge >= self.MIN_VOL_SURGE:
            return SignalResult(
                strategy_name=self.STRATEGY_NAME,
                direction="LONG",
                pattern=self.PAT_GOLDEN_CROSS,
                structure_score=min(2.0, vol_surge),
                valid=True,
            )

        # --- Pattern 2: Death Cross ---
        if ema50_p >= ema200_p and ema50_c < ema200_c and vol_surge >= self.MIN_VOL_SURGE:
            return SignalResult(
                strategy_name=self.STRATEGY_NAME,
                direction="SHORT",
                pattern=self.PAT_DEATH_CROSS,
                structure_score=min(2.0, vol_surge),
                valid=True,
            )

        # --- Pattern 3: Trend Continuation Long ---
        if (ema_gap_curr > self.MIN_EMA_GAP and
                ema200_slope is not None and ema200_slope > 0 and
                close > ema50_c and
                close > open_ and
                rsi is not None and 50 <= rsi <= 70 and
                vol_surge >= self.MIN_VOL_SURGE):
            return SignalResult(
                strategy_name=self.STRATEGY_NAME,
                direction="LONG",
                pattern=self.PAT_TREND_CONT_LONG,
                structure_score=min(2.0, abs(ema_gap_curr) * 100),
                valid=True,
            )

        # --- Pattern 4: Trend Continuation Short ---
        if (ema_gap_curr < -self.MIN_EMA_GAP and
                ema200_slope is not None and ema200_slope < 0 and
                close < ema50_c and
                close < open_ and
                rsi is not None and 30 <= rsi <= 50 and
                vol_surge >= self.MIN_VOL_SURGE):
            return SignalResult(
                strategy_name=self.STRATEGY_NAME,
                direction="SHORT",
                pattern=self.PAT_TREND_CONT_SHORT,
                structure_score=min(2.0, abs(ema_gap_curr) * 100),
                valid=True,
            )

        # --- Pattern 5: Momentum Acceleration ---
        gap_growth = abs(ema_gap_curr) - abs(ema_gap_prev)
        if (gap_growth >= self.ACCEL_EMA_GAP_GROWTH and
                abs(ema_gap_curr) > self.MIN_EMA_GAP and
                vol_surge >= self.MIN_VOL_SURGE and
                rsi_slope is not None):

            if ema_gap_curr > 0 and rsi_slope > 0:
                return SignalResult(
                    strategy_name=self.STRATEGY_NAME,
                    direction="LONG",
                    pattern=self.PAT_MOMENTUM_ACCEL,
                    structure_score=min(2.0, gap_growth * 500),
                    valid=True,
                )

            if ema_gap_curr < 0 and rsi_slope < 0:
                return SignalResult(
                    strategy_name=self.STRATEGY_NAME,
                    direction="SHORT",
                    pattern=self.PAT_MOMENTUM_ACCEL,
                    structure_score=min(2.0, gap_growth * 500),
                    valid=True,
                )

        return None

    def score(self, df, signal, timeframe, symbol=None, trend_df=None,
              context_df=None, regime="SIDEWAYS", cfg=None):
        cfg = cfg or {}
        weights = self.get_weights(timeframe)
        direction = signal.direction

        trend_s = self._calc_trend_score(df, direction)
        mom_s = self._calc_momentum_score(df, direction)
        vol_s, vol_ratio = self._calc_volume_score(df, cfg)
        mtf_s = self._calc_mtf_score(direction, trend_df, context_df, cfg)
        _, pen_n = self._calc_penalty(df, direction, regime, vol_ratio, cfg)

        t_n = self._normalize(trend_s, self.MAX_TREND)
        m_n = self._normalize(mom_s, self.MAX_MOMENTUM)
        v_n = self._normalize(vol_s, self.MAX_VOLUME)
        st_n = self._normalize(signal.structure_score, self.MAX_STRUCTURE)

        raw, final = self._apply_weights_and_scale(
            t_n, m_n, v_n, 0.0, mtf_s, st_n, pen_n, weights
        )

        signal.trend_score = trend_s
        signal.momentum_score = mom_s
        signal.volume_score = vol_s
        signal.mtf_score = mtf_s
        signal.penalty_norm = pen_n
        signal.rule_score_raw = raw
        signal.final_score = final
        signal.components = self._build_components(signal, weights)
        return signal

    def _to_float(self, value) -> Optional[float]:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None
