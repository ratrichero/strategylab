from typing import Optional, Tuple
import pandas as pd

from app.strategies.base import BaseStrategy, SignalResult, StrategyWeights


class GridReversionStrategy(BaseStrategy):
    STRATEGY_NAME = "grid_reversion_v1"
    DEFAULT_THRESHOLD = 8.0
    SUPPORTED_TIMEFRAMES = ["15m"]

    WEIGHTS = {
        "15m": StrategyWeights(
            trend=0.20,
            momentum=0.15,
            volume=0.10,
            pattern=0.35,
            mtf=0.20,
            structure=0.0,
        ),
    }

    PATTERN_LOWER_RECLAIM = "Grid Lower Reclaim"
    PATTERN_LOWER_OVERSHOOT = "Grid Lower Overshoot"
    PATTERN_UPPER_REJECT = "Grid Upper Reject"
    PATTERN_UPPER_OVERSHOOT = "Grid Upper Overshoot"
    PATTERN_THRESHOLDS = {
        PATTERN_LOWER_RECLAIM: 8.0,
        PATTERN_LOWER_OVERSHOOT: 8.0,
        PATTERN_UPPER_REJECT: 8.0,
        PATTERN_UPPER_OVERSHOOT: 8.0,
    }

    HTF_RANGE_LOOKBACK = 36
    MIN_RANGE_PCT = 0.01
    MAX_RANGE_PCT = 0.10
    ENTRY_BUFFER_ATR = 0.80
    OVERSHOOT_BUFFER_ATR = 0.35
    ACCEPT_BUFFER_ATR = 0.15
    MAX_ATR_PERCENTILE = 0.90
    STRONG_1H_GAP = 0.020
    STRONG_4H_GAP = 0.030
    MIN_BODY_RATIO = 0.18

    def is_symbol_allowed(self, symbol: str, cfg: dict) -> bool:
        strategy_cfg = self.get_strategy_config(cfg)
        allowed = strategy_cfg.get("symbols")

        # default BTC only nếu không khai báo symbols
        if not allowed:
            return (symbol or "").upper() == "BTCUSDT"

        allowed_symbols = self._parse_symbol_list(allowed)
        if not allowed_symbols:
            return (symbol or "").upper() == "BTCUSDT"

        return (symbol or "").upper() in allowed_symbols

    def detect(self, df, timeframe, symbol=None, trend_df=None, context_df=None, cfg=None):
        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            return None
        if len(df) < self.get_min_bars():
            return None
        if trend_df is None or len(trend_df) < self.HTF_RANGE_LOOKBACK + 5:
            return None

        range_ctx = self._build_anchor_range_context(trend_df)
        if not range_ctx:
            return None

        curr = df.iloc[-2]
        prev = df.iloc[-3]

        atr = self._to_float(curr.get("atr"))
        close = self._to_float(curr.get("close"))
        high = self._to_float(curr.get("high"))
        low = self._to_float(curr.get("low"))

        if None in [atr, close, high, low] or atr <= 0:
            return None

        range_low = range_ctx["range_low"]
        range_high = range_ctx["range_high"]
        entry_buffer = atr * self.ENTRY_BUFFER_ATR
        overshoot_buffer = atr * self.OVERSHOOT_BUFFER_ATR

        bullish_reclaim = self._is_bullish_reclaim_candle(curr, prev)
        bearish_reject = self._is_bearish_reject_candle(curr, prev)

        if low < range_low - overshoot_buffer and close >= range_low and bullish_reclaim:
            return SignalResult(
                strategy_name=self.STRATEGY_NAME,
                direction="LONG",
                pattern=self.PATTERN_LOWER_OVERSHOOT,
                valid=True,
            )

        if low <= range_low + entry_buffer and close >= range_low and bullish_reclaim:
            return SignalResult(
                strategy_name=self.STRATEGY_NAME,
                direction="LONG",
                pattern=self.PATTERN_LOWER_RECLAIM,
                valid=True,
            )

        if high > range_high + overshoot_buffer and close <= range_high and bearish_reject:
            return SignalResult(
                strategy_name=self.STRATEGY_NAME,
                direction="SHORT",
                pattern=self.PATTERN_UPPER_OVERSHOOT,
                valid=True,
            )

        if high >= range_high - entry_buffer and close <= range_high and bearish_reject:
            return SignalResult(
                strategy_name=self.STRATEGY_NAME,
                direction="SHORT",
                pattern=self.PATTERN_UPPER_REJECT,
                valid=True,
            )

        return None

    def score(self, df, signal, timeframe, symbol=None, trend_df=None,
              context_df=None, regime="SIDEWAYS", cfg=None):
        cfg = cfg or {}
        weights = self.get_weights(timeframe)

        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            return self._invalidate(signal, "unsupported_timeframe")

        # 1h anchor là bắt buộc
        if trend_df is None or len(trend_df) < self.HTF_RANGE_LOOKBACK + 5:
            return self._invalidate(signal, "missing_1h_anchor")

        range_ctx = self._build_anchor_range_context(trend_df)
        if not range_ctx:
            return self._invalidate(signal, "invalid_1h_range")

        last = df.iloc[-1]
        atr_percentile = self._to_float(last.get("atr_percentile"))
        if atr_percentile is not None and atr_percentile > self.MAX_ATR_PERCENTILE:
            return self._invalidate(signal, "atr_hot")

        if self._accepted_outside_range(signal.direction, df, range_ctx):
            return self._invalidate(signal, "accept_outside_range")

        if self._is_strong_htf_trend_against(signal.direction, trend_df, context_df):
            return self._invalidate(signal, "htf_trend_against")

        trend_s = self._calc_range_balance_score(df, trend_df, context_df, range_ctx)
        mom_s = self._calc_reversion_momentum_score(df, signal.direction)
        vol_s, vol_ratio = self._calc_volume_suitability_score(df)
        pat_s = self._calc_location_reaction_score(df, signal.pattern, signal.direction, range_ctx)
        mtf_s = self._calc_mtf_safety_score(signal.direction, trend_df, context_df, regime)
        pen_n = self._calc_grid_penalty(df, signal.direction, vol_ratio, trend_df, context_df, regime)

        t_n = self._normalize(trend_s, self.MAX_TREND)
        m_n = self._normalize(mom_s, self.MAX_MOMENTUM)
        v_n = self._normalize(vol_s, self.MAX_VOLUME)
        p_n = self._normalize(pat_s, self.MAX_PATTERN)

        raw, final = self._apply_weights_and_scale(
            t_n, m_n, v_n, p_n, mtf_s, 0.0, pen_n, weights
        )

        signal.trend_score = trend_s
        signal.momentum_score = mom_s
        signal.volume_score = vol_s
        signal.pattern_score = pat_s
        signal.mtf_score = mtf_s
        signal.penalty_norm = pen_n
        signal.rule_score_raw = raw
        signal.final_score = final
        signal.components = self._build_components(signal, weights)
        return signal

    def _build_anchor_range_context(self, trend_df) -> Optional[dict]:
        # 1h anchor range, bỏ cây cuối để tránh dùng chính candle hiện tại làm méo range
        window = trend_df.iloc[-(self.HTF_RANGE_LOOKBACK + 1):-1]
        if len(window) < self.HTF_RANGE_LOOKBACK:
            return None

        range_high = self._to_float(window["high"].max())
        range_low = self._to_float(window["low"].min())
        if None in [range_high, range_low] or range_high <= range_low:
            return None

        range_mid = (range_high + range_low) / 2
        if range_mid <= 0:
            return None

        range_width = range_high - range_low
        range_pct = range_width / range_mid
        if range_pct < self.MIN_RANGE_PCT or range_pct > self.MAX_RANGE_PCT:
            return None

        last = trend_df.iloc[-1]
        ema50 = self._to_float(last.get("ema50"))
        ema200 = self._to_float(last.get("ema200"))
        ema_gap = None
        if ema50 is not None and ema200 is not None and ema200 != 0:
            ema_gap = (ema50 - ema200) / ema200

        return {
            "range_high": range_high,
            "range_low": range_low,
            "range_mid": range_mid,
            "range_width": range_width,
            "range_pct": range_pct,
            "anchor_ema_gap": ema_gap,
        }

    def _is_bullish_reclaim_candle(self, curr, prev) -> bool:
        close = self._to_float(curr.get("close"))
        open_ = self._to_float(curr.get("open"))
        high = self._to_float(curr.get("high"))
        low = self._to_float(curr.get("low"))
        if None in [close, open_, high, low]:
            return False

        body = abs(close - open_)
        full_range = high - low
        if full_range <= 0:
            return False

        lower_wick = min(close, open_) - low
        body_ratio = body / full_range if full_range > 0 else 0

        prev_open = self._to_float(prev.get("open"))
        prev_close = self._to_float(prev.get("close"))
        engulfing = False
        if prev_open is not None and prev_close is not None:
            engulfing = (
                prev_close < prev_open and
                close > open_ and
                open_ <= prev_close and
                close >= prev_open
            )

        wick_reclaim = close > open_ and lower_wick >= body * 1.2 and body_ratio >= self.MIN_BODY_RATIO
        return wick_reclaim or engulfing

    def _is_bearish_reject_candle(self, curr, prev) -> bool:
        close = self._to_float(curr.get("close"))
        open_ = self._to_float(curr.get("open"))
        high = self._to_float(curr.get("high"))
        low = self._to_float(curr.get("low"))
        if None in [close, open_, high, low]:
            return False

        body = abs(close - open_)
        full_range = high - low
        if full_range <= 0:
            return False

        upper_wick = high - max(close, open_)
        body_ratio = body / full_range if full_range > 0 else 0

        prev_open = self._to_float(prev.get("open"))
        prev_close = self._to_float(prev.get("close"))
        engulfing = False
        if prev_open is not None and prev_close is not None:
            engulfing = (
                prev_close > prev_open and
                close < open_ and
                open_ >= prev_close and
                close <= prev_open
            )

        wick_reject = close < open_ and upper_wick >= body * 1.2 and body_ratio >= self.MIN_BODY_RATIO
        return wick_reject or engulfing

    def _accepted_outside_range(self, direction: str, df, range_ctx: dict) -> bool:
        curr = df.iloc[-2]
        last = df.iloc[-1]

        curr_close = self._to_float(curr.get("close"))
        last_close = self._to_float(last.get("close"))
        atr = self._to_float(last.get("atr")) or self._to_float(curr.get("atr"))

        if None in [curr_close, last_close, atr] or atr <= 0:
            return False

        accept_buffer = atr * self.ACCEPT_BUFFER_ATR

        if direction == "LONG":
            return (
                curr_close < (range_ctx["range_low"] - accept_buffer) and
                last_close < (range_ctx["range_low"] - accept_buffer)
            )

        return (
            curr_close > (range_ctx["range_high"] + accept_buffer) and
            last_close > (range_ctx["range_high"] + accept_buffer)
        )

    def _is_strong_htf_trend_against(self, direction: str, trend_df, context_df) -> bool:
        checks = [
            (trend_df, self.STRONG_1H_GAP),
            (context_df, self.STRONG_4H_GAP),
        ]

        for htf_df, strong_gap in checks:
            if htf_df is None or len(htf_df) < 50:
                continue

            last = htf_df.iloc[-1]
            ema50 = self._to_float(last.get("ema50"))
            ema200 = self._to_float(last.get("ema200"))
            slope = self._to_float(last.get("ema200_slope"))
            if None in [ema50, ema200, slope] or ema200 == 0:
                continue

            gap = (ema50 - ema200) / ema200

            if direction == "LONG" and gap < -strong_gap and slope < 0:
                return True
            if direction == "SHORT" and gap > strong_gap and slope > 0:
                return True

        return False

    def _calc_range_balance_score(self, df, trend_df, context_df, range_ctx: dict) -> float:
        score = 0.0

        range_pct = range_ctx["range_pct"]
        if 0.015 <= range_pct <= 0.06:
            score += 1.0
        elif 0.01 <= range_pct <= 0.08:
            score += 0.5

        anchor_gap = range_ctx.get("anchor_ema_gap")
        if anchor_gap is not None:
            anchor_gap = abs(anchor_gap)
            if anchor_gap <= 0.010:
                score += 1.0
            elif anchor_gap <= 0.018:
                score += 0.5

        last = df.iloc[-1]
        atr_percentile = self._to_float(last.get("atr_percentile"))
        if atr_percentile is not None:
            if atr_percentile <= 0.60:
                score += 0.6
            elif atr_percentile <= 0.75:
                score += 0.3

        if context_df is not None and len(context_df) >= 50:
            ctx_last = context_df.iloc[-1]
            ctx_ema50 = self._to_float(ctx_last.get("ema50"))
            ctx_ema200 = self._to_float(ctx_last.get("ema200"))
            if ctx_ema50 is not None and ctx_ema200 is not None and ctx_ema200 != 0:
                ctx_gap = abs((ctx_ema50 - ctx_ema200) / ctx_ema200)
                if ctx_gap <= 0.020:
                    score += 0.4
                elif ctx_gap <= 0.035:
                    score += 0.2

        return min(self.MAX_TREND, score)

    def _calc_reversion_momentum_score(self, df, direction: str) -> float:
        curr = df.iloc[-2]
        last = df.iloc[-1]

        rsi = self._to_float(last.get("rsi"))
        rsi_slope = self._to_float(last.get("rsi_slope"))
        curr_close = self._to_float(curr.get("close"))
        last_close = self._to_float(last.get("close"))

        if rsi is None:
            return 0.0

        score = 0.0
        if direction == "LONG":
            if 30 <= rsi <= 45:
                score += 1.5
            elif 45 < rsi <= 55:
                score += 1.0
            elif rsi < 30:
                score += 0.5

            if rsi_slope is not None and rsi_slope > 0:
                score += 0.7
            if curr_close is not None and last_close is not None and last_close >= curr_close:
                score += 0.3
        else:
            if 55 <= rsi <= 70:
                score += 1.5
            elif 45 <= rsi < 55:
                score += 1.0
            elif rsi > 70:
                score += 0.5

            if rsi_slope is not None and rsi_slope < 0:
                score += 0.7
            if curr_close is not None and last_close is not None and last_close <= curr_close:
                score += 0.3

        return min(self.MAX_MOMENTUM, score)

    def _calc_volume_suitability_score(self, df) -> Tuple[float, Optional[float]]:
        curr = df.iloc[-2]
        vol_ma = self._to_float(curr.get("vol_ma"))
        volume = self._to_float(curr.get("volume"))
        if vol_ma is None or volume is None or vol_ma <= 0:
            return 0.0, None

        vol_ratio = volume / vol_ma

        if 0.9 <= vol_ratio <= 1.8:
            return 2.0, vol_ratio
        if 0.7 <= vol_ratio < 0.9:
            return 1.0, vol_ratio
        if 1.8 < vol_ratio <= 2.2:
            return 1.0, vol_ratio
        if 2.2 < vol_ratio <= 3.0:
            return 0.5, vol_ratio
        return 0.0, vol_ratio

    def _calc_location_reaction_score(self, df, pattern: str, direction: str, range_ctx: dict) -> float:
        curr = df.iloc[-2]
        last = df.iloc[-1]

        close = self._to_float(curr.get("close"))
        open_ = self._to_float(curr.get("open"))
        high = self._to_float(curr.get("high"))
        low = self._to_float(curr.get("low"))
        atr = self._to_float(curr.get("atr"))
        confirm_close = self._to_float(last.get("close"))

        if None in [close, open_, high, low, atr] or atr <= 0:
            return 0.0

        body = abs(close - open_)
        upper_wick = high - max(close, open_)
        lower_wick = min(close, open_) - low
        score = 0.0

        if direction == "LONG":
            band_dist = max(0.0, close - range_ctx["range_low"])
            closeness = max(0.0, 1.0 - min(1.0, band_dist / (atr * 2.0)))
            score += 1.2 * closeness

            if lower_wick > body * 1.5:
                score += 0.5
            if close > open_:
                score += 0.3
            if confirm_close is not None and confirm_close >= close:
                score += 0.2
            if "Overshoot" in (pattern or "") and low < range_ctx["range_low"]:
                overshoot_depth = min(1.0, (range_ctx["range_low"] - low) / (atr * 1.5))
                score += 0.3 + 0.3 * overshoot_depth
        else:
            band_dist = max(0.0, range_ctx["range_high"] - close)
            closeness = max(0.0, 1.0 - min(1.0, band_dist / (atr * 2.0)))
            score += 1.2 * closeness

            if upper_wick > body * 1.5:
                score += 0.5
            if close < open_:
                score += 0.3
            if confirm_close is not None and confirm_close <= close:
                score += 0.2
            if "Overshoot" in (pattern or "") and high > range_ctx["range_high"]:
                overshoot_depth = min(1.0, (high - range_ctx["range_high"]) / (atr * 1.5))
                score += 0.3 + 0.3 * overshoot_depth

        return min(self.MAX_PATTERN, score)

    def _calc_mtf_safety_score(self, direction: str, trend_df, context_df, regime: str) -> float:
        score = 0.40

        if regime == "SIDEWAYS":
            score += 0.20
        elif direction == "LONG" and regime == "BEAR":
            score -= 0.10
        elif direction == "SHORT" and regime == "BULL":
            score -= 0.10

        trend_last = trend_df.iloc[-1] if trend_df is not None and len(trend_df) >= 50 else None
        if trend_last is not None:
            ema50 = self._to_float(trend_last.get("ema50"))
            ema200 = self._to_float(trend_last.get("ema200"))
            if ema50 is not None and ema200 is not None and ema200 != 0:
                gap = (ema50 - ema200) / ema200
                if abs(gap) <= 0.012:
                    score += 0.20
                elif abs(gap) <= 0.020:
                    score += 0.10

        if context_df is not None and len(context_df) >= 50:
            ctx_last = context_df.iloc[-1]
            ema50 = self._to_float(ctx_last.get("ema50"))
            ema200 = self._to_float(ctx_last.get("ema200"))
            if ema50 is not None and ema200 is not None and ema200 != 0:
                gap = (ema50 - ema200) / ema200
                if direction == "LONG":
                    if gap >= 0:
                        score += 0.10
                    elif abs(gap) <= 0.015:
                        score += 0.05
                else:
                    if gap <= 0:
                        score += 0.10
                    elif abs(gap) <= 0.015:
                        score += 0.05

        return max(0.0, min(1.0, score))

    def _calc_grid_penalty(self, df, direction: str, vol_ratio: Optional[float], trend_df, context_df, regime: str) -> float:
        penalty = 0.0

        last = df.iloc[-1]
        atr_percentile = self._to_float(last.get("atr_percentile"))
        if atr_percentile is not None and atr_percentile > 0.75:
            penalty -= 0.10

        if vol_ratio is not None and vol_ratio > 2.5:
            penalty -= 0.10

        if direction == "LONG" and regime == "BEAR":
            penalty -= 0.05
        elif direction == "SHORT" and regime == "BULL":
            penalty -= 0.05

        if context_df is not None and len(context_df) >= 50:
            ctx_last = context_df.iloc[-1]
            ctx_ema50 = self._to_float(ctx_last.get("ema50"))
            ctx_ema200 = self._to_float(ctx_last.get("ema200"))
            if ctx_ema50 is not None and ctx_ema200 is not None and ctx_ema200 != 0:
                ctx_gap = (ctx_ema50 - ctx_ema200) / ctx_ema200
                if direction == "LONG" and ctx_gap < -0.02:
                    penalty -= 0.05
                if direction == "SHORT" and ctx_gap > 0.02:
                    penalty -= 0.05

        return penalty

    def _to_float(self, value) -> Optional[float]:
        try:
            if value is None or pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None
