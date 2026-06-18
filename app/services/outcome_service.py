"""Trade Outcome Analytics — với fix MAE/MFE cho flash close"""

from datetime import timedelta
from typing import Optional, Tuple
import pandas as pd

from app.db.models import TradeOutcomeAnalytics
from app.core.time_utils import ensure_utc


def _safe_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def save_trade_outcome(db, trade, feature):
    existing = db.query(TradeOutcomeAnalytics).filter(
        TradeOutcomeAnalytics.signal_id == trade.id
    ).first()
    if existing:
        return

    entry = _safe_float(trade.entry_price)
    exit_price = _safe_float(trade.exit_price)
    stop_loss = _safe_float(trade.stop_loss)
    take_profit = _safe_float(trade.take_profit)
    result_pct = _safe_float(trade.result_percent)

    created = ensure_utc(trade.created_at) if trade.created_at else None
    exited = ensure_utc(trade.exit_time) if trade.exit_time else None

    # HOTFIX:
    # analytics là side-effect, không được crash nếu thiếu field
    if entry is None or exit_price is None or created is None or exited is None:
        print(
            f"[OUTCOME] Skip signal_id={trade.id} "
            f"| entry={entry} exit={exit_price} created={created} exited={exited}"
        )
        return

    if result_pct is None:
        if trade.direction == "LONG":
            result_pct = ((exit_price - entry) / entry * 100) if entry else 0.0
        else:
            result_pct = ((entry - exit_price) / entry * 100) if entry else 0.0

    duration_sec = max(0, (exited - created).total_seconds())
    duration_mins = duration_sec / 60

    mae = mfe = time_to_mae = time_to_mfe = None
    df = _fetch_klines(trade.symbol, created, exited)

    if df is not None and not df.empty:
        df = df[df["time"] <= exited]
        if not df.empty:
            if trade.direction == "LONG":
                drawdowns = (df["low"]  - entry) / entry * 100
                runups    = (df["high"] - entry) / entry * 100
            else:
                drawdowns = (entry - df["high"]) / entry * 100
                runups    = (entry - df["low"])  / entry * 100

            mae = round(float(drawdowns.min()), 4)
            mfe = round(float(runups.max()), 4)

            mae_idx = drawdowns.idxmin()
            time_to_mae = max(0, int((df.loc[mae_idx, "time"] - created).total_seconds() / 60))

            mfe_idx = runups.idxmax()
            time_to_mfe = max(0, int((df.loc[mfe_idx, "time"] - created).total_seconds() / 60))

    if mae is None or mfe is None:
        mae, mfe, time_to_mae, time_to_mfe = _fallback_mae_mfe(
            entry, exit_price, trade.direction, result_pct, duration_mins
        )

    rr_planned = None
    rr_realized = None

    if stop_loss is not None and take_profit is not None and entry != stop_loss:
        rr_planned = round(abs((take_profit - entry) / (entry - stop_loss)), 4)

    if rr_planned and rr_planned > 0 and stop_loss is not None:
        risk_pct = abs((stop_loss - entry) / entry * 100) if entry else 0
        if risk_pct > 0:
            rr_realized = round(result_pct / risk_pct, 4)

    db.add(TradeOutcomeAnalytics(
        signal_id=trade.id,
        symbol=trade.symbol,
        timeframe=trade.timeframe,
        direction=trade.direction,
        regime=trade.regime,

        entry_price=entry,
        exit_price=exit_price,
        stop_loss=stop_loss,
        take_profit=take_profit,

        rr_planned=rr_planned,
        rr_realized=rr_realized,
        trade_return=result_pct,

        label=1 if trade.status == "WIN" else 0,
        max_drawdown=mae,
        max_favorable=mfe,

        time_to_exit=max(0, int(duration_mins)),
        time_to_mae=time_to_mae,
        time_to_mfe=time_to_mfe,

        volatility_at_entry=float(feature.atr_ratio) if feature.atr_ratio else None,
        volume_ratio_at_entry=float(feature.volume_ratio) if feature.volume_ratio else None,
        total_score=float(feature.total_score or 0),
        trend_score=float(feature.trend_score or 0),
        mtf_score=float(feature.mtf_score or 0),
        penalty_norm=float(feature.penalty_norm or 0),

        exit_reason=trade.exit_reason
    ))


def _fetch_klines(symbol, start_time, end_time):
    from app.services.binance_service import get_klines
    import time as time_module

    start_time = ensure_utc(start_time)
    end_time   = ensure_utc(end_time)

    fetch_start = start_time - timedelta(minutes=2)
    fetch_end   = end_time   + timedelta(minutes=2)

    for attempt in range(3):
        try:
            df = get_klines(
                symbol=symbol,
                interval="1m",
                start_time=fetch_start,
                end_time=fetch_end,
                limit=1500
            )
            if df is not None and not df.empty:
                return df
            if attempt < 2:
                time_module.sleep(2)
        except Exception as e:
            print(f"[OUTCOME] Klines error attempt {attempt+1}: {e}")
            if attempt < 2:
                time_module.sleep(2)

    return pd.DataFrame()


def _fallback_mae_mfe(entry, exit_price, direction, result_pct, duration_mins):
    t = max(0, int(duration_mins))
    if result_pct > 0:
        mfe = round(result_pct, 4)
        mae = round(-abs(result_pct) * 0.1, 4)
    else:
        mae = round(result_pct, 4)
        mfe = round(abs(result_pct) * 0.1, 4)
    return mae, mfe, t, t