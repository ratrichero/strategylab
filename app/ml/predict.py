import os
from typing import Optional, Dict, Tuple

import joblib
import numpy as np


class PredictionEngine:
    """
    Backward-compatible prediction engine.

    Nếu chưa có model:
      - predict() trả None
      - scan flow vẫn chạy bình thường
    """

    def __init__(self):
        self._models: Dict[str, object] = {}

    def predict(self, features, timeframe=None) -> Optional[float]:
        model = self._get_model(timeframe)
        if model is None:
            return None

        try:
            clean = []
            for v in features:
                if v is None:
                    clean.append(0.0)
                else:
                    try:
                        fv = float(v)
                        if np.isnan(fv):
                            clean.append(0.0)
                        else:
                            clean.append(fv)
                    except Exception:
                        clean.append(0.0)

            prob = float(model.predict_proba([clean])[0][1])
            return round(prob, 4)
        except Exception as e:
            print(f"⚠️ Predict error: {e}")
            return None

    def predict_with_confidence(self, features, timeframe=None) -> Tuple[Optional[float], str]:
        prob = self.predict(features, timeframe)
        if prob is None:
            return None, "NONE"

        dist = abs(prob - 0.5)
        if dist >= 0.20:
            return prob, "HIGH"
        elif dist >= 0.10:
            return prob, "MEDIUM"
        return prob, "LOW"

    def _get_model(self, timeframe):
        key = timeframe or "default"
        if key not in self._models:
            self._models[key] = self._load_model(timeframe)
        return self._models[key]

    def _load_model(self, timeframe):
        # Ưu tiên model mới nếu có
        candidates = []

        if timeframe:
            candidates.append(os.path.join("models", f"xgb_{timeframe}_latest.pkl"))

        candidates.extend([
            os.path.join("models", "xgb_latest.pkl"),
            os.path.join("app", "ml", "model.pkl"),  # legacy fallback
        ])

        for path in candidates:
            if os.path.exists(path):
                try:
                    print(f"📦 Loading model: {path}")
                    return joblib.load(path)
                except Exception as e:
                    print(f"⚠️ Failed to load model {path}: {e}")

        # Không có model cũng không crash
        print("⚠️ No ML model found — predict_prob will return None")
        return None

    def reload(self, timeframe=None):
        key = timeframe or "default"
        self._models.pop(key, None)
        return self._get_model(timeframe)


_engine = PredictionEngine()


def predict_prob(features, timeframe=None):
    return _engine.predict(features, timeframe)


def predict_with_confidence(features, timeframe=None):
    return _engine.predict_with_confidence(features, timeframe)


def reload_model(timeframe=None):
    return _engine.reload(timeframe)