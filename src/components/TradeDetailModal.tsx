// @ts-nocheck
/* eslint-disable */
import { useEffect, useRef, useMemo } from 'react';
import { createChart, createSeriesMarkers, CrosshairMode, CandlestickSeries } from 'lightweight-charts';
import { X, TrendingUp, TrendingDown, Activity, Target, BarChart3, Globe } from 'lucide-react';
import { utcToVN } from '../utils/time';
import { getTradeEntryMs } from '../utils/klineSimulator';

function safeParseJSON(v) {
  if (!v) return null;
  if (typeof v === 'object') return v;
  try { return JSON.parse(v); } catch { return null; }
}

function Stat({ label, value, color = 'text-white', mono = true }) {
  return (
    <div className="flex justify-between py-1.5 text-xs border-b border-slate-800 last:border-0">
      <span className="text-slate-400">{label}</span>
      <span className={`${color} ${mono ? 'font-mono' : ''}`}>{value ?? '–'}</span>
    </div>
  );
}

function fmt(v, digits = 4) {
  if (v == null || v === '') return '–';
  const n = Number(v);
  if (!Number.isFinite(n)) return '–';
  if (Math.abs(n) >= 1000) return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
  return n.toFixed(digits);
}

function pct(v, digits = 2) {
  if (v == null) return '–';
  const n = Number(v);
  if (!Number.isFinite(n)) return '–';
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
}

export function TradeDetailModal({ trade, klines, onClose, loadingKlines = false }) {
  const chartContainerRef = useRef(null);
  const chartRef = useRef(null);

  const indicators = useMemo(() => safeParseJSON(trade?.indicators_snapshot) || {}, [trade]);
  const marketCtx = useMemo(() => safeParseJSON(trade?.market_context) || {}, [trade]);

  // Filter klines around the trade window
  const tradeKlines = useMemo(() => {
    if (!klines || !trade) return [];
    const anchorMs = getTradeEntryMs(trade);
    const exitMs = trade.exit_time ? new Date(trade.exit_time).getTime() : anchorMs + 3 * 86400000;
    // Add a small buffer before/after for context
    const startMs = anchorMs - 30 * 60_000;       // 30 min before
    const endMs = (trade.hit_at_ms || exitMs) + 30 * 60_000;
    return klines.filter(k => k.openTime >= startMs && k.openTime <= endMs);
  }, [klines, trade]);

  useEffect(() => {
    if (!chartContainerRef.current || !tradeKlines.length) return;

    const chartHeight = Math.min(380, Math.max(260, Math.floor(window.innerHeight * 0.42)));
    const chart = createChart(chartContainerRef.current, {
      layout: {
        background: { color: '#0f172a' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#334155' },
      timeScale: { borderColor: '#334155', timeVisible: true, secondsVisible: false },
      width: chartContainerRef.current.clientWidth,
      height: chartHeight,
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981',
      downColor: '#ef4444',
      borderUpColor: '#10b981',
      borderDownColor: '#ef4444',
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    candleSeries.setData(
      tradeKlines.map(k => ({
        time: Math.floor(k.openTime / 1000),
        open: k.open,
        high: k.high,
        low: k.low,
        close: k.close,
      }))
    );

    // Price lines: entry / SL / TP
    const entry = Number(trade.entry_price);
    const sl = Number(trade.sim_sl ?? trade.stop_loss);
    const tp = Number(trade.sim_tp ?? trade.take_profit);

    if (entry) {
      candleSeries.createPriceLine({
        price: entry, color: '#6366f1', lineWidth: 2, lineStyle: 0,
        axisLabelVisible: true, title: `Entry ${fmt(entry)}`,
      });
    }
    if (sl) {
      candleSeries.createPriceLine({
        price: sl, color: '#ef4444', lineWidth: 2, lineStyle: 2,
        axisLabelVisible: true, title: `SL ${fmt(sl)}`,
      });
    }
    if (tp) {
      candleSeries.createPriceLine({
        price: tp, color: '#10b981', lineWidth: 2, lineStyle: 2,
        axisLabelVisible: true, title: `TP ${fmt(tp)}`,
      });
    }

    // Hit marker
    if (trade.hit_at_ms) {
      createSeriesMarkers(candleSeries, [{
        time: Math.floor(trade.hit_at_ms / 1000),
        position: trade.sim_status === 'WIN' ? 'belowBar' : 'aboveBar',
        color: trade.sim_status === 'WIN' ? '#10b981' : '#ef4444',
        shape: trade.sim_status === 'WIN' ? 'arrowUp' : 'arrowDown',
        text: trade.sim_status === 'WIN' ? 'TP HIT' : 'SL HIT',
      }]);
    }

    chart.timeScale().fitContent();
    chartRef.current = chart;

    const handleResize = () => {
      if (chartContainerRef.current) {
        chart.applyOptions({ width: chartContainerRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [tradeKlines, trade]);

  if (!trade) return null;

  const isLong = trade.direction === 'LONG';
  const displayStatus = trade.sim_status || trade._derivedStatus || trade.status;
  const pnl = Number(trade.sim_result ?? trade._derivedPct ?? trade.result_percent ?? 0);
  const pnlColor = pnl > 0 ? 'text-emerald-400' : pnl < 0 ? 'text-red-400' : 'text-slate-400';

  // Market context extraction
  const macro1d = marketCtx?.entry?.macro_1d || {};
  const tactical1h = marketCtx?.entry?.tactical_1h || {};
  const struct4h = marketCtx?.entry?.structure_4h || {};

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm p-2 sm:p-4" onClick={onClose}>
      <div
        className="bg-slate-900 border border-slate-700 rounded-xl shadow-2xl w-full max-w-6xl max-h-[94vh] sm:max-h-[92vh] overflow-hidden flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between px-4 sm:px-5 py-3 border-b border-slate-700 bg-slate-800/50">
          <div className="flex flex-wrap items-center gap-2 sm:gap-3">
            <span className="text-xl font-bold text-white">{trade.symbol}</span>
            <span className={`inline-flex items-center gap-1 text-xs font-semibold px-2 py-1 rounded ${
              isLong ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'
            }`}>
              {isLong ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
              {trade.direction}
            </span>
            <span className="text-xs text-slate-500">{trade.timeframe}</span>
            <span className={`text-sm font-mono font-bold ${pnlColor}`}>{pct(pnl)}</span>
            {displayStatus && (
              <span className={`text-xs px-2 py-0.5 rounded font-semibold ${
                displayStatus === 'WIN' ? 'bg-emerald-500/15 text-emerald-400' :
                displayStatus === 'LOSS' ? 'bg-red-500/15 text-red-400' :
                'bg-orange-500/15 text-orange-400'
              }`}>{displayStatus}</span>
            )}
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-slate-700 rounded-lg text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-3 sm:p-5 space-y-5">
          {/* Chart */}
          <div className="bg-slate-950 rounded-lg border border-slate-800 p-2">
            {loadingKlines ? (
              <div className="h-[260px] sm:h-[380px] flex items-center justify-center text-slate-500 text-sm">
                Loading Binance 1m klines...
              </div>
            ) : tradeKlines.length === 0 ? (
              <div className="h-[260px] sm:h-[380px] flex items-center justify-center text-slate-500 text-sm">
                No kline data available for this trade window
              </div>
            ) : (
              <div ref={chartContainerRef} />
            )}
          </div>

          {/* Stats grid */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* Signal Summary */}
            <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
              <div className="flex items-center gap-2 mb-3">
                <Target className="w-4 h-4 text-indigo-400" />
                <h4 className="text-sm font-semibold text-white">Signal Summary</h4>
              </div>
              <Stat label="Direction" value={trade.direction} color={isLong ? 'text-emerald-400' : 'text-red-400'} mono={false} />
              <Stat label="Pattern" value={trade.pattern || '–'} mono={false} />
              <Stat label="Strategy" value={trade.strategy_name || '–'} mono={false} />
              <Stat label="Regime" value={trade.regime || '–'} mono={false} />
              <Stat label="Score" value={fmt(trade.score, 2)} />
              <Stat label="Engine v" value={trade.engine_version || '–'} />
              <Stat label="Status (Orig)" value={trade.status} mono={false} />
              <Stat label="Exit Reason" value={trade.exit_reason || trade._debug_exit_reason || '–'} mono={false} />
            </div>

            {/* Indicators */}
            <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
              <div className="flex items-center gap-2 mb-3">
                <Activity className="w-4 h-4 text-cyan-400" />
                <h4 className="text-sm font-semibold text-white">Indicators</h4>
              </div>
              <Stat label="RSI" value={fmt(indicators.rsi ?? trade.sf_rsi ?? trade.rsi_val ?? trade.rsi, 2)} />
              <Stat label="RSI Slope" value={fmt(indicators.rsi_slope, 4)} />
              <Stat label="ATR" value={fmt(indicators.atr, 4)} />
              <Stat label="ATR Ratio" value={fmt(indicators.atr_ratio ?? trade.sf_atr ?? trade.atr_ratio, 4)} />
              <Stat label="ATR %ile" value={fmt(indicators.atr_percentile, 2)} />
              <Stat label="EMA50" value={fmt(indicators.ema50, 4)} />
              <Stat label="EMA200" value={fmt(indicators.ema200, 4)} />
              <Stat label="EMA Dist" value={fmt(indicators.ema_distance ?? trade.sf_ema, 4)} />
              <Stat label="BB Width" value={fmt(indicators.bb_width, 4)} />
              <Stat label="Vol Ratio" value={fmt(indicators.volume_ratio ?? trade.sf_vol ?? trade.volume_ratio_val ?? trade.volume_ratio, 2)} />
            </div>

            {/* Market Context */}
            <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
              <div className="flex items-center gap-2 mb-3">
                <Globe className="w-4 h-4 text-amber-400" />
                <h4 className="text-sm font-semibold text-white">Market Context</h4>
              </div>
              <Stat label="Macro 1D" value={macro1d.trend || '–'} color={macro1d.trend === 'BULL' ? 'text-emerald-400' : macro1d.trend === 'BEAR' ? 'text-red-400' : 'text-slate-400'} mono={false} />
              <Stat label="EMA50/200 %" value={fmt(macro1d.ema50_vs_ema200_pct, 4)} />
              <Stat label="Dist EMA200" value={fmt(macro1d.distance_from_ema200_pct, 4)} />
              <Stat label="4H Trend" value={struct4h.trend || '–'} color={struct4h.trend === 'BULL' ? 'text-emerald-400' : struct4h.trend === 'BEAR' ? 'text-red-400' : 'text-slate-400'} mono={false} />
              <Stat label="4H ATR%" value={fmt(struct4h.atr_pct, 4)} />
              <Stat label="1H RSI" value={fmt(tactical1h.rsi, 2)} />
              <Stat label="1H ATR%" value={fmt(tactical1h.atr_pct, 4)} />
              {marketCtx?.execution?.mode && (
                <Stat label="Exec Mode" value={marketCtx.execution.mode} mono={false} />
              )}
              {marketCtx?.breakeven_applied != null && (
                <Stat label="Breakeven" value={marketCtx.breakeven_applied ? 'YES' : 'NO'} color={marketCtx.breakeven_applied ? 'text-amber-400' : 'text-slate-500'} mono={false} />
              )}
            </div>

            {/* Simulation Result */}
            <div className="bg-slate-800/50 rounded-lg p-4 border border-slate-700">
              <div className="flex items-center gap-2 mb-3">
                <BarChart3 className="w-4 h-4 text-emerald-400" />
                <h4 className="text-sm font-semibold text-white">Simulation</h4>
              </div>
              <Stat label="Entry" value={fmt(trade.entry_price)} color="text-indigo-400" />
              <Stat label="SL (Orig)" value={fmt(trade.stop_loss)} color="text-red-300" />
              <Stat label="TP (Orig)" value={fmt(trade.take_profit)} color="text-emerald-300" />
              <Stat label="SL (Sim)" value={fmt(trade.sim_sl ?? trade.stop_loss)} color="text-red-400" />
              <Stat label="TP (Sim)" value={fmt(trade.sim_tp ?? trade.take_profit)} color="text-emerald-400" />
              <Stat label="SL %" value={trade._debug_sl_pct != null ? `${Number(trade._debug_sl_pct).toFixed(3)}%` : '–'} />
              <Stat label="TP %" value={trade._debug_tp_pct != null ? `${Number(trade._debug_tp_pct).toFixed(3)}%` : '–'} />
              <Stat label="Result" value={pct(pnl)} color={pnlColor} />
              <Stat label="Status" value={displayStatus || '-'} mono={false} color={
                displayStatus === 'WIN' ? 'text-emerald-400' :
                displayStatus === 'LOSS' ? 'text-red-400' : 'text-orange-400'
              } />
              <Stat label="Entry Time" value={utcToVN(trade.entry_time || trade.created_at || trade.candle_time)} mono={false} />
              <Stat label="Hit At" value={trade.hit_at_ms ? utcToVN(new Date(trade.hit_at_ms).toISOString()) : '–'} mono={false} />
              {trade._debug_scanned != null && (
                <Stat label="Bars Scanned" value={trade._debug_scanned} />
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
