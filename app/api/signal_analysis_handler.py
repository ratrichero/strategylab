# app/api/signal_analysis_handler.py
# COMPLETE FILE — replace entirely

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime, timedelta
from app.db.async_pool import get_async_pool
import decimal

router = APIRouter()


def _parse_dt(s):
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo:
            from datetime import timezone
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except:
        return None


def _parse_vn(start_s, end_s):
    dt_start = None
    dt_end = None
    if start_s:
        if "T" in start_s:
            dt_start = _parse_dt(start_s)
        else:
            dt_start = _parse_dt(start_s + "T00:00:00+07:00")
    if end_s:
        if "T" in end_s:
            dt_end = _parse_dt(end_s)
        else:
            base = _parse_dt(end_s + "T00:00:00+07:00")
            dt_end = base + timedelta(days=1) if base else None
    return dt_start, dt_end


def _safe(obj):
    if isinstance(obj, dict):
        return {k: _safe(v) for k, v in obj.items()}
    if isinstance(obj, decimal.Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj


@router.post("/api/signal-analysis")
async def signal_analysis(body: Dict[str, Any]):
    pool = await get_async_pool()
    query_name = body.get("query", "")
    params = body.get("params", {})

    dt_start, dt_end = _parse_vn(
        params.get("start_date"),
        params.get("end_date")
    )

    # sig_f: inline date filter for signals (no $1/$2)
    def sf(alias="s", col="exit_time"):
        parts = []
        if dt_start:
            parts.append(f"{alias}.{col} >= '{dt_start.isoformat()}'::timestamp")
        if dt_end:
            parts.append(f"{alias}.{col} < '{dt_end.isoformat()}'::timestamp")
        return (" AND " + " AND ".join(parts)) if parts else ""

    sig_f = sf("s", "exit_time")

    # sd_f: parameterized for scan_debug ($1, $2)
    sd_params = []
    sd_f = ""
    pidx = 1
    if dt_start:
        sd_f += f" AND sd.created_at >= ${pidx}"
        sd_params.append(dt_start)
        pidx += 1
    if dt_end:
        sd_f += f" AND sd.created_at < ${pidx}"
        sd_params.append(dt_end)
        pidx += 1

    try:
        async with pool.acquire() as conn:
            rows = await _dispatch(conn, query_name, params, sig_f, sd_f, sd_params)

        if rows and len(rows) > 0 and hasattr(rows[0], "keys"):
            result = [_safe(dict(r)) for r in rows]
        else:
            result = [_safe(r) if isinstance(r, dict) else r for r in rows]

        return {"data": result}

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


async def _dispatch(conn, name, params, sig_f, sd_f, sd_params):

    if name == "funnel":
        s = [
            await conn.fetchval(f"SELECT COUNT(*) FROM scan_debug sd WHERE 1=1 {sd_f}", *sd_params),
            await conn.fetchval(f"SELECT COUNT(*) FROM scan_debug sd WHERE passed_score=true {sd_f}", *sd_params),
            await conn.fetchval(f"SELECT COUNT(*) FROM scan_debug sd WHERE block_reason IS NOT NULL {sd_f}", *sd_params),
            await conn.fetchval(f"SELECT COUNT(*) FROM scan_debug sd WHERE signal_id IS NOT NULL {sd_f}", *sd_params),
            await conn.fetchval(f"SELECT COUNT(*) FROM scan_debug sd JOIN trade_outcome_analytics toa ON toa.signal_id=sd.signal_id WHERE toa.label=1 {sd_f}", *sd_params),
        ]
        return [
            {"stage": "Total Scanned", "count": s[0] or 0},
            {"stage": "Passed Score", "count": s[1] or 0},
            {"stage": "Blocked", "count": s[2] or 0},
            {"stage": "Total Traded", "count": s[3] or 0},
            {"stage": "Won", "count": s[4] or 0},
        ]

    elif name == "block_reasons":
        return await conn.fetch(f"SELECT CASE WHEN block_reason LIKE 'HTF%%' THEN 'HTF (grouped)' WHEN block_reason LIKE 'OTF%%' THEN 'OTF (grouped)' ELSE COALESCE(block_reason,'Passed') END AS reason, COUNT(*) AS n, ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER(),1) AS pct, ROUND(AVG(total_score)::numeric,3) AS avg_score FROM scan_debug sd WHERE 1=1 {sd_f} GROUP BY reason ORDER BY n DESC", *sd_params)

    elif name == "score_histogram":
        return await conn.fetch(f"WITH b AS (SELECT CONCAT(FLOOR(s.score)::int,'-',(FLOOR(s.score)+1)::int) AS score_bucket, FLOOR(s.score) AS sort_key, s.status, s.result_percent FROM signals s WHERE s.status IN ('WIN','LOSS') {sig_f}) SELECT score_bucket, COUNT(*) total, COUNT(*) FILTER (WHERE status='WIN') wins, COUNT(*) FILTER (WHERE status='LOSS') losses, ROUND(100.0*COUNT(*) FILTER (WHERE status='WIN')/NULLIF(COUNT(*),0),1) win_rate, ROUND(AVG(result_percent)::numeric,4) avg_return FROM b GROUP BY score_bucket,sort_key ORDER BY sort_key")

    elif name == "score_scatter":
        return await conn.fetch(f"SELECT s.score AS total_score, toa.rr_realized, toa.trade_return, toa.label, s.symbol, s.timeframe, s.direction, s.regime FROM signals s JOIN trade_outcome_analytics toa ON toa.signal_id=s.id WHERE s.status IN ('WIN','LOSS') AND toa.label IS NOT NULL {sig_f} LIMIT 500")

    elif name == "score_calibration":
        return await conn.fetch(f"WITH d AS (SELECT NTILE(10) OVER (ORDER BY s.score) AS decile, s.score, CASE WHEN s.status='WIN' THEN 1 ELSE 0 END AS label FROM signals s WHERE s.status IN ('WIN','LOSS') {sig_f}) SELECT decile, ROUND(MIN(score)::numeric,3) score_min, ROUND(MAX(score)::numeric,3) score_max, ROUND(AVG(score)::numeric,3) score_mean, COUNT(*) n, ROUND(100.0*AVG(label::numeric),1) actual_win_rate FROM d GROUP BY decile ORDER BY decile")

    elif name == "score_regime_heatmap":
        return await conn.fetch(f"SELECT CASE WHEN s.score<6 THEN '<6' WHEN s.score<7 THEN '6-7' WHEN s.score<8 THEN '7-8' WHEN s.score<9 THEN '8-9' ELSE '9+' END AS score_band, COALESCE(s.regime,'unknown') AS regime, COUNT(*) n_trades, ROUND(100.0*SUM(CASE WHEN s.status='WIN' THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate, ROUND(AVG(s.result_percent)::numeric,2) avg_return FROM signals s WHERE s.status IN ('WIN','LOSS') {sig_f} GROUP BY score_band,regime ORDER BY score_band,regime")

    elif name == "component_heatmap":
        return await conn.fetch(f"WITH cb AS (SELECT toa.label, toa.rr_realized, ROUND((sf.trend_score/0.2)::numeric)*0.2 AS trend_b, ROUND((sf.momentum_score/0.2)::numeric)*0.2 AS mom_b, ROUND((sf.volume_score/0.2)::numeric)*0.2 AS vol_b, ROUND((sf.pattern_score/0.2)::numeric)*0.2 AS pat_b, ROUND((sf.mtf_score/0.2)::numeric)*0.2 AS mtf_b FROM signal_features sf JOIN trade_outcome_analytics toa ON toa.signal_id=sf.signal_id JOIN signals s ON s.id=sf.signal_id WHERE toa.label IS NOT NULL {sig_f}), lf AS (SELECT 'trend' AS component, trend_b AS bucket, label, rr_realized FROM cb UNION ALL SELECT 'momentum',mom_b,label,rr_realized FROM cb UNION ALL SELECT 'volume',vol_b,label,rr_realized FROM cb UNION ALL SELECT 'pattern',pat_b,label,rr_realized FROM cb UNION ALL SELECT 'mtf',mtf_b,label,rr_realized FROM cb) SELECT component, bucket, COUNT(*) n, ROUND(100.0*AVG(label::numeric),1) win_rate, ROUND(AVG(rr_realized)::numeric,2) avg_rr FROM lf GROUP BY component,bucket HAVING COUNT(*)>=5 ORDER BY component,bucket")

    elif name == "feature_importance_full":
        return await conn.fetch(f"WITH f AS (SELECT toa.label::numeric AS outcome, sf.trend_score*0.25 AS t_c, sf.momentum_score*0.20 AS m_c, sf.volume_score*0.20 AS v_c, sf.pattern_score*0.20 AS p_c, sf.mtf_score*0.15 AS mt_c, sf.penalty_norm AS pen_c, sf.trend_score,sf.momentum_score,sf.volume_score,sf.pattern_score,sf.mtf_score,sf.penalty_norm FROM signal_features sf JOIN trade_outcome_analytics toa ON toa.signal_id=sf.signal_id JOIN signals s ON s.id=sf.signal_id WHERE toa.label IS NOT NULL {sig_f}) SELECT 'trend' AS feature, ROUND(AVG(t_c)::numeric,4) avg_contrib, ROUND(CORR(t_c,outcome)::numeric,4) corr_weighted, ROUND(CORR(trend_score,outcome)::numeric,4) corr_raw, COUNT(*) n FROM f UNION ALL SELECT 'momentum',ROUND(AVG(m_c)::numeric,4),ROUND(CORR(m_c,outcome)::numeric,4),ROUND(CORR(momentum_score,outcome)::numeric,4),COUNT(*) FROM f UNION ALL SELECT 'volume',ROUND(AVG(v_c)::numeric,4),ROUND(CORR(v_c,outcome)::numeric,4),ROUND(CORR(volume_score,outcome)::numeric,4),COUNT(*) FROM f UNION ALL SELECT 'pattern',ROUND(AVG(p_c)::numeric,4),ROUND(CORR(p_c,outcome)::numeric,4),ROUND(CORR(pattern_score,outcome)::numeric,4),COUNT(*) FROM f UNION ALL SELECT 'mtf',ROUND(AVG(mt_c)::numeric,4),ROUND(CORR(mt_c,outcome)::numeric,4),ROUND(CORR(mtf_score,outcome)::numeric,4),COUNT(*) FROM f UNION ALL SELECT 'penalty',ROUND(AVG(pen_c)::numeric,4),ROUND(CORR(pen_c,outcome)::numeric,4),ROUND(CORR(penalty_norm,outcome)::numeric,4),COUNT(*) FROM f")

    elif name == "feature_correlation":
        return await conn.fetch(f"SELECT sf.trend_score,sf.momentum_score,sf.volume_score,sf.pattern_score,sf.mtf_score,sf.penalty_norm,sf.total_score,toa.rr_realized,toa.trade_return,COALESCE(toa.label,0) AS outcome FROM signal_features sf JOIN trade_outcome_analytics toa ON toa.signal_id=sf.signal_id JOIN signals s ON s.id=sf.signal_id WHERE toa.label IS NOT NULL {sig_f} LIMIT 1000")

    elif name == "mae_mfe_scatter":
        return await conn.fetch(f"SELECT toa.max_drawdown AS mae, toa.max_favorable AS mfe, toa.label, toa.time_to_mae, toa.time_to_mfe, toa.time_to_exit, toa.exit_reason, s.symbol, s.direction FROM trade_outcome_analytics toa JOIN signals s ON s.id=toa.signal_id WHERE toa.label IS NOT NULL {sig_f} LIMIT 500")

    elif name == "exit_reason_breakdown":
        return await conn.fetch(f"SELECT toa.exit_reason, COUNT(*) count, ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER(),1) pct FROM trade_outcome_analytics toa JOIN signals s ON s.id=toa.signal_id WHERE toa.exit_reason IS NOT NULL {sig_f} GROUP BY toa.exit_reason ORDER BY count DESC")

    elif name == "time_to_exit_dist":
        return await conn.fetch(f"SELECT CASE WHEN toa.time_to_exit<60 THEN '<1h' WHEN toa.time_to_exit<240 THEN '1-4h' WHEN toa.time_to_exit<720 THEN '4-12h' WHEN toa.time_to_exit<1440 THEN '12-24h' ELSE '>24h' END AS bucket, COUNT(*) count, ROUND(100.0*SUM(CASE WHEN toa.label=1 THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate FROM trade_outcome_analytics toa JOIN signals s ON s.id=toa.signal_id WHERE toa.time_to_exit IS NOT NULL {sig_f} GROUP BY bucket ORDER BY MIN(toa.time_to_exit)")

    elif name == "score_threshold_optimizer":
        return await conn.fetch(f"WITH t AS (SELECT generate_series(6,10,1)::numeric AS threshold), p AS (SELECT t.threshold, COUNT(*) FILTER (WHERE s.status IN ('WIN','LOSS') AND s.score>=t.threshold) n_trades, ROUND(100.0*COUNT(*) FILTER (WHERE s.status='WIN' AND s.score>=t.threshold)/NULLIF(COUNT(*) FILTER (WHERE s.status IN ('WIN','LOSS') AND s.score>=t.threshold),0),1) win_rate, ROUND(AVG(s.result_percent) FILTER (WHERE s.status IN ('WIN','LOSS') AND s.score>=t.threshold)::numeric,2) avg_return FROM t CROSS JOIN signals s WHERE s.status IN ('WIN','LOSS') {sig_f} GROUP BY t.threshold) SELECT threshold,n_trades,win_rate,avg_return FROM p WHERE n_trades>0 ORDER BY threshold")

    elif name == "score_component_radar":
        return await conn.fetch(f"SELECT CASE WHEN sf.total_score<5 THEN 'Low (<5)' WHEN sf.total_score<6.5 THEN 'Mid (5-6.5)' WHEN sf.total_score<8 THEN 'Good (6.5-8)' ELSE 'Excellent (8+)' END AS score_band, ROUND(AVG(sf.trend_score)::numeric,3) avg_trend, ROUND(AVG(sf.momentum_score)::numeric,3) avg_momentum, ROUND(AVG(sf.volume_score)::numeric,3) avg_volume, ROUND(AVG(sf.pattern_score)::numeric,3) avg_pattern, ROUND(AVG(sf.mtf_score)::numeric,3) avg_mtf, ROUND(AVG(sf.penalty_norm)::numeric,3) avg_penalty, ROUND(100.0*COUNT(*) FILTER (WHERE toa.label=1)/NULLIF(COUNT(*) FILTER (WHERE toa.label IS NOT NULL),0),1) win_rate, COUNT(*) n FROM signal_features sf LEFT JOIN trade_outcome_analytics toa ON toa.signal_id=sf.signal_id JOIN signals s ON s.id=sf.signal_id WHERE sf.signal_id IS NOT NULL {sig_f} GROUP BY score_band ORDER BY MIN(sf.total_score)")

    elif name == "score_quality_trend":
        return await conn.fetch(f"SELECT DATE_TRUNC('day',s.created_at) AS day, ROUND(AVG(s.score)::numeric,3) avg_score, COUNT(*) n_signals, ROUND(100.0*SUM(CASE WHEN s.status='WIN' THEN 1 ELSE 0 END)/NULLIF(SUM(CASE WHEN s.status IN ('WIN','LOSS') THEN 1 ELSE 0 END),0),1) win_rate FROM signals s WHERE s.status IN ('WIN','LOSS') {sig_f} GROUP BY DATE_TRUNC('day',s.created_at) ORDER BY day")

    elif name == "rsi_vol_heatmap":
        return await conn.fetch(f"WITH ind AS (SELECT toa.label, toa.trade_return, (sd.indicators_snapshot->>'rsi')::numeric AS rsi, (sd.indicators_snapshot->>'volume_ratio')::numeric AS vol_ratio FROM scan_debug sd JOIN trade_outcome_analytics toa ON toa.signal_id=sd.signal_id JOIN signals s ON s.id=sd.signal_id WHERE sd.signal_id IS NOT NULL AND sd.indicators_snapshot IS NOT NULL AND toa.label IS NOT NULL {sig_f}), b AS (SELECT label, trade_return, CASE WHEN rsi<30 THEN '<30' WHEN rsi<45 THEN '30-45' WHEN rsi<55 THEN '45-55' WHEN rsi<70 THEN '55-70' ELSE '70+' END AS rsi_zone, CASE WHEN vol_ratio<0.8 THEN '<0.8x' WHEN vol_ratio<1.5 THEN '0.8-1.5x' WHEN vol_ratio<3 THEN '1.5-3x' WHEN vol_ratio<6 THEN '3-6x' ELSE '>6x' END AS vol_zone FROM ind) SELECT rsi_zone,vol_zone,COUNT(*) n_trades, ROUND(100.0*SUM(CASE WHEN label=1 THEN 1 ELSE 0 END)/COUNT(*),1) win_rate, ROUND(AVG(trade_return)::numeric,4) avg_return FROM b GROUP BY rsi_zone,vol_zone ORDER BY rsi_zone,vol_zone")

    elif name == "tf_symbol_heatmap":
        return await conn.fetch(f"SELECT s.timeframe,s.symbol,COUNT(*) n_trades, ROUND(100.0*SUM(CASE WHEN s.status='WIN' THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate, ROUND(AVG(s.result_percent)::numeric,2) avg_rr FROM signals s WHERE s.status IN ('WIN','LOSS') {sig_f} GROUP BY s.timeframe,s.symbol HAVING COUNT(*)>=2 ORDER BY win_rate DESC")

    elif name == "atr_score_heatmap":
        return await conn.fetch(f"SELECT CASE WHEN (sd.indicators_snapshot->>'atr_percentile')::numeric<0.25 THEN '<25%' WHEN (sd.indicators_snapshot->>'atr_percentile')::numeric<0.5 THEN '25-50%' WHEN (sd.indicators_snapshot->>'atr_percentile')::numeric<0.75 THEN '50-75%' ELSE '75%+' END AS atr_bucket, CASE WHEN s.score<6 THEN '<6' WHEN s.score<7 THEN '6-7' WHEN s.score<8 THEN '7-8' WHEN s.score<9 THEN '8-9' ELSE '9+' END AS score_band, COUNT(*) n_trades, ROUND(100.0*SUM(CASE WHEN toa.label=1 THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate FROM scan_debug sd JOIN signals s ON s.id=sd.signal_id LEFT JOIN trade_outcome_analytics toa ON toa.signal_id=s.id WHERE sd.signal_id IS NOT NULL AND sd.indicators_snapshot IS NOT NULL AND toa.label IS NOT NULL {sig_f} GROUP BY atr_bucket,score_band HAVING COUNT(*)>=3 ORDER BY atr_bucket,score_band")

    elif name == "mtf_trend_heatmap":
        return await conn.fetch(f"SELECT CASE WHEN sf.mtf_score<0.3 THEN '<0.3' WHEN sf.mtf_score<0.6 THEN '0.3-0.6' ELSE '0.6+' END AS mtf_bucket, CASE WHEN sf.trend_score<0.3 THEN '<0.3' WHEN sf.trend_score<0.6 THEN '0.3-0.6' ELSE '0.6+' END AS trend_bucket, COUNT(*) n_trades, ROUND(100.0*SUM(CASE WHEN toa.label=1 THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate FROM signal_features sf JOIN trade_outcome_analytics toa ON toa.signal_id=sf.signal_id JOIN signals s ON s.id=sf.signal_id WHERE toa.label IS NOT NULL {sig_f} GROUP BY mtf_bucket,trend_bucket HAVING COUNT(*)>=3 ORDER BY mtf_bucket,trend_bucket")

    elif name == "indicator_bucket":
        ind = params.get("indicator", "rsi")
        fm = {
            "rsi": "sd.indicators_snapshot->>'rsi'",
            "volume_ratio": "sd.indicators_snapshot->>'volume_ratio'",
            "atr_percentile": "sd.indicators_snapshot->>'atr_percentile'",
        }
        field = fm.get(ind, fm["rsi"])
        if ind == "rsi":
            bsql = f"CASE WHEN ({field})::numeric<30 THEN '<30' WHEN ({field})::numeric<50 THEN '30-50' WHEN ({field})::numeric<70 THEN '50-70' ELSE '70+' END"
        elif ind == "volume_ratio":
            bsql = f"CASE WHEN ({field})::numeric<1 THEN '<1' WHEN ({field})::numeric<2 THEN '1-2' WHEN ({field})::numeric<5 THEN '2-5' ELSE '5+' END"
        else:
            bsql = f"CASE WHEN ({field})::numeric<0.25 THEN '<25%' WHEN ({field})::numeric<0.5 THEN '25-50%' WHEN ({field})::numeric<0.75 THEN '50-75%' ELSE '75%+' END"
        return await conn.fetch(f"SELECT {bsql} AS bucket, COUNT(*) trades, ROUND(100.0*SUM(CASE WHEN toa.label=1 THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate, ROUND(AVG(toa.trade_return)::numeric,4) avg_return FROM scan_debug sd JOIN trade_outcome_analytics toa ON toa.signal_id=sd.signal_id JOIN signals s ON s.id=sd.signal_id WHERE sd.signal_id IS NOT NULL AND sd.indicators_snapshot IS NOT NULL AND ({field}) IS NOT NULL AND toa.label IS NOT NULL {sig_f} GROUP BY bucket ORDER BY MIN(({field})::numeric)")

    # ── EDGE QUERIES ──────────────────────────────────────

    elif name == "edge_baseline":
        return await conn.fetch(f"SELECT s.direction,s.timeframe,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r, ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY t.rr_realized)::numeric,3) median_r, ROUND(AVG(CASE WHEN t.rr_realized>0 THEN 1.0 ELSE 0.0 END)*100,1) winrate, ROUND(AVG(CASE WHEN t.rr_realized>0 THEN t.rr_realized END)::numeric,3) avg_win_r, ROUND(AVG(CASE WHEN t.rr_realized<=0 THEN t.rr_realized END)::numeric,3) avg_loss_r, ROUND((AVG(CASE WHEN t.rr_realized>0 THEN 1.0 ELSE 0.0 END)*COALESCE(AVG(CASE WHEN t.rr_realized>0 THEN t.rr_realized END),0)+(1-AVG(CASE WHEN t.rr_realized>0 THEN 1.0 ELSE 0.0 END))*COALESCE(AVG(CASE WHEN t.rr_realized<=0 THEN t.rr_realized END),0))::numeric,4) expectancy FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE t.label IS NOT NULL {sig_f} GROUP BY s.direction,s.timeframe ORDER BY s.direction,s.timeframe")

    elif name == "edge_strategy":
        return await conn.fetch(f"SELECT s.strategy_name,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r, ROUND(AVG(CASE WHEN t.rr_realized>0 THEN 1 ELSE 0 END)*100,2) winrate FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE t.label IS NOT NULL {sig_f} GROUP BY s.strategy_name ORDER BY avg_r DESC")

    elif name == "edge_pattern":
        return await conn.fetch(f"SELECT s.pattern,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r, ROUND(AVG(CASE WHEN t.rr_realized>0 THEN 1 ELSE 0 END)*100,2) winrate FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE t.label IS NOT NULL {sig_f} GROUP BY s.pattern HAVING COUNT(*)>3 ORDER BY avg_r DESC")

    elif name == "edge_timeframe":
        return await conn.fetch(f"SELECT s.timeframe,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r, ROUND(AVG(CASE WHEN t.rr_realized>0 THEN 1 ELSE 0 END)*100,2) winrate FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE t.label IS NOT NULL {sig_f} GROUP BY s.timeframe ORDER BY avg_r DESC")

    elif name == "edge_direction":
        return await conn.fetch(f"SELECT s.direction,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r, ROUND(AVG(CASE WHEN t.rr_realized>0 THEN 1 ELSE 0 END)*100,2) winrate FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE t.label IS NOT NULL {sig_f} GROUP BY s.direction")

    elif name == "edge_regime":
        return await conn.fetch(f"SELECT s.regime,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r, ROUND(AVG(CASE WHEN t.rr_realized>0 THEN 1 ELSE 0 END)*100,2) winrate FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE t.label IS NOT NULL {sig_f} GROUP BY s.regime ORDER BY avg_r DESC")

    elif name == "edge_score":
        return await conn.fetch(f"SELECT FLOOR(t.total_score)::int AS score_bucket,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r, ROUND(AVG(CASE WHEN t.rr_realized>0 THEN 1 ELSE 0 END)*100,2) winrate FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE t.total_score IS NOT NULL {sig_f} GROUP BY score_bucket ORDER BY score_bucket")

    elif name == "edge_mtf":
        return await conn.fetch(f"SELECT CONCAT(ROUND(FLOOR(sf.mtf_score*10)/10,1)::text,'-',ROUND((FLOOR(sf.mtf_score*10)+1)/10,1)::text) AS mtf_bucket, COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r FROM signal_features sf JOIN trade_outcome_analytics t ON sf.signal_id=t.signal_id JOIN signals s ON s.id=sf.signal_id WHERE 1=1 {sig_f} GROUP BY FLOOR(sf.mtf_score*10) ORDER BY FLOOR(sf.mtf_score*10)")

    elif name == "edge_mtf_analysis":
        return await conn.fetch(f"WITH m AS (SELECT CASE WHEN sf.mtf_score<0.2 THEN '1.(0.0-0.2)' WHEN sf.mtf_score<0.4 THEN '2.(0.2-0.4)' WHEN sf.mtf_score<0.6 THEN '3.(0.4-0.6)' WHEN sf.mtf_score<0.8 THEN '4.(0.6-0.8)' ELSE '5.(0.8-1.0)' END AS mtf_bucket, t.rr_realized, t.label FROM signal_features sf JOIN trade_outcome_analytics t ON t.signal_id=sf.signal_id JOIN signals s ON s.id=sf.signal_id WHERE t.label IS NOT NULL {sig_f}), b AS (SELECT AVG(rr_realized) base_r FROM trade_outcome_analytics WHERE label IS NOT NULL) SELECT m.mtf_bucket,COUNT(*) n, ROUND(AVG(m.label::numeric)*100,1) winrate, ROUND(AVG(m.rr_realized)::numeric,3) avg_r, ROUND((AVG(m.rr_realized)-b.base_r)::numeric,3) vs_baseline FROM m,b GROUP BY m.mtf_bucket,b.base_r ORDER BY m.mtf_bucket")

    elif name == "edge_mtf_direction":
        return await conn.fetch(f"SELECT CASE WHEN sf.mtf_score<0.3 THEN 'Low (<0.3)' WHEN sf.mtf_score<0.6 THEN 'Mid (0.3-0.6)' ELSE 'High (>0.6)' END AS mtf_bucket, s.direction, ROUND(AVG(t.rr_realized)::numeric,3) avg_r, COUNT(*) total FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id JOIN signal_features sf ON s.id=sf.signal_id WHERE 1=1 {sig_f} GROUP BY 1,2 ORDER BY 1,2")

    elif name == "edge_correlation":
        return await conn.fetch(f"SELECT ROUND(CORR(sf.trend_score,t.rr_realized)::numeric,4) trend_corr, ROUND(CORR(sf.momentum_score,t.rr_realized)::numeric,4) momentum_corr, ROUND(CORR(sf.volume_score,t.rr_realized)::numeric,4) volume_corr, ROUND(CORR(sf.pattern_score,t.rr_realized)::numeric,4) pattern_corr, ROUND(CORR(sf.mtf_score,t.rr_realized)::numeric,4) mtf_corr FROM signal_features sf JOIN trade_outcome_analytics t ON sf.signal_id=t.signal_id JOIN signals s ON s.id=sf.signal_id WHERE 1=1 {sig_f}")

    elif name == "edge_top_combo":
        return await conn.fetch(f"SELECT s.pattern,s.direction,s.timeframe,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE 1=1 {sig_f} GROUP BY s.pattern,s.direction,s.timeframe HAVING COUNT(*)>3 ORDER BY avg_r DESC LIMIT 30")

    elif name == "edge_hold_time":
        return await conn.fetch(f"SELECT CASE WHEN time_to_exit<10 THEN '<10' WHEN time_to_exit<30 THEN '10-30' WHEN time_to_exit<60 THEN '30-60' ELSE '>60' END AS bucket, COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE 1=1 {sig_f} GROUP BY bucket ORDER BY MIN(time_to_exit)")

    elif name == "edge_regime_pattern":
        return await conn.fetch(f"SELECT s.regime,s.pattern,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r FROM trade_outcome_analytics t JOIN signals s ON t.signal_id=s.id WHERE 1=1 {sig_f} GROUP BY s.regime,s.pattern HAVING COUNT(*)>3 ORDER BY avg_r DESC LIMIT 30")

    elif name == "edge_mfe_tp":
        return await conn.fetch(f"SELECT s.strategy_name, ROUND(AVG(max_favorable)::numeric,3) avg_mfe, ROUND(AVG(rr_realized)::numeric,3) avg_realized, ROUND((AVG(max_favorable)/NULLIF(AVG(rr_realized),0))::numeric,2) mfe_ratio FROM trade_outcome_analytics t JOIN signals s ON t.signal_id=s.id WHERE 1=1 {sig_f} GROUP BY s.strategy_name")

    elif name == "edge_mfe_mae_avg":
        return await conn.fetch(f"SELECT ROUND(AVG(max_favorable)::numeric,3) avg_mfe, ROUND(AVG(max_drawdown)::numeric,3) avg_mae FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE t.label IS NOT NULL {sig_f}")

    elif name == "edge_derivative_bias":
        return await conn.fetch(f"SELECT CASE WHEN derivative_bias>0 THEN 'Positive' WHEN derivative_bias<0 THEN 'Negative' ELSE 'Neutral' END AS bias_type, COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r, ROUND(AVG(CASE WHEN t.rr_realized>0 THEN 1 ELSE 0 END)*100,2) winrate FROM scan_debug d JOIN trade_outcome_analytics t ON d.signal_id=t.signal_id JOIN signals s ON s.id=d.signal_id WHERE t.label IS NOT NULL {sig_f} GROUP BY bias_type")

    elif name == "edge_derivative_effect":
        return await conn.fetch("WITH bi AS (SELECT CASE WHEN d.derivative_bias>0.3 THEN 'Strong +' WHEN d.derivative_bias>0.1 THEN 'Mild +' WHEN d.derivative_bias>=-0.1 THEN 'Neutral' WHEN d.derivative_bias>=-0.3 THEN 'Mild -' ELSE 'Strong -' END AS bucket, d.derivative_bias, d.total_score, s.status, t.rr_realized FROM scan_debug d JOIN signals s ON s.id=d.signal_id LEFT JOIN trade_outcome_analytics t ON t.signal_id=d.signal_id WHERE s.status IN ('WIN','LOSS') AND d.derivative_bias IS NOT NULL) SELECT bucket,COUNT(*) n, ROUND(AVG(derivative_bias)::numeric,4) avg_bias, ROUND(AVG(total_score)::numeric,3) avg_score, ROUND(AVG(CASE WHEN status='WIN' THEN 1.0 ELSE 0.0 END)*100,1) winrate, ROUND(AVG(rr_realized)::numeric,3) avg_r FROM bi GROUP BY bucket ORDER BY AVG(derivative_bias) DESC")

    elif name == "edge_rsi_bucket":
        return await conn.fetch(f"SELECT CONCAT(FLOOR(s.rsi/10)::int*10,'-',FLOOR(s.rsi/10)::int*10+10) AS rsi_bucket, COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r FROM signals s JOIN trade_outcome_analytics t ON t.signal_id=s.id WHERE s.rsi IS NOT NULL {sig_f} GROUP BY FLOOR(s.rsi/10) ORDER BY FLOOR(s.rsi/10)")

    elif name == "edge_atr_bucket":
        return await conn.fetch(f"SELECT width_bucket(s.atr_ratio,0.0001,0.1,10) AS atr_bucket, COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r FROM signals s JOIN trade_outcome_analytics t ON t.signal_id=s.id WHERE s.atr_ratio IS NOT NULL {sig_f} GROUP BY atr_bucket ORDER BY atr_bucket")

    elif name == "edge_data_validate":
        return await conn.fetch(f"SELECT s.id,s.symbol,s.direction,s.entry_price,s.stop_loss,s.take_profit, ROUND(((s.take_profit-s.entry_price)/NULLIF(ABS(s.entry_price-s.stop_loss),0))::numeric,2) AS rr, CASE WHEN s.direction='LONG' AND s.stop_loss>=s.entry_price THEN 'LONG SL>=Entry' WHEN s.direction='SHORT' AND s.stop_loss<=s.entry_price THEN 'SHORT SL<=Entry' ELSE 'OK' END AS flag FROM signals s WHERE s.status IN ('WIN','LOSS') {sig_f} ORDER BY CASE WHEN flag!='OK' THEN 0 ELSE 1 END,s.id DESC LIMIT 100")

    elif name == "edge_baseline_compare":
        mtf_min = float(params.get("mtf_min_score", 0.6))
        return await conn.fetch("WITH base AS (SELECT s.direction,s.timeframe,AVG(t.rr_realized)::numeric avg_r FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id WHERE t.label IS NOT NULL GROUP BY s.direction,s.timeframe), filt AS (SELECT s.direction,s.timeframe,COUNT(*) total, ROUND(AVG(t.rr_realized)::numeric,3) avg_r FROM trade_outcome_analytics t JOIN signals s ON s.id=t.signal_id JOIN signal_features sf ON s.id=sf.signal_id WHERE sf.mtf_score>$1 GROUP BY s.direction,s.timeframe) SELECT b.direction,b.timeframe, ROUND(b.avg_r,3) base_r, f.avg_r filtered_r, ROUND((f.avg_r-b.avg_r)::numeric,3) improvement, f.total FROM base b JOIN filt f ON b.direction=f.direction AND b.timeframe=f.timeframe WHERE f.total>10", mtf_min)

    elif name == "edge_sweet_spot":
        atr_t = float(params.get("atr_threshold", 0.4))
        mtf_t = float(params.get("mtf_threshold", 0.6))
        return await conn.fetch("WITH best AS (SELECT s.timeframe,s.direction,s.regime, CASE WHEN sf.mtf_score>=$1 THEN 'High MTF' ELSE 'Low MTF' END AS mtf_q, CASE WHEN (d.indicators_snapshot->>'ema50')::numeric>(d.indicators_snapshot->>'ema200')::numeric THEN 'Uptrend' ELSE 'Down/Side' END AS trend, CASE WHEN (d.indicators_snapshot->>'atr_percentile')::numeric<$2 THEN 'Low Vol' ELSE 'High Vol' END AS vol, t.rr_realized, t.label FROM signals s JOIN signal_features sf ON sf.signal_id=s.id JOIN scan_debug d ON d.signal_id=s.id JOIN trade_outcome_analytics t ON t.signal_id=s.id WHERE t.label IS NOT NULL AND d.indicators_snapshot IS NOT NULL) SELECT timeframe,direction,regime,mtf_q,trend,vol,COUNT(*) n, ROUND(AVG(label::numeric)*100,1) winrate, ROUND(AVG(rr_realized)::numeric,3) avg_r FROM best GROUP BY 1,2,3,4,5,6 HAVING COUNT(*)>=5 ORDER BY avg_r DESC LIMIT 30", mtf_t, atr_t)

    elif name == "edge_indicator_discovery":
        atr_l = float(params.get("atr_limit", 0.4))
        vol_l = float(params.get("vol_ratio_limit", 2.0))
        tests = [
            ("Baseline (LONG)", "d.direction='LONG' AND t.label IS NOT NULL"),
            ("EMA50>EMA200", "d.direction='LONG' AND t.label IS NOT NULL AND (d.indicators_snapshot->>'ema50')::numeric>(d.indicators_snapshot->>'ema200')::numeric"),
            ("EMA200_Slope>0", "d.direction='LONG' AND t.label IS NOT NULL AND (d.indicators_snapshot->>'ema200_slope')::numeric>0"),
            (f"ATR_Perc<{atr_l}", f"d.direction='LONG' AND t.label IS NOT NULL AND (d.indicators_snapshot->>'atr_percentile')::numeric<{atr_l}"),
            ("RSI_Slope>0", "d.direction='LONG' AND t.label IS NOT NULL AND (d.indicators_snapshot->>'rsi_slope')::numeric>0"),
            (f"VolRatio>{vol_l}", f"d.direction='LONG' AND t.label IS NOT NULL AND (d.indicators_snapshot->>'volume_ratio')::numeric>{vol_l}"),
        ]
        rows = []
        for tname, where in tests:
            try:
                r = await conn.fetchrow(f"SELECT COUNT(*) AS n, ROUND(AVG(t.rr_realized)::numeric,3) AS avg_r, ROUND(AVG(t.label::numeric)*100,1) AS wr FROM scan_debug d JOIN trade_outcome_analytics t ON d.signal_id=t.signal_id WHERE {where}")
                rows.append({"filter_name": tname, "n": r["n"] if r else 0, "avg_r": float(r["avg_r"] or 0) if r else 0, "winrate": float(r["wr"] or 0) if r else 0})
            except:
                rows.append({"filter_name": tname, "n": 0, "avg_r": 0, "winrate": 0})
        return rows

    else:
        return []