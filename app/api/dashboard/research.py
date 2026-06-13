from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List
from app.db.async_pool import get_async_pool
from datetime import datetime
import decimal

router = APIRouter(tags=["Dashboard - Research"])

class ResearchConfig(BaseModel):
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    date_field: Optional[str] = "exit_time"
    symbols: Optional[str] = None
    symbol_mode: Optional[str] = "include"
    timeframes: Optional[List[str]] = None
    engine_version: Optional[str] = None
    direction: Optional[str] = None
    strategy: Optional[str] = None
    patterns: Optional[List[str]] = None
    regimes: Optional[List[str]] = None
    rsi_min: Optional[float] = None
    rsi_max: Optional[float] = None
    volume_ratio_min: Optional[float] = None
    atr_ratio_min: Optional[float] = None
    ema_distance_min: Optional[float] = None
    ema_distance_max: Optional[float] = None
    score_min: Optional[float] = None
    score_max: Optional[float] = None
    trend_score_min: Optional[float] = None
    momentum_score_min: Optional[float] = None
    volume_score_min: Optional[float] = None
    mtf_score_min: Optional[float] = None
    mtf_score_max: Optional[float] = None
    rr_override: Optional[float] = None
    sl_pct: Optional[float] = None
    tp_pct: Optional[float] = None
    reverse_direction: Optional[bool] = False
    initial_capital: Optional[float] = 10000
    position_size: Optional[float] = 1000

def _parse_dt(s):
    if not s: return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo:
            from datetime import timezone
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except: return None

@router.post("/api/research/run")
async def run_research(config: ResearchConfig):
    try:
        pool = await get_async_pool()
        conds = ["s.status IN ('WIN','LOSS')"]; params = []; idx = 1
        date_col = "s.exit_time" if config.date_field == "exit_time" else "s.created_at"
        if config.start_date:
            conds.append(f"{date_col} >= ${idx}"); params.append(_parse_dt(config.start_date)); idx += 1
        if config.end_date:
            conds.append(f"{date_col} < ${idx}"); params.append(_parse_dt(config.end_date)); idx += 1
        if config.timeframes:
            conds.append(f"s.timeframe = ANY(${idx})"); params.append(config.timeframes); idx += 1
        if config.direction and config.direction != "all":
            conds.append(f"s.direction = ${idx}"); params.append(config.direction); idx += 1
        if config.strategy and config.strategy != "all":
            conds.append(f"s.strategy_name = ${idx}"); params.append(config.strategy); idx += 1
        if config.patterns:
            conds.append(f"s.pattern = ANY(${idx})"); params.append(config.patterns); idx += 1
        if config.regimes:
            regimes = []
            for r in config.regimes:
                if r == "SIDEWAYS": regimes.extend(["SIDEWAYS","RANGING"])
                else: regimes.append(r)
            conds.append(f"s.regime = ANY(${idx})"); params.append(regimes); idx += 1
        if config.engine_version and config.engine_version != "all":
            if config.engine_version.endswith("+"):
                conds.append(f"s.engine_version >= ${idx}::numeric"); params.append(float(config.engine_version[:-1])); idx += 1
            else:
                conds.append(f"s.engine_version::text = ${idx}"); params.append(config.engine_version); idx += 1
        if config.score_min is not None:
            conds.append(f"s.score >= ${idx}"); params.append(config.score_min); idx += 1
        if config.score_max is not None:
            conds.append(f"s.score <= ${idx}"); params.append(config.score_max); idx += 1
        where = " AND ".join(conds)
        async with pool.acquire() as conn:
            rows = await conn.fetch(f"SELECT s.*, sf.rsi AS sf_rsi, sf.volume_ratio AS sf_vol, sf.atr_ratio AS sf_atr, sf.ema_distance AS sf_ema, sf.trend_score AS sf_trend, sf.momentum_score AS sf_mom, sf.volume_score AS sf_vol_s, sf.mtf_score AS sf_mtf, toa.max_drawdown AS toa_mae, toa.max_favorable AS toa_mfe, toa.rr_planned, toa.rr_realized FROM signals s LEFT JOIN signal_features sf ON sf.signal_id = s.id LEFT JOIN trade_outcome_analytics toa ON toa.signal_id = s.id WHERE {where} ORDER BY s.exit_time ASC", *params)
        trades = []
        for r in rows:
            d = dict(r)
            if config.symbols:
                sym_list = [x.strip().upper() + ("" if x.strip().upper().endswith("USDT") else "USDT") for x in config.symbols.replace(",", " ").split() if x.strip()]
                if sym_list:
                    match = d["symbol"] in sym_list
                    if config.symbol_mode == "include" and not match: continue
                    if config.symbol_mode == "exclude" and match: continue
            rsi = float(d.get("sf_rsi") or d.get("rsi") or 0)
            if config.rsi_min is not None and rsi < config.rsi_min: continue
            if config.rsi_max is not None and rsi > config.rsi_max: continue
            vr = float(d.get("sf_vol") or d.get("volume_ratio") or 0)
            if config.volume_ratio_min is not None and vr < config.volume_ratio_min: continue
            ar = float(d.get("sf_atr") or d.get("atr_ratio") or 0)
            if config.atr_ratio_min is not None and ar < config.atr_ratio_min: continue
            ed = float(d.get("sf_ema") or 0)
            if config.ema_distance_min is not None and ed < config.ema_distance_min: continue
            if config.ema_distance_max is not None and ed > config.ema_distance_max: continue
            ts = float(d.get("sf_trend") or 0)
            if config.trend_score_min is not None and ts < config.trend_score_min: continue
            ms = float(d.get("sf_mom") or 0)
            if config.momentum_score_min is not None and ms < config.momentum_score_min: continue
            vs = float(d.get("sf_vol_s") or 0)
            if config.volume_score_min is not None and vs < config.volume_score_min: continue
            mt = float(d.get("sf_mtf") or 0)
            if config.mtf_score_min is not None and mt < config.mtf_score_min: continue
            if config.mtf_score_max is not None and mt > config.mtf_score_max: continue
            entry = float(d.get("entry_price") or 0)
            result = float(d.get("result_percent") or 0)
            mae = float(d.get("toa_mae") or 0)
            mfe = float(d.get("toa_mfe") or 0)
            direction = d.get("direction", "")
            exit_reason = (d.get("exit_reason") or "").lower()
            sim_result = result; sim_status = d.get("status", ""); sim_counted = True
            sl_used = tp_used = None
            if config.reverse_direction:
                direction = "SHORT" if direction == "LONG" else "LONG"
                d["direction"] = direction; result = -result
            has_sl_tp = config.sl_pct is not None and config.tp_pct is not None
            has_rr = config.rr_override is not None
            if entry > 0 and (has_sl_tp or has_rr):
                if has_sl_tp: sl_pct = abs(config.sl_pct); tp_pct = abs(config.tp_pct)
                else:
                    orig_sl = float(d.get("stop_loss") or 0)
                    sl_pct = abs(orig_sl - entry) / entry * 100 if orig_sl and entry else 2.0
                    tp_pct = sl_pct * config.rr_override
                sl_used = sl_pct; tp_used = tp_pct
                hit_sl = mae >= sl_pct; hit_tp = mfe >= tp_pct
                if hit_sl and hit_tp:
                    if exit_reason == "sl": sim_result = -sl_pct; sim_status = "LOSS"
                    elif exit_reason == "tp": sim_result = tp_pct; sim_status = "WIN"
                    else: sim_result = None; sim_status = "NOT_COUNT"; sim_counted = False
                elif hit_sl: sim_result = -sl_pct; sim_status = "LOSS"
                elif hit_tp: sim_result = tp_pct; sim_status = "WIN"
                else: sim_result = result; sim_status = d.get("status", "")
            clean = {}
            for k, v in d.items():
                if isinstance(v, decimal.Decimal): clean[k] = float(v)
                elif isinstance(v, datetime): clean[k] = v.isoformat()
                else: clean[k] = v
            clean.update({"sim_result": sim_result, "sim_status": sim_status, "sim_counted": sim_counted,
                "_debug_mae": mae, "_debug_mfe": mfe, "_debug_sl_pct": sl_used, "_debug_tp_pct": tp_used,
                "_debug_exit_reason": exit_reason, "rsi_val": rsi, "volume_ratio_val": vr})
            trades.append(clean)
        return {"trades": trades, "total": len(trades)}
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
