"""
ML Evaluation Pipeline
======================
Metrics + calibration curve + threshold sweep.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from sklearn.metrics import roc_auc_score, brier_score_loss
from sklearn.linear_model import LogisticRegression


# ============================================================
# CALIBRATION
# ============================================================

class PlattCalibrator:
    """
    Platt Scaling: fit logistic regression trên raw scores.
    Phù hợp với 200-1000 mẫu.
    """
    def __init__(self):
        self._lr = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
        self._fitted = False

    def fit(self, raw_scores: np.ndarray, y_true: np.ndarray):
        scores_2d = raw_scores.reshape(-1, 1)
        self._lr.fit(scores_2d, y_true)
        self._fitted = True
        return self

    def predict(self, raw_scores: np.ndarray) -> np.ndarray:
        if not self._fitted:
            return raw_scores
        scores_2d = raw_scores.reshape(-1, 1)
        return self._lr.predict_proba(scores_2d)[:, 1]

    def predict_single(self, raw_score: float) -> float:
        return float(self.predict(np.array([raw_score]))[0])


# ============================================================
# METRICS
# ============================================================

def compute_fold_metrics(
    y_true: np.ndarray,
    y_pred_raw: np.ndarray,
    y_pred_calibrated: Optional[np.ndarray] = None,
    fold: int = 0,
) -> Dict:
    """
    Tính metrics cho 1 fold.
    """
    if len(np.unique(y_true)) < 2:
        return {"fold": fold, "auc": None, "brier": None, "n_samples": len(y_true)}

    auc_raw = float(roc_auc_score(y_true, y_pred_raw))

    result = {
        "fold":       fold,
        "n_samples":  len(y_true),
        "n_pos":      int(y_true.sum()),
        "n_neg":      int((y_true == 0).sum()),
        "auc_raw":    round(auc_raw, 4),
        "brier_raw":  round(float(brier_score_loss(y_true, y_pred_raw)), 4),
    }

    if y_pred_calibrated is not None:
        result["auc_calibrated"]   = round(float(roc_auc_score(y_true, y_pred_calibrated)), 4)
        result["brier_calibrated"] = round(float(brier_score_loss(y_true, y_pred_calibrated)), 4)

    return result


def aggregate_fold_metrics(fold_metrics: List[Dict]) -> Dict:
    """
    Aggregate metrics across all folds.
    """
    valid = [m for m in fold_metrics if m.get("auc_raw") is not None]
    if not valid:
        return {"status": "no_valid_folds"}

    aucs    = [m["auc_raw"] for m in valid]
    briers  = [m["brier_raw"] for m in valid]

    return {
        "n_folds":        len(valid),
        "avg_auc":        round(float(np.mean(aucs)), 4),
        "std_auc":        round(float(np.std(aucs)), 4),
        "min_auc":        round(float(np.min(aucs)), 4),
        "max_auc":        round(float(np.max(aucs)), 4),
        "avg_brier":      round(float(np.mean(briers)), 4),
        "fold_aucs":      [round(a, 4) for a in aucs],
        "fold_briers":    [round(b, 4) for b in briers],
    }


# ============================================================
# QUALITY GATE
# ============================================================

def check_quality_gate(
    cv_metrics: Dict,
    train_auc: float,
    min_auc: float = 0.54,
    max_overfit_gap: float = 0.08,
    min_fold_auc: float = 0.50,
) -> Tuple[bool, str]:
    """
    Kiểm tra model có đủ chất lượng để deploy không.

    Returns:
        (passed: bool, reason: str)
    """
    avg_auc = cv_metrics.get("avg_auc", 0)
    min_f   = cv_metrics.get("min_auc", 0)
    overfit = train_auc - avg_auc

    if avg_auc < min_auc:
        return False, f"avg_AUC {avg_auc:.4f} < min {min_auc}"

    if min_f < min_fold_auc:
        return False, f"min_fold_AUC {min_f:.4f} < {min_fold_auc}"

    if overfit > max_overfit_gap:
        return False, f"overfit_gap {overfit:.4f} > max {max_overfit_gap}"

    return True, "PASSED"


# ============================================================
# THRESHOLD SWEEP
# ============================================================

def threshold_sweep(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    thresholds: Optional[List[float]] = None,
    returns: Optional[np.ndarray] = None,
) -> pd.DataFrame:
    """
    Sweep threshold và tính business metrics.

    Args:
        y_true:     array of 0/1 labels
        y_prob:     array of predicted probabilities
        thresholds: list of thresholds to try
        returns:    array of actual trade returns (% PnL per trade)
                    nếu None sẽ dùng label thay thế

    Returns:
        DataFrame với mỗi row là 1 threshold và các metrics tương ứng
    """
    if thresholds is None:
        thresholds = np.arange(0.40, 0.72, 0.02).round(2).tolist()

    rows = []
    total = len(y_true)

    for thresh in thresholds:
        mask = y_prob >= thresh
        n_kept = int(mask.sum())

        if n_kept < 5:
            continue

        y_kept   = y_true[mask]
        winrate  = float(y_kept.mean())
        n_win    = int(y_kept.sum())
        n_loss   = n_kept - n_win

        if returns is not None:
            ret_kept = returns[mask]
            avg_ret  = float(ret_kept.mean())
            avg_win  = float(ret_kept[y_kept == 1].mean()) if n_win > 0 else 0
            avg_loss = float(ret_kept[y_kept == 0].mean()) if n_loss > 0 else 0
            gross_p  = float(ret_kept[y_kept == 1].sum()) if n_win > 0 else 0
            gross_l  = abs(float(ret_kept[y_kept == 0].sum())) if n_loss > 0 else 1e-9
            pf       = round(gross_p / gross_l, 3) if gross_l > 0 else 0
            std      = float(ret_kept.std()) if n_kept > 1 else 1e-9
            sharpe   = round(avg_ret / std, 3) if std > 0 else 0
        else:
            avg_ret  = winrate - 0.5
            avg_win  = 1.0 if n_win > 0 else 0
            avg_loss = -1.0 if n_loss > 0 else 0
            pf       = round(n_win / n_loss, 3) if n_loss > 0 else 0
            sharpe   = round(avg_ret / 0.5, 3)

        rows.append({
            "threshold":  round(thresh, 3),
            "n_trades":   n_kept,
            "pct_kept":   round(n_kept / total, 3),
            "winrate":    round(winrate, 3),
            "n_win":      n_win,
            "n_loss":     n_loss,
            "avg_return": round(avg_ret, 4),
            "avg_win":    round(avg_win, 4),
            "avg_loss":   round(avg_loss, 4),
            "profit_factor": pf,
            "sharpe":     sharpe,
        })

    df = pd.DataFrame(rows)
    return df


def pick_best_threshold(
    sweep_df: pd.DataFrame,
    primary_metric: str = "sharpe",
    min_pct_kept: float = 0.30,
) -> Tuple[float, pd.Series]:
    """
    Chọn threshold tốt nhất từ sweep results.

    Args:
        sweep_df:       output từ threshold_sweep()
        primary_metric: metric để tối ưu (sharpe / profit_factor / winrate)
        min_pct_kept:   phải giữ lại ít nhất X% trades

    Returns:
        (best_threshold, best_row)
    """
    filtered = sweep_df[sweep_df["pct_kept"] >= min_pct_kept]

    if filtered.empty:
        filtered = sweep_df

    best_row = filtered.loc[filtered[primary_metric].idxmax()]
    return float(best_row["threshold"]), best_row


# ============================================================
# CALIBRATION CURVE
# ============================================================

def compute_calibration_curve(
    y_true: np.ndarray,
    y_prob: np.ndarray,
    n_bins: int = 10,
) -> pd.DataFrame:
    """
    Tính reliability curve để kiểm tra calibration.
    """
    bins = np.linspace(0, 1, n_bins + 1)
    rows = []

    for i in range(n_bins):
        lo, hi = bins[i], bins[i + 1]
        mask   = (y_prob >= lo) & (y_prob < hi)
        n      = int(mask.sum())
        if n == 0:
            continue
        actual_rate   = float(y_true[mask].mean())
        predicted_avg = float(y_prob[mask].mean())
        rows.append({
            "bin_lo":          round(lo, 2),
            "bin_hi":          round(hi, 2),
            "n_samples":       n,
            "predicted_prob":  round(predicted_avg, 4),
            "actual_winrate":  round(actual_rate, 4),
            "calibration_gap": round(actual_rate - predicted_avg, 4),
        })

    return pd.DataFrame(rows)


def calibration_summary(cal_df: pd.DataFrame) -> Dict:
    """
    Tóm tắt chất lượng calibration.
    """
    if cal_df.empty:
        return {"status": "no_data"}

    gaps      = cal_df["calibration_gap"].abs()
    max_gap   = float(gaps.max())
    mean_gap  = float(gaps.mean())
    ece       = float((gaps * cal_df["n_samples"]).sum() / cal_df["n_samples"].sum())

    quality = "GOOD" if ece < 0.05 else ("OK" if ece < 0.10 else "POOR")

    return {
        "ece":           round(ece, 4),
        "max_gap":       round(max_gap, 4),
        "mean_gap":      round(mean_gap, 4),
        "quality":       quality,
        "n_bins_active": len(cal_df),
    }