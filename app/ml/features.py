import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Optional
from app.ml.feature_registry import get_feature_names, FEATURE_VERSION


class FeatureBuilder:
    def __init__(self):
        self.feature_names = get_feature_names()
        self.version = FEATURE_VERSION

    def build_from_scan(self, row, components, direction,
                        indicators_snapshot=None, derivative_data=None,
                        candle_time=None) -> List[float]:
        snap = indicators_snapshot or {}; deriv = derivative_data or {}; f = {}
        f["trend_score_norm"]    = self._div(components.get("trend_score", 0), 3.0)
        f["momentum_score_norm"] = self._div(components.get("momentum_score", 0), 2.5)
        f["volume_score_norm"]   = self._div(components.get("volume_score", 0), 2.5)
        f["pattern_score_norm"]  = self._div(components.get("pattern_score", 0), 2.5)
        f["mtf_score"]           = float(components.get("mtf_score", 0))
        f["penalty_norm"]        = abs(float(components.get("penalty_norm", 0)))
        f["derivative_bias"]     = float(components.get("derivative_bias", 0))
        f["ema_distance"]        = self._clip(float(snap.get("ema_distance", 0) or 0), -0.5, 0.5)
        f["ema200_slope"]        = float(snap.get("ema200_slope", 0) or 0)
        f["ema50_ema200_gap"]    = self._ema_gap(row)
        rsi = self._safe(row.get("rsi"))
        f["rsi_norm"]            = (rsi/100.0) if rsi else 0.5
        f["rsi_slope"]           = float(snap.get("rsi_slope", 0) or 0) / 10.0
        f["rsi_distance_50"]     = abs(rsi-50)/50.0 if rsi else 0.0
        f["atr_ratio"]           = float(snap.get("atr_ratio", 0) or 0)
        f["atr_percentile"]      = float(snap.get("atr_percentile", 0.5) or 0.5)
        f["bb_width"]            = self._clip(float(snap.get("bb_width", 0) or 0), 0, 0.2)
        f["bb_position"]         = float(row.get("bb_position", 0.5) or 0.5)
        f["volume_ratio_norm"]   = self._clip(float(snap.get("volume_ratio", 1) or 1), 0, 5) / 5.0
        f["regime_encoded"]      = self._regime_encode(row)
        f["direction_encoded"]   = 1.0 if direction == "LONG" else 0.0
        f["funding_rate"]        = self._clip(float(deriv.get("funding_rate", 0)), -0.1, 0.1)
        f["oi_change_pct_norm"]  = self._clip(float(deriv.get("oi_change_pct", 0)), -10, 10) / 10.0
        f["ls_ratio_norm"]       = self._clip(float(deriv.get("long_short_ratio", 1)), 0.3, 3.0) / 3.0
        if candle_time:
            f["hour_sin"] = np.sin(2*np.pi*candle_time.hour/24)
            f["hour_cos"] = np.cos(2*np.pi*candle_time.hour/24)
            f["day_of_week_norm"] = candle_time.weekday() / 6.0
        else:
            f["hour_sin"] = 0.0; f["hour_cos"] = 1.0; f["day_of_week_norm"] = 0.0
        return self._to_vector(f)

    def build_from_db(self, feature_row, outcome_row, signal_row=None) -> List[float]:
        f = {}
        f["trend_score_norm"]    = self._div(float(feature_row.trend_score or 0), 3.0)
        f["momentum_score_norm"] = self._div(float(feature_row.momentum_score or 0), 2.5)
        f["volume_score_norm"]   = self._div(float(feature_row.volume_score or 0), 2.5)
        f["pattern_score_norm"]  = self._div(float(feature_row.pattern_score or 0), 2.5)
        f["mtf_score"]           = float(feature_row.mtf_score or 0)
        f["penalty_norm"]        = abs(float(feature_row.penalty_norm or 0))
        f["derivative_bias"]     = 0.0
        f["ema_distance"]        = self._clip(float(feature_row.ema_distance or 0), -0.5, 0.5)
        f["ema200_slope"] = 0.0; f["ema50_ema200_gap"] = 0.0
        rsi = float(feature_row.rsi or 50)
        f["rsi_norm"] = rsi/100.0; f["rsi_slope"] = 0.0; f["rsi_distance_50"] = abs(rsi-50)/50.0
        f["atr_ratio"] = float(feature_row.atr_ratio or 0)
        f["atr_percentile"] = 0.5; f["bb_width"] = 0.0; f["bb_position"] = 0.5
        f["volume_ratio_norm"] = self._clip(float(feature_row.volume_ratio or 1), 0, 5) / 5.0
        regime = feature_row.regime or "SIDEWAYS"
        f["regime_encoded"] = {"BULL": 1.0, "BEAR": 0.0, "SIDEWAYS": 0.5}.get(regime, 0.5)
        direction = signal_row.direction if signal_row else outcome_row.direction
        f["direction_encoded"] = 1.0 if direction == "LONG" else 0.0
        f["funding_rate"] = 0.0; f["oi_change_pct_norm"] = 0.0; f["ls_ratio_norm"] = 1.0/3.0
        if signal_row and signal_row.candle_time:
            ct = signal_row.candle_time
            f["hour_sin"] = np.sin(2*np.pi*ct.hour/24)
            f["hour_cos"] = np.cos(2*np.pi*ct.hour/24)
            f["day_of_week_norm"] = ct.weekday() / 6.0
        else:
            f["hour_sin"] = 0.0; f["hour_cos"] = 1.0; f["day_of_week_norm"] = 0.0
        return self._to_vector(f)

    def _to_vector(self, f):
        out = []
        for name in self.feature_names:
            v = f.get(name, 0.0)
            if v is None or (isinstance(v, float) and np.isnan(v)): v = 0.0
            out.append(float(v))
        return out

    @staticmethod
    def _safe(val):
        if val is None: return None
        try:
            v = float(val); return v if not np.isnan(v) else None
        except: return None

    @staticmethod
    def _div(val, max_val):
        if max_val == 0: return 0.0
        return min(1.0, max(0.0, float(val or 0) / max_val))

    @staticmethod
    def _clip(val, lo, hi):
        return max(lo, min(hi, float(val or 0)))

    @staticmethod
    def _regime_encode(row):
        close = row.get("close", 0); ema200 = row.get("ema200", 0)
        if close and ema200 and float(ema200) != 0:
            r = float(close)/float(ema200)
            if r > 1.002: return 1.0
            if r < 0.998: return 0.0
        return 0.5

    @staticmethod
    def _ema_gap(row):
        ema50 = row.get("ema50"); ema200 = row.get("ema200")
        if ema50 and ema200 and float(ema200) != 0:
            return (float(ema50)-float(ema200))/float(ema200)
        return 0.0


_builder = FeatureBuilder()

def build_features_from_row(row, components, direction,
                             indicators_snapshot=None,
                             derivative_data=None,
                             candle_time=None):
    return _builder.build_from_scan(
        row=row, components=components, direction=direction,
        indicators_snapshot=indicators_snapshot,
        derivative_data=derivative_data, candle_time=candle_time)
