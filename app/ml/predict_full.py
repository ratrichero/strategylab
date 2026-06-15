"""
ML Training Pipeline v2
========================
Walk-forward CV + Random Search Tuning + Platt Calibration
+ Holdout Evaluation + Threshold Sweep + Registry Integration
"""

import os
import json
import time
import joblib
import numpy as np
from datetime import datetime, timezone
from typing import Optional, Dict, List, Tuple

import xgboost as xgb
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score

from app.ml.data import load_dataset, audit_dataset, split_dataset
from app.ml.evaluate import (
    PlattCalibrator,
    compute_fold_metrics,
    aggregate_fold_metrics,
    check_quality_gate,
    threshold_sweep,
    pick_best_threshold,
    compute_calibration_curve,
    calibration_summary,
)
from app.ml.feature_registry import get_feature_names, FEATURE_VERSION
from app.ml.config import TRAIN_CONFIG, MODEL_CONFIG


# ============================================================
# CONFIG
# ============================================================

N_FOLDS       = 5
HOLDOUT_RATIO = 0.20
N_TUNING_TRIALS = 50
MIN_AUC       = 0.54
MAX_OVERFIT   = 0.08
MIN_FOLD_AUC  = 0.50
MODEL_DIR     = TRAIN_CONFIG.model_dir


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def train_model(
    timeframe: Optional[str] = None,
    strategy_name: Optional[str] = None,
    force: bool = False,
    n_tuning_trials: int = N_TUNING_TRIALS,
    min_engine_version: Optional[float] = None,
) -> Dict:
    """
    Full training pipeline:
    1. Load + audit data
    2. Split: dev / holdout
    3. Hyperparameter tuning (random search trên walk-forward CV)
    4. Final model train trên full dev set
    5. Calibration (Platt Scaling)
    6. Holdout evaluation
    7. Threshold sweep trên holdout
    8. Save model + registry
    """

    print("\n" + "="*65)
    print("🚀 ML TRAINING PIPELINE v2")
    print("="*65)

    # ── 1. Load data ───────────────────────────────────────────
    print("\n[1/8] Loading data...")
    X, y, meta = load_dataset(
        timeframe=timeframe,
        strategy_name=strategy_name,
        min_engine_version=min_engine_version,
    )

    if len(y) < TRAIN_CONFIG.min_samples:
        return {
            "status":  "error",
            "message": f"Not enough data: {len(y)} < {TRAIN_CONFIG.min_samples}"
        }

    # ── 2. Audit ───────────────────────────────────────────────
    print("\n[2/8] Auditing dataset...")
    audit = audit_dataset(meta)
    _print_audit(audit)

    if audit.get("warnings"):
        for w in audit["warnings"]:
            print(f"  ⚠️  {w}")
        if not force:
            winrate = audit.get("win_rate", 0.5)
            if winrate < 0.25 or winrate > 0.80:
                return {"status": "error", "message": "Label distribution quá lệch, kiểm tra data"}

    # ── 3. Split ───────────────────────────────────────────────
    print("\n[3/8] Splitting dataset...")
    X_dev, X_hold, y_dev, y_hold, meta_dev, meta_hold = split_dataset(
        X, y, meta, holdout_ratio=HOLDOUT_RATIO
    )

    # ── 4. Hyperparameter tuning ───────────────────────────────
    print(f"\n[4/8] Hyperparameter tuning ({n_tuning_trials} trials)...")
    best_params, tuning_results = _random_search_cv(
        X_dev, y_dev, n_trials=n_tuning_trials, n_folds=N_FOLDS
    )
    print(f"  Best params: {best_params}")
    print(f"  Best avg AUC: {tuning_results['best_auc']:.4f}")

    # ── 5. Walk-forward CV với best params ─────────────────────
    print(f"\n[5/8] Final walk-forward CV ({N_FOLDS} folds)...")
    cv_metrics, train_auc = _walk_forward_cv(
        X_dev, y_dev, params=best_params, n_folds=N_FOLDS
    )
    _print_cv_metrics(cv_metrics)

    # ── Quality gate ───────────────────────────────────────────
    gate_pass, gate_reason = check_quality_gate(
        cv_metrics=cv_metrics,
        train_auc=train_auc,
        min_auc=MIN_AUC,
        max_overfit_gap=MAX_OVERFIT,
        min_fold_auc=MIN_FOLD_AUC,
    )
    print(f"\n  Quality Gate: {'✅ PASSED' if gate_pass else '❌ FAILED'} — {gate_reason}")

    if not gate_pass and not force:
        return {
            "status":     "rejected",
            "reason":     gate_reason,
            "cv_metrics": cv_metrics,
            "audit":      audit,
        }

    # ── 6. Train final model trên full dev set ─────────────────
    print("\n[6/8] Training final model...")
    scale_pos = _calc_scale_pos(y_dev)
    final_model = _train_xgb(X_dev, y_dev, params=best_params, scale_pos=scale_pos)

    # ── 7. Calibration (Platt Scaling trên 20% cuối dev) ───────
    print("\n[7/8] Calibrating model...")
    cal_split = int(len(X_dev) * 0.80)
    X_cal     = X_dev[cal_split:]
    y_cal     = y_dev[cal_split:]

    raw_cal_scores = final_model.predict_proba(X_cal)[:, 1]
    calibrator     = PlattCalibrator()
    calibrator.fit(raw_cal_scores, y_cal)

    cal_probs_cal = calibrator.predict(raw_cal_scores)
    cal_brier_cal = _brier(y_cal, cal_probs_cal)
    print(f"  Calibrator fitted on {len(y_cal)} samples | Brier: {cal_brier_cal:.4f}")

    # ── 8. Holdout evaluation ──────────────────────────────────
    print("\n[8/8] Holdout evaluation...")
    raw_hold   = final_model.predict_proba(X_hold)[:, 1]
    prob_hold  = calibrator.predict(raw_hold)
    hold_auc   = float(roc_auc_score(y_hold, prob_hold))
    hold_brier = _brier(y_hold, prob_hold)

    # Calibration curve trên holdout
    cal_curve  = compute_calibration_curve(y_hold, prob_hold)
    cal_sum    = calibration_summary(cal_curve)

    print(f"  Holdout AUC:   {hold_auc:.4f}")
    print(f"  Holdout Brier: {hold_brier:.4f}")
    print(f"  Calibration:   ECE={cal_sum['ece']:.4f} ({cal_sum['quality']})")

    # Threshold sweep trên holdout
    returns_hold = meta_hold["trade_return"].values if not meta_hold.empty else None
    sweep_df     = threshold_sweep(y_hold, prob_hold, returns=returns_hold)
    best_thresh, best_row = pick_best_threshold(
        sweep_df, primary_metric="sharpe", min_pct_kept=0.30
    )

    print(f"\n  Recommended threshold: {best_thresh}")
    print(f"  At threshold {best_thresh}:")
    print(f"    Trades kept: {best_row['n_trades']} ({best_row['pct_kept']:.0%})")
    print(f"    Winrate:     {best_row['winrate']:.1%}")
    print(f"    Sharpe:      {best_row['sharpe']:.3f}")
    print(f"    PF:          {best_row['profit_factor']:.3f}")

    # ── Save model ─────────────────────────────────────────────
    version    = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    model_path = _save_model_bundle(
        model=final_model,
        calibrator=calibrator,
        version=version,
        timeframe=timeframe,
        strategy_name=strategy_name,
    )
    print(f"\n  ✅ Model saved: {model_path}")

    # ── Save to model_registry ─────────────────────────────────
    _save_to_registry(
        version=version,
        model_path=model_path,
        timeframe=timeframe,
        strategy_name=strategy_name,
        train_size=len(y_dev),
        auc=hold_auc,
        brier=hold_brier,
        recommended_threshold=best_thresh,
        cv_metrics=cv_metrics,
        audit=audit,
    )

    result = {
        "status":       "success",
        "version":      version,
        "model_path":   model_path,
        "train_size":   len(y_dev),
        "holdout_size": len(y_hold),
        "cv_metrics":   cv_metrics,
        "holdout": {
            "auc":           round(hold_auc, 4),
            "brier":         round(hold_brier, 4),
            "calibration":   cal_sum,
        },
        "recommended_threshold": best_thresh,
        "threshold_sweep": sweep_df.to_dict("records"),
        "audit": audit,
        "best_params": best_params,
        "feature_version": FEATURE_VERSION,
        "feature_count": len(get_feature_names()),
    }

    print("\n" + "="*65)
    print("✅ TRAINING COMPLETE")
    print("="*65)

    return result


# ============================================================
# HYPERPARAMETER TUNING
# ============================================================

def _random_search_cv(
    X: np.ndarray,
    y: np.ndarray,
    n_trials: int = 50,
    n_folds: int = 5,
) -> Tuple[Dict, Dict]:
    """
    Random search: thử ngẫu nhiên N tổ hợp params
    Metric tối ưu: avg val AUC qua walk-forward CV
    """
    rng = np.random.RandomState(42)
    best_auc   = -1.0
    best_params = _default_params()
    all_results = []

    print(f"  Running {n_trials} random trials...")

    for trial in range(n_trials):
        params = _sample_params(rng)
        scale_pos = _calc_scale_pos(y)

        fold_aucs = []
        tscv = TimeSeriesSplit(n_splits=n_folds)

        for tr_idx, te_idx in tscv.split(X):
            if len(np.unique(y[te_idx])) < 2:
                continue
            try:
                m = _train_xgb(X[tr_idx], y[tr_idx], params=params, scale_pos=scale_pos)
                prob = m.predict_proba(X[te_idx])[:, 1]
                fold_aucs.append(roc_auc_score(y[te_idx], prob))
            except Exception:
                continue

        if not fold_aucs:
            continue

        avg_auc = float(np.mean(fold_aucs))
        all_results.append({"params": params, "avg_auc": avg_auc})

        if avg_auc > best_auc:
            best_auc   = avg_auc
            best_params = params.copy()

        if (trial + 1) % 10 == 0:
            print(f"  Trial {trial+1}/{n_trials} — best AUC so far: {best_auc:.4f}")

    return best_params, {"best_auc": best_auc, "n_trials": len(all_results)}


def _sample_params(rng: np.random.RandomState) -> Dict:
    return {
        "max_depth":         int(rng.choice([3, 4, 5, 6])),
        "learning_rate":     float(rng.choice([0.01, 0.03, 0.05, 0.10])),
        "n_estimators":      int(rng.choice([100, 200, 300, 500])),
        "min_child_weight":  int(rng.choice([10, 20, 30, 50])),
        "subsample":         float(rng.choice([0.6, 0.7, 0.8, 0.9])),
        "colsample_bytree":  float(rng.choice([0.6, 0.7, 0.8, 0.9])),
        "reg_alpha":         float(rng.choice([0.0, 0.1, 0.5, 1.0])),
        "reg_lambda":        float(rng.choice([0.5, 1.0, 2.0])),
        "gamma":             float(rng.choice([0.0, 0.1, 0.3])),
    }


def _default_params() -> Dict:
    return {
        "max_depth":         4,
        "learning_rate":     0.05,
        "n_estimators":      200,
        "min_child_weight":  20,
        "subsample":         0.8,
        "colsample_bytree":  0.8,
        "reg_alpha":         0.1,
        "reg_lambda":        1.0,
        "gamma":             0.0,
    }


# ============================================================
# WALK-FORWARD CV
# ============================================================

def _walk_forward_cv(
    X: np.ndarray,
    y: np.ndarray,
    params: Dict,
    n_folds: int = 5,
) -> Tuple[Dict, float]:
    """
    Walk-forward CV với given params.
    Returns (cv_metrics, train_auc)
    """
    tscv      = TimeSeriesSplit(n_splits=n_folds)
    fold_mets = []
    scale_pos = _calc_scale_pos(y)

    for fold, (tr_idx, te_idx) in enumerate(tscv.split(X)):
        if len(np.unique(y[te_idx])) < 2:
            continue

        m = _train_xgb(X[tr_idx], y[tr_idx], params=params, scale_pos=scale_pos)

        raw_te = m.predict_proba(X[te_idx])[:, 1]
        raw_tr = m.predict_proba(X[tr_idx])[:, 1]

        auc_tr = float(roc_auc_score(y[tr_idx], raw_tr))
        auc_te = float(roc_auc_score(y[te_idx], raw_te))

        fold_mets.append({
            "fold":        fold + 1,
            "n_train":     len(tr_idx),
            "n_val":       len(te_idx),
            "auc_raw":     round(auc_te, 4),
            "auc_train":   round(auc_tr, 4),
            "overfit_gap": round(auc_tr - auc_te, 4),
        })

        print(
            f"  Fold {fold+1}: train={auc_tr:.4f} val={auc_te:.4f} "
            f"gap={auc_tr-auc_te:.4f}"
        )

    cv = aggregate_fold_metrics(fold_mets)
    cv["fold_details"] = fold_mets
    cv["avg_overfit"]  = round(
        float(np.mean([m["overfit_gap"] for m in fold_mets])), 4
    )

    # Train AUC trên toàn bộ dev (để tính overfit_gap tổng)
    final_m  = _train_xgb(X, y, params=params, scale_pos=scale_pos)
    train_auc = float(roc_auc_score(y, final_m.predict_proba(X)[:, 1]))

    return cv, train_auc


# ============================================================
# XGB HELPERS
# ============================================================

def _train_xgb(
    X: np.ndarray,
    y: np.ndarray,
    params: Dict,
    scale_pos: float = 1.0,
) -> xgb.XGBClassifier:
    m = xgb.XGBClassifier(
        **params,
        scale_pos_weight   = scale_pos,
        eval_metric        = "auc",
        early_stopping_rounds = 50,
        random_state       = 42,
        verbosity          = 0,
        use_label_encoder  = False,
    )
    # Nếu có validation set riêng thì dùng, không thì dùng 10% cuối làm eval
    split = int(len(X) * 0.90)
    if split < len(X):
        m.fit(
            X[:split], y[:split],
            eval_set=[(X[split:], y[split:])],
            verbose=False,
        )
    else:
        m.fit(X, y, verbose=False)
    return m


def _calc_scale_pos(y: np.ndarray) -> float:
    pos = int(y.sum())
    neg = len(y) - pos
    return neg / pos if pos > 0 else 1.0


def _brier(y_true: np.ndarray, y_prob: np.ndarray) -> float:
    from sklearn.metrics import brier_score_loss
    return round(float(brier_score_loss(y_true, y_prob)), 4)


# ============================================================
# SAVE MODEL
# ============================================================

def _save_model_bundle(
    model,
    calibrator: PlattCalibrator,
    version: str,
    timeframe: Optional[str] = None,
    strategy_name: Optional[str] = None,
) -> str:
    """
    Lưu model bundle gồm:
    - model file (.pkl)
    - calibrator file (_calibrator.pkl)
    - metadata file (_meta.json)
    """
    os.makedirs(MODEL_DIR, exist_ok=True)

    suffix = ""
    if timeframe:
        suffix += f"_{timeframe}"
    if strategy_name:
        suffix += f"_{strategy_name}"

    base       = os.path.join(MODEL_DIR, f"xgb{suffix}_{version}")
    model_path = base + ".pkl"
    cal_path   = base + "_calibrator.pkl"
    meta_path  = base + "_meta.json"
    latest     = os.path.join(MODEL_DIR, f"xgb{suffix}_latest.pkl")
    cal_latest = os.path.join(MODEL_DIR, f"xgb{suffix}_latest_calibrator.pkl")

    joblib.dump(model,      model_path)
    joblib.dump(calibrator, cal_path)
    joblib.dump(model,      latest)
    joblib.dump(calibrator, cal_latest)

    meta = {
        "version":          version,
        "feature_version":  FEATURE_VERSION,
        "feature_names":    get_feature_names(),
        "feature_count":    len(get_feature_names()),
        "timeframe":        timeframe,
        "strategy_name":    strategy_name,
        "calibrator_path":  cal_path,
        "created_at":       datetime.now(timezone.utc).isoformat(),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    return model_path


def _save_to_registry(
    version: str,
    model_path: str,
    timeframe: Optional[str],
    strategy_name: Optional[str],
    train_size: int,
    auc: float,
    brier: float,
    recommended_threshold: float,
    cv_metrics: Dict,
    audit: Dict,
):
    """Lưu model vào model_registry DB."""
    try:
        from app.db.session import SessionLocal
        from app.db.models import ModelRegistry
        from app.core.time_utils import utc_now

        with SessionLocal() as db:
            # Deactivate models cũ cùng timeframe/strategy
            old = db.query(ModelRegistry).filter(
                ModelRegistry.is_active == True
            )
            if timeframe:
                old = old.filter(ModelRegistry.timeframe == timeframe)
            old.update({"is_active": False})

            # Insert model mới
            reg = ModelRegistry(
                model_version = version,
                scan_version  = "5.0",
                timeframe     = timeframe or "all",
                features      = json.dumps(get_feature_names()),
                target        = "trade_return_positive",
                train_size    = train_size,
                auc           = round(auc, 4),
                sharpe        = round(recommended_threshold, 4),
                max_drawdown  = round(brier, 4),
                model_path    = model_path,
                is_active     = True,
                created_at    = utc_now(),
            )
            db.add(reg)
            db.commit()
            print(f"  ✅ Saved to model_registry (id={reg.id})")
    except Exception as e:
        print(f"  ⚠️  Registry save error: {e}")


# ============================================================
# PRINT HELPERS
# ============================================================

def _print_audit(audit: Dict):
    print(f"  Total trades:  {audit.get('total_trades', 0)}")
    print(f"  WIN:           {audit.get('win_count', 0)}")
    print(f"  LOSS:          {audit.get('loss_count', 0)}")
    print(f"  Winrate:       {audit.get('win_rate', 0):.1%}")
    print(f"  Date range:    {audit.get('date_range', {}).get('start')} → {audit.get('date_range', {}).get('end')}")


def _print_cv_metrics(cv: Dict):
    print(f"  avg_AUC:      {cv.get('avg_auc', 0):.4f} ± {cv.get('std_auc', 0):.4f}")
    print(f"  min_AUC:      {cv.get('min_auc', 0):.4f}")
    print(f"  avg_overfit:  {cv.get('avg_overfit', 0):.4f}")
    print(f"  fold_AUCs:    {cv.get('fold_aucs', [])}")