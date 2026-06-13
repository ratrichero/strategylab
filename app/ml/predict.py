import os, joblib
import numpy as np
from typing import Optional, Dict, Tuple
from app.ml.config import TRAIN_CONFIG
from app.ml.feature_registry import get_feature_count


class PredictionEngine:
    def __init__(self):
        self._models: Dict[str, object] = {}

    def predict(self, features, timeframe=None) -> Optional[float]:
        model = self._get_model(timeframe)
        if model is None: return None
        expected = get_feature_count()
        if len(features) != expected:
            print(f"⚠️ Feature mismatch: {len(features)} vs {expected}"); return None
        clean = [0.0 if (v is None or np.isnan(v)) else float(v) for v in features]
        try:
            return round(float(model.predict_proba([clean])[0][1]), 4)
        except Exception as e:
            print(f"⚠️ Predict error: {e}"); return None

    def predict_with_confidence(self, features, timeframe=None) -> Tuple[Optional[float], str]:
        prob = self.predict(features, timeframe)
        if prob is None: return None, "NONE"
        dist = abs(prob - 0.5)
        if dist >= 0.2: return prob, "HIGH"
        elif dist >= 0.1: return prob, "MEDIUM"
        return prob, "LOW"

    def _get_model(self, timeframe):
        key = timeframe or "default"
        if key not in self._models:
            self._models[key] = self._load_model(timeframe)
        return self._models[key]

    def _load_model(self, timeframe):
        d = TRAIN_CONFIG.model_dir; p = TRAIN_CONFIG.model_prefix
        if timeframe:
            path = os.path.join(d, f"{p}_{timeframe}_latest.pkl")
            if os.path.exists(path): print(f"📦 {path}"); return joblib.load(path)
        path = os.path.join(d, f"{p}_latest.pkl")
        if os.path.exists(path): print(f"📦 {path}"); return joblib.load(path)
        legacy = "app/ml/model.pkl"
        if os.path.exists(legacy): print(f"📦 Legacy: {legacy}"); return joblib.load(legacy)
        print("⚠️ No model found"); return None

    def reload(self, timeframe=None):
        self._models.pop(timeframe or "default", None)
        return self._get_model(timeframe)


_engine = PredictionEngine()

def predict_prob(features, timeframe=None): return _engine.predict(features, timeframe)
def predict_with_confidence(features, timeframe=None): return _engine.predict_with_confidence(features, timeframe)
def reload_model(timeframe=None): return _engine.reload(timeframe)
