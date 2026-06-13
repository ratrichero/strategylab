import os, json, joblib
import numpy as np
from datetime import datetime
from typing import Optional, Dict

from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score
from sklearn.calibration import CalibratedClassifierCV
import xgboost as xgb

from app.ml.config import MODEL_CONFIG, TRAIN_CONFIG
from app.ml.feature_registry import get_feature_names, FEATURE_VERSION
from app.ml.features import FeatureBuilder


def train_model(timeframe: Optional[str] = None, force: bool = False) -> Dict:
    print("\n" + "="*60 + "\n🚀 TRAINING ML MODEL\n" + "="*60)
    X, y = _build_dataset(timeframe)
    if len(y) < TRAIN_CONFIG.min_samples:
        return {"status": "error", "message": f"Not enough data: {len(y)}"}

    pos = int(y.sum()); neg = len(y) - pos
    scale_pos = neg/pos if pos > 0 else 1.0
    print(f"Data: {len(y)} | WIN={pos} LOSS={neg} | scale={scale_pos:.2f}")

    tscv = TimeSeriesSplit(n_splits=TRAIN_CONFIG.n_cv_splits)
    auc_scores = []; overfit_gaps = []

    for fold, (tr_idx, te_idx) in enumerate(tscv.split(X)):
        X_tr, X_te = X[tr_idx], X[te_idx]
        y_tr, y_te = y[tr_idx], y[te_idx]
        if len(np.unique(y_te)) < 2: continue
        m = _create_model(scale_pos)
        m.fit(X_tr, y_tr, eval_set=[(X_te, y_te)], verbose=False)
        tr_auc = roc_auc_score(y_tr, m.predict_proba(X_tr)[:, 1])
        te_auc = roc_auc_score(y_te, m.predict_proba(X_te)[:, 1])
        auc_scores.append(te_auc); overfit_gaps.append(tr_auc - te_auc)
        print(f"  Fold {fold+1}: Train={tr_auc:.4f} Test={te_auc:.4f} Gap={tr_auc-te_auc:.4f}")

    avg_auc = float(np.mean(auc_scores)); avg_overfit = float(np.mean(overfit_gaps))

    if not force:
        if avg_auc < TRAIN_CONFIG.min_auc:
            return {"status": "rejected", "reason": f"AUC {avg_auc:.4f} < {TRAIN_CONFIG.min_auc}"}
        if avg_overfit > TRAIN_CONFIG.max_overfit_gap:
            return {"status": "rejected", "reason": f"Overfit {avg_overfit:.4f}"}

    split = int(len(X) * 0.9)
    final = _create_model(scale_pos)
    final.fit(X[:split], y[:split], eval_set=[(X[split:], y[split:])], verbose=False)

    try:
        calibrated = CalibratedClassifierCV(final, cv=3, method="sigmoid")
        calibrated.fit(X, y); model_to_save = calibrated
    except: model_to_save = final

    version = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    model_path = _save_model(model_to_save, version, timeframe)

    try:
        imps = final.feature_importances_; names = get_feature_names()
        importance = sorted(zip(names, imps), key=lambda x: x[1], reverse=True)
    except: importance = []

    result = {
        "status": "success", "model_version": version, "model_path": model_path,
        "train_size": len(y), "avg_auc": avg_auc, "avg_overfit": avg_overfit,
        "fold_aucs": [float(a) for a in auc_scores],
        "top_features": [{"feature": n, "importance": float(i)} for n, i in importance[:10]],
        "feature_version": FEATURE_VERSION, "feature_count": len(get_feature_names())
    }
    print(f"\n✅ Model saved: {model_path} | AUC: {avg_auc:.4f}")
    return result


def _build_dataset(timeframe):
    from app.db.session import SessionLocal
    from app.db.models import Signal, SignalFeature, TradeOutcomeAnalytics
    db = SessionLocal()
    query = (db.query(SignalFeature, TradeOutcomeAnalytics, Signal)
             .join(TradeOutcomeAnalytics, SignalFeature.signal_id == TradeOutcomeAnalytics.signal_id)
             .join(Signal, SignalFeature.signal_id == Signal.id)
             .filter(Signal.status.in_(["WIN", "LOSS"]))
             .order_by(Signal.candle_time.asc()))
    if timeframe: query = query.filter(Signal.timeframe == timeframe)
    data = query.all(); db.close()
    builder = FeatureBuilder(); X_list = []; y_list = []
    for feat, outcome, signal in data:
        try:
            X_list.append(builder.build_from_db(feat, outcome, signal))
            y_list.append(1 if outcome.label == 1 else 0)
        except: continue
    return np.array(X_list), np.array(y_list)


def _create_model(scale_pos=1.0):
    cfg = MODEL_CONFIG
    return xgb.XGBClassifier(
        max_depth=cfg.max_depth, n_estimators=cfg.n_estimators,
        learning_rate=cfg.learning_rate, subsample=cfg.subsample,
        colsample_bytree=cfg.colsample_bytree, reg_alpha=cfg.reg_alpha,
        reg_lambda=cfg.reg_lambda, min_child_weight=cfg.min_child_weight,
        gamma=cfg.gamma, scale_pos_weight=scale_pos,
        eval_metric=cfg.eval_metric, early_stopping_rounds=cfg.early_stopping_rounds,
        random_state=cfg.random_state, use_label_encoder=False)


def _save_model(model, version, timeframe):
    model_dir = TRAIN_CONFIG.model_dir; os.makedirs(model_dir, exist_ok=True)
    tf_sfx = f"_{timeframe}" if timeframe else ""; prefix = TRAIN_CONFIG.model_prefix
    model_path = os.path.join(model_dir, f"{prefix}{tf_sfx}_{version}.pkl")
    latest     = os.path.join(model_dir, f"{prefix}{tf_sfx}_latest.pkl")
    joblib.dump(model, model_path); joblib.dump(model, latest)
    meta = {"version": version, "feature_version": FEATURE_VERSION,
            "feature_names": get_feature_names(), "feature_count": len(get_feature_names()),
            "timeframe": timeframe, "created_at": datetime.utcnow().isoformat()}
    with open(model_path.replace(".pkl", "_meta.json"), "w") as fp:
        json.dump(meta, fp, indent=2)
    return model_path
