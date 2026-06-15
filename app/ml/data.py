"""
ML Data Pipeline
================
Query closed trades từ DB, build dataset cho training.

Output:
  X: numpy array (n_samples, n_features)
  y: numpy array (n_samples,)
  meta: DataFrame với signal_id, created_at, timeframe, strategy_name
        (dùng để audit cohort và debug)
"""

import numpy as np
import pandas as pd
from typing import Optional, Tuple, Dict

from app.db.session import SessionLocal
from app.db.models import Signal, SignalFeature, TradeOutcomeAnalytics
from app.ml.features import FeatureBuilder
from app.ml.feature_registry import get_feature_names


def load_dataset(
    timeframe: Optional[str] = None,
    strategy_name: Optional[str] = None,
    min_engine_version: Optional[float] = None,
    exclude_reasons: tuple = ("SYSTEM_CRASH", "KILL_SWITCH"),
    trading_mode: Optional[str] = None,
) -> Tuple[np.ndarray, np.ndarray, pd.DataFrame]:
    """
    Load và build dataset từ closed trades.

    Returns:
        X:    (n_samples, n_features) float array
        y:    (n_samples,) int array — 0/1
        meta: DataFrame với index, signal_id, created_at, timeframe,
              strategy_name, engine_version, direction, regime,
              trade_return, label
              Dùng để audit cohort, debug, threshold analysis
    """
    rows = _query_closed_trades(
        timeframe=timeframe,
        strategy_name=strategy_name,
        min_engine_version=min_engine_version,
        exclude_reasons=exclude_reasons,
        trading_mode=trading_mode,
    )

    if not rows:
        return np.array([]), np.array([]), pd.DataFrame()

    builder = FeatureBuilder()
    X_list = []
    y_list = []
    meta_list = []

    skipped = 0
    for feat, outcome, signal in rows:
        try:
            x = builder.build_from_db(feat, outcome, signal)
            label = 1 if (outcome.trade_return is not None and float(outcome.trade_return) > 0) else 0

            X_list.append(x)
            y_list.append(label)
            meta_list.append({
                "signal_id":      signal.id,
                "created_at":     signal.created_at,
                "candle_time":    signal.candle_time,
                "timeframe":      signal.timeframe,
                "strategy_name":  signal.strategy_name,
                "engine_version": float(signal.engine_version or 0),
                "direction":      signal.direction,
                "regime":         signal.regime,
                "trade_return":   float(outcome.trade_return or 0),
                "rr_realized":    float(outcome.rr_realized or 0),
                "exit_reason":    signal.exit_reason,
                "label":          label,
            })
        except Exception as e:
            skipped += 1
            continue

    if skipped > 0:
        print(f"[DATA] Skipped {skipped} rows due to errors")

    X = np.array(X_list, dtype=np.float32)
    y = np.array(y_list, dtype=np.int32)
    meta = pd.DataFrame(meta_list)

    # Sort theo thời gian — BẮT BUỘC cho walk-forward
    if not meta.empty and "created_at" in meta.columns:
        meta = meta.sort_values("created_at").reset_index(drop=True)
        X = X[meta.index.values] if len(meta) == len(X) else X

    print(f"[DATA] Loaded: {len(y)} samples | WIN={y.sum()} | LOSS={(y==0).sum()}")

    return X, y, meta


def audit_dataset(meta: pd.DataFrame) -> Dict:
    """
    Kiểm tra chất lượng dataset trước khi train.
    Trả về dict summary.
    """
    if meta.empty:
        return {"status": "empty"}

    summary = {
        "total_trades":    len(meta),
        "win_count":       int((meta["label"] == 1).sum()),
        "loss_count":      int((meta["label"] == 0).sum()),
        "win_rate":        round(float((meta["label"] == 1).mean()), 4),
        "date_range": {
            "start": str(meta["created_at"].min()),
            "end":   str(meta["created_at"].max()),
        },
        "by_timeframe":     meta.groupby("timeframe")["label"].agg(
            count="count",
            winrate=lambda x: round(x.mean(), 3)
        ).to_dict("index"),
        "by_strategy":     meta.groupby("strategy_name")["label"].agg(
            count="count",
            winrate=lambda x: round(x.mean(), 3)
        ).to_dict("index"),
        "by_engine_version": meta.groupby("engine_version")["label"].agg(
            count="count",
            winrate=lambda x: round(x.mean(), 3)
        ).to_dict("index"),
        "by_direction":    meta.groupby("direction")["label"].agg(
            count="count",
            winrate=lambda x: round(x.mean(), 3)
        ).to_dict("index"),
        "warnings":        [],
    }

    # Warnings
    if summary["win_rate"] < 0.35:
        summary["warnings"].append(f"Label rất mất cân bằng: winrate={summary['win_rate']:.1%}")
    if summary["win_rate"] > 0.70:
        summary["warnings"].append(f"Winrate quá cao ({summary['win_rate']:.1%}), kiểm tra label logic")
    if summary["total_trades"] < 300:
        summary["warnings"].append(f"Chỉ có {summary['total_trades']} trades, model sẽ không ổn định")

    return summary


def split_dataset(
    X: np.ndarray,
    y: np.ndarray,
    meta: pd.DataFrame,
    holdout_ratio: float = 0.20,
) -> Tuple:
    """
    Chia dataset theo thời gian:
      - Development set: phần đầu (80%)
      - Holdout set:     phần cuối (20%)

    KHÔNG bao giờ random split.
    Data phải đã được sort theo created_at trước khi gọi hàm này.
    """
    n = len(y)
    split_idx = int(n * (1 - holdout_ratio))

    X_dev, X_hold = X[:split_idx], X[split_idx:]
    y_dev, y_hold = y[:split_idx], y[split_idx:]
    meta_dev      = meta.iloc[:split_idx].reset_index(drop=True)
    meta_hold     = meta.iloc[split_idx:].reset_index(drop=True)

    print(
        f"[DATA] Split: dev={len(y_dev)} ({(1-holdout_ratio):.0%}) "
        f"| holdout={len(y_hold)} ({holdout_ratio:.0%})"
    )
    print(
        f"[DATA] Dev WIN={y_dev.sum()} LOSS={(y_dev==0).sum()} "
        f"| Holdout WIN={y_hold.sum()} LOSS={(y_hold==0).sum()}"
    )

    return X_dev, X_hold, y_dev, y_hold, meta_dev, meta_hold


# ============================================================
# INTERNAL
# ============================================================

def _query_closed_trades(
    timeframe=None,
    strategy_name=None,
    min_engine_version=None,
    exclude_reasons=("SYSTEM_CRASH", "KILL_SWITCH"),
    trading_mode=None,
):
    with SessionLocal() as db:
        q = (
            db.query(SignalFeature, TradeOutcomeAnalytics, Signal)
            .join(TradeOutcomeAnalytics, SignalFeature.signal_id == TradeOutcomeAnalytics.signal_id)
            .join(Signal, SignalFeature.signal_id == Signal.id)
            .filter(Signal.status.in_(["WIN", "LOSS"]))
        )

        if timeframe:
            q = q.filter(Signal.timeframe == timeframe)

        if strategy_name:
            q = q.filter(Signal.strategy_name == strategy_name)

        if min_engine_version:
            q = q.filter(Signal.engine_version >= min_engine_version)

        if trading_mode:
            q = q.filter(Signal.trading_mode == trading_mode)

        if exclude_reasons:
            q = q.filter(Signal.exit_reason.notin_(exclude_reasons))

        q = q.filter(TradeOutcomeAnalytics.trade_return.isnot(None))

        q = q.order_by(Signal.candle_time.asc())

        return q.all()