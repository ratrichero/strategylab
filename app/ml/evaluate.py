import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional
from app.ml.predict import predict_prob
from app.ml.features import FeatureBuilder


def evaluate_recent(days: int = 30, timeframe: Optional[str] = None) -> Dict:
    from app.db.session import SessionLocal
    from app.db.models import Signal, SignalFeature, TradeOutcomeAnalytics
    db = SessionLocal(); cutoff = datetime.utcnow() - timedelta(days=days)
    builder = FeatureBuilder()
    query = (db.query(Signal, SignalFeature, TradeOutcomeAnalytics)
             .join(SignalFeature, Signal.id == SignalFeature.signal_id)
             .join(TradeOutcomeAnalytics, Signal.id == TradeOutcomeAnalytics.signal_id)
             .filter(Signal.status.in_(["WIN","LOSS"]), Signal.candle_time >= cutoff)
             .order_by(Signal.candle_time.asc()))
    if timeframe: query = query.filter(Signal.timeframe == timeframe)
    data = query.all(); db.close()
    if not data: return {"error": "No data", "period_days": days}
    preds = []; actuals = []; returns = []
    for signal, feature, outcome in data:
        features = builder.build_from_db(feature, outcome, signal)
        prob = predict_prob(features, signal.timeframe)
        if prob is not None:
            preds.append(prob); actuals.append(1 if outcome.label == 1 else 0)
            returns.append(float(signal.result_percent or 0))
    if not preds: return {"error": "No predictions", "period_days": days}
    preds = np.array(preds); actuals = np.array(actuals); returns = np.array(returns)
    from sklearn.metrics import roc_auc_score
    auc = roc_auc_score(actuals, preds)
    thresholds = []
    for t in [0.4, 0.5, 0.55, 0.6, 0.65, 0.7]:
        mask = preds >= t
        if mask.sum() == 0: continue
        fr = returns[mask]; fa = actuals[mask]
        thresholds.append({
            "threshold": t, "n_signals": int(mask.sum()),
            "winrate": float(fa.mean()), "avg_return": float(fr.mean()),
            "total_return": float(fr.sum()),
            "sharpe": float(fr.mean()/(fr.std()+1e-10)*np.sqrt(252))
        })
    return {"period_days": days, "total_signals": len(preds), "auc": float(auc),
            "overall_winrate": float(actuals.mean()),
            "overall_avg_return": float(returns.mean()),
            "threshold_analysis": thresholds}


def detect_drift(window_days: int = 7) -> Dict:
    recent = evaluate_recent(days=window_days)
    previous = evaluate_recent(days=window_days*2)
    if "error" in recent or "error" in previous:
        return {"drift_detected": False, "reason": "not_enough_data"}
    auc_drop = previous["auc"] - recent["auc"]
    return {"drift_detected": auc_drop > 0.05,
            "auc_recent": recent["auc"], "auc_previous": previous["auc"],
            "auc_drop": auc_drop,
            "recommendation": "RETRAIN" if auc_drop > 0.05 else "MONITOR" if auc_drop > 0.03 else "OK"}
