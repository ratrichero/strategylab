import pandas as pd
import numpy as np


class MTFCalculator:

    # ─────────────────────────────────────────────
    # Dynamic timeframe mapping
    # ─────────────────────────────────────────────
    MTF_TIMEFRAME_MAP = {
        "15m": {"trend": "4h", "context": "1d"},
        "1h":  {"trend": "4h", "context": "1d"},
        "4h":  {"trend": "1d", "context": None},
    }

    @classmethod
    def get_timeframe_map(cls, entry_tf: str):
        return cls.MTF_TIMEFRAME_MAP.get(entry_tf, {"trend": None, "context": None})

    # ─────────────────────────────────────────────
    # Safe getter
    # ─────────────────────────────────────────────
    @staticmethod
    def _safe(row, key):
        val = row.get(key)
        if val is None or pd.isna(val):
            return None
        return float(val)

    # ─────────────────────────────────────────────
    # RSI Trend-Following Peaked Score
    # ─────────────────────────────────────────────
    @staticmethod
    def _rsi_trend_score(rsi: float, direction: str) -> float:

        if rsi is None:
            return 0.0

        # LONG logic
        if direction == "LONG":
            if 50 <= rsi <= 70:
                return (rsi - 50) / 20  # peak at 70 (1.0)
            elif 70 < rsi <= 85:
                return max(0.0, 1 - (rsi - 70) / 15)
            else:
                return 0.0

        # SHORT logic
        else:
            if 30 <= rsi <= 50:
                return (50 - rsi) / 20
            elif 15 <= rsi < 30:
                return max(0.0, 1 - (30 - rsi) / 15)
            elif rsi > 50:
            # ✅ FIX: RSI > 50 nhưng SHORT vẫn có partial score
            # RSI=55 → 0.0, RSI=70 → -0.25 (không dùng)
            # Thêm soft zone 50-60: score nhỏ dần
                if rsi <= 60:
                    return max(0.0, (60 - rsi) / 40)  # 0.25 → 0.0
            return 0.0
            

    # ─────────────────────────────────────────────
    # ATR-normalized Distance with Guard
    # ─────────────────────────────────────────────
    @staticmethod
    def _atr_distance(close, ema200, atr, direction):

        # Guard against extreme small ATR
        if atr is None or atr <= 0:
            return 0.0

        if atr / close < 0.0005:  # ATR < 0.05% of price
            return 0.0

        distance_atr = (close - ema200) / atr

        if direction == "LONG":

            if distance_atr >= 0:
                # ✅ Close TRÊN ema200 → thuận trend LONG
                return min(1.0, distance_atr / 3.0)

            else:
                # ✅ Close DƯỚI ema200 → against-trend
                # Mirror SHORT: soft decay, floor = 0.0 (không ưu đãi)
                val = 0.1 - (-distance_atr) / 6.0
                #
                # distance_atr = -0.1 → 0.1 - 0.017 = 0.083  (hơi dưới, vẫn có score nhỏ)
                # distance_atr = -0.6 → 0.1 - 0.100 = 0.000  (xa hơn → về 0)
                # distance_atr = -2.0 → 0.1 - 0.333 = 0.000  (rất xa → 0)
                return max(0.0, val)

        else:

            if distance_atr >= 0:
                # ✅ FIX: close > ema200 tức là ĐANG trên trend
                # SHORT vẫn hợp lệ nếu vừa break xuống
                # Tăng soft floor từ 0.0 → 0.05
                val = 0.1 - distance_atr / 6.0
                return max(0.05, val)   # ← không về 0 cứng
                #return max(0.0, 0.1 - distance_atr / 6.0)

            return min(1.0, -distance_atr / 3.0)

    # ─────────────────────────────────────────────
    # MAIN MTF FUNCTION
    # ─────────────────────────────────────────────
    @classmethod
    def compute_mtf_score(cls,
                          direction: str,
                          trend_df: pd.DataFrame,
                          context_df: pd.DataFrame = None) -> float:

        if trend_df is None or len(trend_df) < 50:
            return 0.0

        trend_last = trend_df.iloc[-1]

        close_t = cls._safe(trend_last, "close")
        ema200_t = cls._safe(trend_last, "ema200")
        ema50_t = cls._safe(trend_last, "ema50")
        rsi_t = cls._safe(trend_last, "rsi")
        atr_t = cls._safe(trend_last, "atr")

        """print(
            f"[MTF DEBUG] direction={direction} | "
            f"ATR={atr_t} | Close={close_t} | "
            f"ATR/Close={(atr_t/close_t) if (atr_t and close_t) else None}"
        )"""

        if close_t is None or ema200_t is None:
            return 0.0
        
        # ───────── Trend Layer ─────────

        distance_component = cls._atr_distance(
            close_t, ema200_t, atr_t, direction
        )

        # Smooth structure component
        structure_component = 0.0
        if ema50_t is not None and ema200_t != 0:
            ema_gap = (ema50_t - ema200_t) / ema200_t

            if direction == "LONG" and ema_gap > 0:
                structure_component = min(1.0, ema_gap * 50)

            elif direction == "SHORT" and ema_gap < 0:
                structure_component = min(1.0, -ema_gap * 50)

        rsi_component = cls._rsi_trend_score(rsi_t, direction)

        """print(
            f"[MTF TREND DEBUG] direction={direction} | "
            f"distance_component={distance_component:.4f} | "
            f"struct={structure_component:.4f} | "
            f"rsi={rsi_component:.4f}"
        )"""

        trend_layer = (
            0.5 * distance_component +
            0.25 * structure_component +
            0.25 * rsi_component
        )

        trend_layer = max(0.0, min(1.0, trend_layer))

        # ───────── Context Layer ─────────

        context_available = (
            context_df is not None and len(context_df) >= 50
        )

        context_layer = 0.0

        if context_available:

            ctx_last = context_df.iloc[-1]

            close_c = cls._safe(ctx_last, "close")
            ema200_c = cls._safe(ctx_last, "ema200")
            rsi_c = cls._safe(ctx_last, "rsi")
            atr_c = cls._safe(ctx_last, "atr")

            if close_c is not None and ema200_c is not None:

                distance_ctx = cls._atr_distance(
                    close_c, ema200_c, atr_c, direction
                )

                rsi_ctx_component = 0.0

                if rsi_c is not None:

                    if direction == "LONG" and rsi_c > 50:
                        rsi_ctx_component = min(1.0, (rsi_c - 50) / 30)

                    elif direction == "SHORT" and rsi_c < 50:
                        rsi_ctx_component = min(1.0, (50 - rsi_c) / 30)

                context_layer = (
                    0.7 * distance_ctx +
                    0.3 * rsi_ctx_component
                )

                context_layer = max(0.0, min(1.0, context_layer))

        # ───────── Final Combine ─────────

        if context_available:
            mtf_score = 0.65 * trend_layer + 0.35 * context_layer
        else:
            mtf_score = trend_layer

        
        return round(max(0.0, min(1.0, mtf_score)), 4)