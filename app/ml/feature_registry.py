from dataclasses import dataclass
from typing import List

FEATURE_VERSION = "3.0"

@dataclass
class FeatureDef:
    name: str; category: str; max_val: float
    default: float = 0.0; enabled: bool = True

FEATURE_CATALOG: List[FeatureDef] = [
    FeatureDef("trend_score_norm",    "scoring",     3.0),
    FeatureDef("momentum_score_norm", "scoring",     2.5),
    FeatureDef("volume_score_norm",   "scoring",     2.5),
    FeatureDef("pattern_score_norm",  "scoring",     2.5),
    FeatureDef("mtf_score",           "scoring",     1.0),
    FeatureDef("penalty_norm",        "scoring",     1.9),
    FeatureDef("derivative_bias",     "scoring",     1.0),
    FeatureDef("ema_distance",        "trend",       0.5),
    FeatureDef("ema200_slope",        "trend",       0.01),
    FeatureDef("ema50_ema200_gap",    "trend",       0.1),
    FeatureDef("rsi_norm",            "momentum",    100.0),
    FeatureDef("rsi_slope",           "momentum",    10.0),
    FeatureDef("rsi_distance_50",     "momentum",    50.0),
    FeatureDef("atr_ratio",           "volatility",  0.1),
    FeatureDef("atr_percentile",      "volatility",  1.0),
    FeatureDef("bb_width",            "volatility",  0.2),
    FeatureDef("bb_position",         "volatility",  1.0),
    FeatureDef("volume_ratio_norm",   "volume",      5.0),
    FeatureDef("regime_encoded",      "context",     1.0),
    FeatureDef("direction_encoded",   "context",     1.0),
    FeatureDef("funding_rate",        "derivatives", 0.1),
    FeatureDef("oi_change_pct_norm",  "derivatives", 10.0),
    FeatureDef("ls_ratio_norm",       "derivatives", 3.0),
    FeatureDef("hour_sin",            "time",        1.0),
    FeatureDef("hour_cos",            "time",        1.0),
    FeatureDef("day_of_week_norm",    "time",        6.0),
]

def get_active_features(): return [f for f in FEATURE_CATALOG if f.enabled]
def get_feature_names(): return [f.name for f in get_active_features()]
def get_feature_count(): return len(get_active_features())
