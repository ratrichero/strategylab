"""Trade Outcome Analytics — với fix MAE/MFE cho flash close"""
import time as time_module
from datetime import datetime, timedelta
from typing import Optional, Tuple
import pandas as pd
from app.db.models import TradeOutcomeAnalytics


def save_trade_outcome(db, trade, feature):
    existing = db.query(TradeOutcomeAnalytics).filter(
        TradeOutcomeAnalytics.signal_id == trade.id).first()
    if existing: return

    entry      = float(trade.entry_price); exit_price = float(trade.exit_price)
    stop_loss  = float(trade.stop_loss);   take_profit = float(trade.take_profit)
    result_pct = float(trade.result_percent)
    created    = trade.created_at; exited = trade.exit_time
    duration_sec  = max(0, (exited - created).total_seconds())
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
            mae = round(float(drawdowns.min()), 4); mfe = round(float(runups.max()), 4)
            mae_idx = drawdowns.idxmin()
            time_to_mae = max(0, int((df.loc[mae_idx,"time"]-created).total_seconds()/60))
            mfe_idx = runups.idxmax()
            time_to_mfe = max(0, int((df.loc[mfe_idx,"time"]-created).total_seconds()/60))

    if mae is None or mfe is None:
        mae, mfe, time_to_mae, time_to_mfe = _fallback_mae_mfe(
            entry, exit_price, trade.direction, result_pct, duration_mins)

    rr_planned = rr_realized = None
    if entry != stop_loss:
        rr_planned = round(abs((take_profit-entry)/(entry-stop_loss)), 4)
    if rr_planned and rr_planned > 0:
        risk_pct = abs((stop_loss-entry)/entry*100)
        if risk_pct > 0: rr_realized = round(result_pct/risk_pct, 4)

    db.add(TradeOutcomeAnalytics(
        signal_id=trade.id, symbol=trade.symbol, timeframe=trade.timeframe,
        direction=trade.direction, regime=trade.regime,
        entry_price=entry, exit_price=exit_price,
        stop_loss=stop_loss, take_profit=take_profit,
        rr_planned=rr_planned, rr_realized=rr_realized,
        trade_return=result_pct, label=1 if trade.status=="WIN" else 0,
        max_drawdown=mae, max_favorable=mfe,
        time_to_exit=max(0,int(duration_mins)),
        time_to_mae=time_to_mae, time_to_mfe=time_to_mfe,
        volatility_at_entry=float(feature.atr_ratio) if feature.atr_ratio else None,
        volume_ratio_at_entry=float(feature.volume_ratio) if feature.volume_ratio else None,
        total_score=float(feature.total_score or 0),
        trend_score=float(feature.trend_score or 0),
        mtf_score=float(feature.mtf_score or 0),
        penalty_norm=float(feature.penalty_norm or 0),
        exit_reason=trade.exit_reason))


def _fetch_klines(symbol, start_time, end_time):
    from app.services.binance_service import get_klines
    fetch_start = start_time - timedelta(minutes=2)
    fetch_end   = end_time   + timedelta(minutes=2)
    for attempt in range(3):
        try:
            df = get_klines(symbol=symbol, interval="1m",
                            start_time=fetch_start, end_time=fetch_end, limit=1500)
            if df is not None and not df.empty: return df
            if attempt < 2: time_module.sleep(2)
        except Exception as e:
            print(f"[OUTCOME] Klines error attempt {attempt+1}: {e}")
            if attempt < 2: time_module.sleep(2)
    return pd.DataFrame()


def _fallback_mae_mfe(entry, exit_price, direction, result_pct, duration_mins):
    t = max(0, int(duration_mins))
    if result_pct > 0:
        mfe = round(result_pct, 4); mae = round(-abs(result_pct)*0.1, 4)
    else:
        mae = round(result_pct, 4); mfe = round(abs(result_pct)*0.1, 4)
    return mae, mfe, t, t
