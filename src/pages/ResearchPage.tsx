// @ts-nocheck
/* eslint-disable */
import { useState, useMemo, useEffect } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Select } from '../components/ui/Select';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { DataTable } from '../components/ui/Table';
import { PercentChangeBadge, StatusBadge } from '../components/ui/Badge';
import { Heatmap } from '../components/charts/Heatmap';
import { Play, RotateCcw, Microscope } from 'lucide-react';
import {
  AreaChart, Area, LineChart, Line, BarChart as ReBarChart, Bar, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts';
import { utcToVN, getTodayVN, normalizeSignalDates as normalizeTradeDates } from '../utils/time';

import { TradeDetailModal } from '../components/TradeDetailModal';
import {
  buildFetchPlan, batchFetchKlines, simulateTradeWithKlines, getKlineCacheSize
} from '../utils/klineSimulator';

const API = '/api';

function ScoreCell({ value }) {
  const v = Number(value) || 0;
  return <span className={`font-mono text-sm ${v >= 8 ? 'text-emerald-400' : v >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>{v.toFixed(2)}</span>;
}
function ChartTip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl text-sm">
      <p className="text-slate-400 mb-2">{label}</p>
      {payload.map((e, i) => (
        <div key={i} className="flex items-center gap-2 mb-1">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: e.color }} />
          <span className="text-slate-300">{e.name}:</span>
          <span className="font-bold text-white">
            {e.name.includes('DD') ? `-${Number(e.value).toFixed(2)}%` : `$${Number(e.value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          </span>
        </div>
      ))}
    </div>
  );
}
function bucketize(val, ranges) {
  for (const [lo, hi] of ranges) { if (val >= lo && val < hi) return hi === Infinity ? `>=${lo}` : `${lo}-${hi}`; }
  return 'other';
}
const DEFAULTS = {
  initialCapital: 10000, positionSize: 1000, startDate: '', endDate: '',
  dateField: 'exit_time',
  symbols: '', symbolMode: 'include', timeframes: [],
  engineVersion: 'all', engineMode: 'only', direction: 'all',
  strategy: 'all', patterns: [], regimes: [],
  rsiMin: '0', rsiMax: '100', volumeRatioMin: '0', atrRatioMin: '0',
  emaDistMin: '-10', emaDistMax: '10',
  scoreMin: '0', scoreMax: '10', trendScoreMin: '0', momentumScoreMin: '0',
  volumeScoreMin: '0', mtfScoreMin: '0', mtfScoreMax: '1',
  rrOverride: '', slPct: '', tpPct: '', reverseDirection: false,
};

function DebugPanel({ trades }) {
  const [page, setPage] = useState(1);
  const [showOnlyNotCount, setShowOnlyNotCount] = useState(false);
  const pageSize = 20;
  const filteredTrades = showOnlyNotCount ? trades.filter(t => t.sim_counted === false) : trades;
  const totalPages = Math.ceil(filteredTrades.length / pageSize);
  const paged = filteredTrades.slice((page - 1) * pageSize, page * pageSize);

  const copyStreak = () => {
    const streak = trades.map(t => {
      const s = t.sim_status || '';
      return s === 'WIN' ? 'W' : s === 'LOSS' ? 'L' : s === 'NOT_COUNT' ? 'N' : '-';
    }).join(' ');
    navigator.clipboard.writeText(streak);
    alert(`Copied ${trades.length} simulated results to clipboard`);
  };

  const exportCSV = () => {
    const headers = ['#','Symbol','TF','Dir','Entry','SL_Orig','TP_Orig','SL_Sim','TP_Sim','MAE%','MFE%','SL%','TP%','HitSL','HitTP','Orig%','Sim%','Status_Orig','Status_Sim','Counted','ExitReason'];
    const rows = trades.map((t, i) => [
      i + 1, t.symbol, t.timeframe, t.direction,
      Number(t.entry_price || 0).toFixed(6), Number(t.stop_loss || 0).toFixed(6), Number(t.take_profit || 0).toFixed(6),
      Number(t.sim_sl || 0).toFixed(6), Number(t.sim_tp || 0).toFixed(6),
      Number(t._debug_mae || 0).toFixed(4), Number(t._debug_mfe || 0).toFixed(4),
      t._debug_sl_pct != null ? Number(t._debug_sl_pct).toFixed(4) : '', t._debug_tp_pct != null ? Number(t._debug_tp_pct).toFixed(4) : '',
      t._debug_hit_sl ? 'YES' : 'NO', t._debug_hit_tp ? 'YES' : 'NO',
      Number(t._debug_original_result || 0).toFixed(4), t.sim_result != null ? Number(t.sim_result).toFixed(4) : '',
      t.status || '', t.sim_status || '', t.sim_counted === false ? 'NO' : 'YES', t._debug_exit_reason || '',
    ].join(','));
    const csv = [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `rr_debug_${Date.now()}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <Card>
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="font-semibold text-white flex items-center gap-2">🔍 RR Debug Panel</h3>
          <p className="text-xs text-slate-500 mt-0.5">MAE/MFE = recalculated from Binance 1m klines for this simulation.</p>
        </div>
        <div className="flex gap-2 items-center">
          <button onClick={() => { setShowOnlyNotCount(!showOnlyNotCount); setPage(1); }} className={`px-2 py-1 rounded text-xs ${showOnlyNotCount ? 'bg-orange-600 text-white' : 'bg-slate-700 text-slate-300'}`}>
            {showOnlyNotCount ? 'Showing NOT_COUNT' : 'Filter NOT_COUNT'}
          </button>
          <button onClick={copyStreak} className="px-2 py-1 bg-indigo-700 hover:bg-indigo-600 text-white rounded text-xs">📋 Streak Simulation</button>
          <button onClick={exportCSV} className="px-2 py-1 bg-emerald-700 hover:bg-emerald-600 text-white rounded text-xs">📥 Export CSV</button>
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="border-b border-slate-700 text-slate-400">
              <th className="py-2 px-1.5 text-left">#</th><th className="py-2 px-1.5 text-left">Symbol</th><th className="py-2 px-1.5 text-center">TF</th><th className="py-2 px-1.5 text-right">Entry</th>
              <th className="py-2 px-1.5 text-right">MAE%</th><th className="py-2 px-1.5 text-right">MFE%</th>
              <th className="py-2 px-1.5 text-right text-slate-500">SL orig</th><th className="py-2 px-1.5 text-right text-slate-500">TP orig</th>
              <th className="py-2 px-1.5 text-right text-orange-400">SL% sim</th><th className="py-2 px-1.5 text-right text-cyan-400">TP% sim</th>
              <th className="py-2 px-1.5 text-center">Hit SL</th><th className="py-2 px-1.5 text-center">Hit TP</th>
              <th className="py-2 px-1.5 text-right">Orig%</th><th className="py-2 px-1.5 text-right">Sim%</th>
              <th className="py-2 px-1.5 text-center">St.Orig</th><th className="py-2 px-1.5 text-center">St.Sim</th><th className="py-2 px-1.5 text-center">Counted-</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((t, i) => {
              const idx = (page - 1) * pageSize + i + 1;
              return (
                <tr key={i} className="border-b border-slate-800 hover:bg-slate-800/50">
                  <td className="py-1.5 px-1.5 text-slate-500">{idx}</td>
                  <td className="py-1.5 px-1.5">{t.symbol}</td>
                  <td className="py-1.5 px-1.5 text-center text-slate-400">{t.timeframe}</td>
                  <td className="py-1.5 px-1.5 text-right">{Number(t.entry_price).toFixed(4)}</td>
                  <td className="py-1.5 px-1.5 text-right text-red-400">{Number(t._debug_mae || 0).toFixed(4)}</td>
                  <td className="py-1.5 px-1.5 text-right text-emerald-400">{Number(t._debug_mfe || 0).toFixed(4)}</td>
                  <td className="py-1.5 px-1.5 text-right text-slate-500">{Number(t.stop_loss || 0).toFixed(4)}</td>
                  <td className="py-1.5 px-1.5 text-right text-slate-500">{Number(t.take_profit || 0).toFixed(4)}</td>
                  <td className="py-1.5 px-1.5 text-right text-orange-400">{t._debug_sl_pct != null ? Number(t._debug_sl_pct).toFixed(4) : '-'}</td>
                  <td className="py-1.5 px-1.5 text-right text-cyan-400">{t._debug_tp_pct != null ? Number(t._debug_tp_pct).toFixed(4) : '-'}</td>
                  <td className={`py-1.5 px-1.5 text-center ${t._debug_hit_sl ? 'text-red-400 font-bold' : 'text-slate-600'}`}>{t._debug_hit_sl ? 'Y' : '-'}</td>
                  <td className={`py-1.5 px-1.5 text-center ${t._debug_hit_tp ? 'text-emerald-400 font-bold' : 'text-slate-600'}`}>{t._debug_hit_tp ? 'Y' : '-'}</td>
                  <td className="py-1.5 px-1.5 text-right">{Number(t._debug_original_result || 0).toFixed(2)}</td>
                  <td className={`py-1.5 px-1.5 text-right font-bold ${t.sim_counted === false ? 'text-slate-500 italic' : (t.sim_result || 0) > 0 ? 'text-emerald-400' : 'text-red-400'}`}>{t.sim_counted === false ? 'Not Count' : Number(t.sim_result || 0).toFixed(2)}</td>
                  <td className={`py-1.5 px-1.5 text-center ${t.status === 'WIN' ? 'text-emerald-500' : 'text-red-500'}`}>{t.status === 'WIN' ? 'W' : 'L'}</td>
                  <td className={`py-1.5 px-1.5 text-center font-bold ${t.sim_status === 'WIN' ? 'text-emerald-400' : t.sim_status === 'LOSS' ? 'text-red-400' : 'text-orange-400'}`}>{t.sim_status === 'WIN' ? 'W' : t.sim_status === 'LOSS' ? 'L' : 'N'}</td>
                  <td className={`py-1.5 px-1.5 text-center font-bold ${t.sim_counted === false ? 'text-orange-400' : 'text-emerald-400'}`}>{t.sim_counted === false ? 'NO' : 'YES'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className="flex items-center justify-between mt-3 px-2">
          <span className="text-xs text-slate-500">{filteredTrades.length} trades • Page {page}/{totalPages}</span>
          <div className="flex gap-1">
            <button onClick={() => setPage(1)} disabled={page === 1} className="px-2 py-1 text-xs bg-slate-700 rounded disabled:opacity-30">First</button>
            <button onClick={() => setPage(Math.max(1, page - 1))} disabled={page === 1} className="px-2 py-1 text-xs bg-slate-700 rounded disabled:opacity-30">Prev</button>
            <button onClick={() => setPage(Math.min(totalPages, page + 1))} disabled={page === totalPages} className="px-2 py-1 text-xs bg-slate-700 rounded disabled:opacity-30">Next</button>
            <button onClick={() => setPage(totalPages)} disabled={page === totalPages} className="px-2 py-1 text-xs bg-slate-700 rounded disabled:opacity-30">Last</button>
          </div>
        </div>
      )}
    </Card>
  );
}

export function Research() {
  const [selectedTrade, setSelectedTrade] = useState(null);
  const [klineCache, setKlineCache] = useState(new Map()); // symbol -> klines[]
  const [fetchProgress, setFetchProgress] = useState(null); // { done, total } | null
  const [running, setRunning] = useState(false);
  const [trades, setTrades] = useState([]);
  const [engineVersions, setEngineVersions] = useState([]);
  const [allStrategies, setAllStrategies] = useState([]);
  const [allPatterns, setAllPatterns] = useState([]);

  const [cfg, setCfg] = useState({ ...DEFAULTS });
  const set = (key, val) => setCfg(prev => ({ ...prev, [key]: val }));

  useEffect(() => {
    (async () => {
      try {
        const [vers, sigs] = await Promise.all([
          fetch(`${API}/engine/versions`).then(r => r.json()).catch(() => []),
          fetch(`${API}/signals-limit=10000`).then(r => r.json()).catch(() => ({ data: [] })),
        ]);
        setEngineVersions(vers.map(v => String(v.engine_version)).filter(Boolean).sort().reverse());
        const s = sigs.data || [];
        setAllStrategies(Array.from(new Set(s.map(x => x.strategy_name).filter(Boolean))).sort());
        setAllPatterns(Array.from(new Set(s.map(x => x.pattern).filter(Boolean))).sort());
      } catch {}
      runWithConfig(DEFAULTS);
    })();
  }, []);

  const runWithConfig = async (c) => {
  setRunning(true);
  setFetchProgress(null);
  try {
    const body = { initial_capital: c.initialCapital, position_size: c.positionSize };
    if (c.startDate) body.start_date = c.startDate;
    if (c.endDate) body.end_date = c.endDate;
    body.date_field = c.dateField;
    if (c.symbols.trim()) { body.symbols = c.symbols; body.symbol_mode = c.symbolMode; }
    if (c.timeframes.length) body.timeframes = c.timeframes;
    if (c.engineVersion !== 'all') body.engine_version = c.engineMode === 'newest' ? c.engineVersion + '+' : c.engineVersion;
    if (c.direction !== 'all') body.direction = c.direction;
    if (c.strategy !== 'all') body.strategy = c.strategy;
    if (c.patterns.length) body.patterns = c.patterns;
    if (c.regimes.length) body.regimes = c.regimes;
    const rMin = parseFloat(c.rsiMin); if (rMin > 0) body.rsi_min = rMin;
    const rMax = parseFloat(c.rsiMax); if (rMax < 100) body.rsi_max = rMax;
    const vrm = parseFloat(c.volumeRatioMin); if (vrm > 0) body.volume_ratio_min = vrm;
    const arm = parseFloat(c.atrRatioMin); if (arm > 0) body.atr_ratio_min = arm;
    const edMin = parseFloat(c.emaDistMin); if (edMin > -10) body.ema_distance_min = edMin;
    const edMax = parseFloat(c.emaDistMax); if (edMax < 10) body.ema_distance_max = edMax;
    const sMin = parseFloat(c.scoreMin); if (sMin > 0) body.score_min = sMin;
    const sMax = parseFloat(c.scoreMax); if (sMax < 10) body.score_max = sMax;
    const tsm = parseFloat(c.trendScoreMin); if (tsm > 0) body.trend_score_min = tsm;
    const msm = parseFloat(c.momentumScoreMin); if (msm > 0) body.momentum_score_min = msm;
    const vsm = parseFloat(c.volumeScoreMin); if (vsm > 0) body.volume_score_min = vsm;
    const mtfm = parseFloat(c.mtfScoreMin); if (mtfm > 0) body.mtf_score_min = mtfm;
    const mtfx = parseFloat(c.mtfScoreMax); if (mtfx < 1) body.mtf_score_max = mtfx;
    // FE owns RR/SL/TP/reverse simulation with real Binance klines.
    // Do not send these params to the backend MAE/MFE simulator.

    const res = await fetch(`${API}/research/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    // Filter invalid SL placement
    let validTrades = (data.trades || []).filter(t => {
      const entry = Number(t.entry_price) || 0;
      const sl = Number(t.stop_loss) || 0;
      if (!entry || !sl) return true;
      if (t.direction === 'LONG' && sl >= entry) return false;
      if (t.direction === 'SHORT' && sl <= entry) return false;
      return true;
    });

    // Check if simulation needed
    const rrVal = parseFloat(c.rrOverride);
    const slVal = parseFloat(c.slPct);
    const tpVal = parseFloat(c.tpPct);
    const hasSlTp = !isNaN(slVal) && slVal > 0 && !isNaN(tpVal) && tpVal > 0;
    const hasRR = !isNaN(rrVal) && rrVal > 0;
    const needSim = hasSlTp || hasRR;

    let klineMap = new Map();

    if (needSim) {
      // Build unique symbol/timerange plan
      const plan = buildFetchPlan(validTrades);
      if (plan.length > 0) {
        setFetchProgress({ done: 0, total: plan.length });
        klineMap = await batchFetchKlines(
          plan,
          (done, total) => setFetchProgress({ done, total }),
          3, 250
        );
        setKlineCache(klineMap);
      }

      // Simulate each trade
      const simOpts = {
        slPct: hasSlTp ? slVal : null,
        tpPct: hasSlTp ? tpVal : null,
        rrOverride: hasRR && !hasSlTp ? rrVal : null,
        reverseDirection: !!c.reverseDirection,
      };
      validTrades = validTrades.map(t => {
        const klines = klineMap.get(t.symbol) || [];
        const sim = simulateTradeWithKlines(t, klines, simOpts);
        return { ...t, ...sim };
      });
    } else {
      // No simulation: clear any previous sim_* fields, use original status/result
      validTrades = validTrades.map(t => ({
        ...t,
        sim_result: Number(t.result_percent || 0),
        sim_status: t.status,
        sim_counted: true,
        sim_sl: t.stop_loss,
        sim_tp: t.take_profit,
      }));
      setKlineCache(new Map());
    }

    setTrades(validTrades.map(normalizeTradeDates));
  } catch (e) {
    console.error(e);
  } finally {
    setRunning(false);
    setFetchProgress(null);
  }
};

  const handleRun = () => runWithConfig(cfg);
  const handleReset = () => setCfg({ ...DEFAULTS });
  const toggleTF = (tf) => set('timeframes', cfg.timeframes.includes(tf) ? cfg.timeframes.filter(x => x !== tf) : [...cfg.timeframes, tf]);
  const tradesDesc = useMemo(() => [...trades].sort((a, b) => new Date(b.exit_time || 0).getTime() - new Date(a.exit_time || 0).getTime()), [trades]);

  const results = useMemo(() => {
    if (!trades.length) return null;
    const fs = cfg.positionSize; const IC = cfg.initialCapital;
    const countedTrades = trades.filter(t => t.sim_counted !== false);
    let nav = IC, peakNav = nav, troughNav = nav, maxDD = 0, maxGain = 0;
    const curve = []; const pnlList = [];
    countedTrades.forEach(t => {
      const rp = Number(t.sim_result || 0); const pnl = fs * (rp / 100);
      nav += pnl; pnlList.push(pnl);
      peakNav = Math.max(peakNav, nav); troughNav = Math.min(troughNav, nav);
      const dd = (peakNav - nav) / peakNav * 100;
      maxDD = Math.max(maxDD, dd); maxGain = Math.max(maxGain, (nav - IC) / IC * 100);
      curve.push({ time: t.exit_time ? utcToVN(t.exit_time) : '', equity: Math.round(nav * 100) / 100, dd: Math.round(dd * 100) / 100 });
    });
    const total = countedTrades.length, wins = countedTrades.filter(t => Number(t.sim_result || 0) > 0).length, losses = countedTrades.filter(t => Number(t.sim_result || 0) < 0).length;
    const wr = total > 0 ? (wins / total) * 100 : 0;
    const gp = countedTrades.filter(t => Number(t.sim_result || 0) > 0).reduce((a, t) => a + Number(t.sim_result || 0), 0);
    const gl = Math.abs(countedTrades.filter(t => Number(t.sim_result || 0) < 0).reduce((a, t) => a + Number(t.sim_result || 0), 0));
    const pf = gl > 0 ? gp / gl : gp > 0 ? Infinity : 0;
    const avgP = wins > 0 ? gp / wins : 0; const avgL = losses > 0 ? gl / losses : 0;
    const exp = total > 0 ? (wr / 100) * avgP - ((1 - wr / 100) * avgL) : 0;
    const pctR = pnlList.map(p => (p / IC) * 100); const avg = pctR.length ? pctR.reduce((a, b) => a + b, 0) / pctR.length : 0;
    const std = pctR.length ? Math.sqrt(pctR.reduce((s, x) => s + (x - avg) ** 2, 0) / pctR.length) : 0; const sharpe = std > 0 ? avg / std : 0;
    const longT = countedTrades.filter(t => t.direction === 'LONG'); const shortT = countedTrades.filter(t => t.direction === 'SHORT');
    const longWR = longT.length > 0 ? (longT.filter(t => Number(t.sim_result || 0) > 0).length / longT.length) * 100 : 0;
    const shortWR = shortT.length > 0 ? (shortT.filter(t => Number(t.sim_result || 0) > 0).length / shortT.length) * 100 : 0;
    const durations = countedTrades.filter(t => t.candle_time && t.exit_time).map(t => new Date(t.exit_time).getTime() - new Date(t.candle_time).getTime()).filter(d => d > 0);
    const avgDurMs = durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : 0;
    const avgDurMin = Math.round(avgDurMs / 60000); let avgDurStr = '-';
    if (avgDurMin > 0) { const h = Math.floor(avgDurMin / 60); const m = avgDurMin % 60; avgDurStr = h >= 24 ? `${Math.floor(h / 24)}d ${h % 24}h` : h > 0 ? `${h}h ${m}m` : `${m}m`; }
    const notCount = trades.length - countedTrades.length;
    let mw = 0, ml = 0, cw = 0, cl = 0;
    countedTrades.forEach(t => { if (Number(t.sim_result || 0) > 0) { cw++; cl = 0; mw = Math.max(mw, cw); } else { cl++; cw = 0; ml = Math.max(ml, cl); } });
    return { nav, pnl: nav - IC, totalReturn: ((nav - IC) / IC) * 100, peakNav, troughNav, maxDD, maxGain, total, wins, losses, wr, pf, avgP, avgL, exp, sharpe, longWR, shortWR, longTotal: longT.length, shortTotal: shortT.length, avgDurStr, notCount, counted: countedTrades.length, maxWinStreak: mw, maxLossStreak: ml, curve };
  }, [trades, cfg.positionSize, cfg.initialCapital]);

  const regimeData = useMemo(() => {
    if (!trades.length) return [];
    const src = trades.filter(t => t.sim_counted !== false);
    const reg = {};
    src.forEach(t => { const r = t.regime || 'UNKNOWN'; if (!reg[r]) reg[r] = { t: 0, w: 0, ret: [] }; reg[r].t++; if ((t.sim_result || 0) > 0) reg[r].w++; reg[r].ret.push(t.sim_result || 0); });
    return Object.entries(reg).map(([regime, d]) => { const wr = d.t > 0 ? (d.w / d.t) * 100 : 0; const gp = d.ret.filter(r => r > 0).reduce((a, b) => a + b, 0); const gl = Math.abs(d.ret.filter(r => r < 0).reduce((a, b) => a + b, 0)); return { regime, trades: d.t, winrate: wr, profitFactor: gl > 0 ? gp / gl : gp > 0 ? Infinity : 0, totalReturn: d.ret.reduce((a, b) => a + b, 0) }; }).sort((a, b) => b.trades - a.trades);
  }, [trades]);

  const rsiBuckets = useMemo(() => {
    const src = trades.filter(t => t.sim_counted !== false);
    const ranges = [[0, 20], [20, 30], [30, 40], [40, 50], [50, 60], [60, 70], [70, 80], [80, 100]];
    const buckets = {};
    ranges.forEach(([lo, hi]) => { buckets[`${lo}-${hi}`] = { t: 0, w: 0, ret: [] }; });
    src.forEach(t => { const rsi = t.rsi_val || t.rsi || 0; const key = bucketize(rsi, ranges); if (buckets[key]) { buckets[key].t++; if ((t.sim_result || 0) > 0) buckets[key].w++; buckets[key].ret.push(t.sim_result || 0); } });
    return Object.entries(buckets).filter(([, d]) => d.t > 0).map(([range, d]) => { const wr = d.t > 0 ? (d.w / d.t) * 100 : 0; const gp = d.ret.filter(r => r > 0).reduce((a, b) => a + b, 0); const gl = Math.abs(d.ret.filter(r => r < 0).reduce((a, b) => a + b, 0)); const avgW = d.w > 0 ? gp / d.w : 0; const avgL = (d.t - d.w) > 0 ? gl / (d.t - d.w) : 0; return { range, trades: d.t, winrate: wr, pf: gl > 0 ? gp / gl : gp > 0 ? Infinity : 0, expectancy: (wr / 100) * avgW - ((1 - wr / 100) * avgL) }; });
  }, [trades]);

  const patternHM = useMemo(() => {
    const src = trades.filter(t => t.sim_counted !== false);
    if (!src.length) return [];
    const g = {};
    src.forEach(t => { if (!t.pattern) return; if (!g[t.pattern]) g[t.pattern] = { All: { w: 0, t: 0 } }; if (!g[t.pattern][t.timeframe]) g[t.pattern][t.timeframe] = { w: 0, t: 0 }; g[t.pattern][t.timeframe].t++; g[t.pattern].All.t++; if ((t.sim_result || 0) > 0) { g[t.pattern][t.timeframe].w++; g[t.pattern].All.w++; } });
    const data = []; Object.keys(g).forEach(p => ['15m', '1h', '4h', 'All'].forEach(tf => { const s = g[p]?.[tf] || { w: 0, t: 0 }; data.push({ x: tf, y: p, value: s.t > 0 ? (s.w / s.t) * 100 : 50, count: s.t }); })); return data;
  }, [trades]);

  const volRsiHM = useMemo(() => {
    const src = trades.filter(t => t.sim_counted !== false);
    const rsiR = [[0, 30], [30, 40], [40, 50], [50, 60], [60, Infinity]];
    const volR = [[0, 1], [1, 2], [2, 3], [3, 5], [5, Infinity]];
    const g = {};
    src.forEach(t => { const rsi = t.rsi_val || t.rsi || 0; const vr = t.volume_ratio_val || t.volume_ratio || 0; const rK = bucketize(rsi, rsiR); const vK = bucketize(vr, volR); if (!g[rK]) g[rK] = {}; if (!g[rK][vK]) g[rK][vK] = { t: 0, gp: 0, gl: 0 }; g[rK][vK].t++; const r = t.sim_result || 0; if (r > 0) g[rK][vK].gp += r; else g[rK][vK].gl += Math.abs(r); });
    const data = []; Object.entries(g).forEach(([rsi, vols]) => Object.entries(vols).forEach(([vol, d]) => { data.push({ x: vol, y: `RSI ${rsi}`, value: d.gl > 0 ? d.gp / d.gl : d.gp > 0 ? 2 : 0, count: d.t }); })); return data;
  }, [trades]);

  const scoreDist = useMemo(() => {
    const src = trades.filter(t => t.sim_counted !== false);
    const ranges = [[0, 5], [5, 6], [6, 7], [7, 8], [8, 9], [9, 10]];
    const buckets = {};
    ranges.forEach(([lo, hi]) => { buckets[`${lo}-${hi}`] = { wins: 0, losses: 0 }; });
    src.forEach(t => { const score = Number(t.score) || 0; const key = bucketize(score, ranges); if (buckets[key]) { if ((t.sim_result || 0) > 0) buckets[key].wins++; else buckets[key].losses++; } });
    return Object.entries(buckets).filter(([, d]) => d.wins + d.losses > 0).map(([range, d]) => ({ range, wins: d.wins, losses: d.losses, total: d.wins + d.losses, winrate: (d.wins + d.losses) > 0 ? (d.wins / (d.wins + d.losses)) * 100 : 0 }));
  }, [trades]);

  const tradeColumns = [
    { key: '__idx', header: '#', width: '40px', render: (_, row) => <span className="text-xs text-slate-500 whitespace-nowrap">{row.__idx}</span> },
    { key: 'symbol', header: 'Symbol', width: '90px', sortable: true, render: v => <span className="whitespace-nowrap text-xs">{v}</span> },
    { key: 'direction', header: 'Dir', width: '76px', sortable: true, render: v => (<span className={`inline-flex items-center gap-1 whitespace-nowrap text-[11px] font-semibold px-2 py-1 rounded-md ${v === 'LONG' ? 'bg-emerald-500/15 text-emerald-400' : 'bg-red-500/15 text-red-400'}`}><span>{v === 'LONG' ? '▲' : '▼'}</span><span>{v}</span></span>) },
    { key: 'timeframe', header: 'TF', width: '54px', sortable: true, render: v => <span className="whitespace-nowrap text-xs">{v}</span> },
    { key: 'pattern', header: 'Pattern', width: '110px', sortable: true, render: v => <span className="text-[11px] whitespace-nowrap">{v}</span> },
    { key: 'entry_price', header: 'Entry', width: '90px', render: v => <span className="whitespace-nowrap text-xs">{v?.toFixed(v > 100 ? 2 : 4) || '-'}</span> },
    { key: 'sim_sl', header: 'SL (Sim)', width: '90px', render: v => <span className="text-red-400 whitespace-nowrap text-xs">{v?.toFixed(v > 100 ? 2 : 4) || '-'}</span> },
    { key: 'sim_tp', header: 'TP (Sim)', width: '90px', render: v => <span className="text-emerald-400 whitespace-nowrap text-xs">{v?.toFixed(v > 100 ? 2 : 4) || '-'}</span> },
    { key: 'sim_result', header: 'P&L (Sim)', width: '110px', sortable: true, render: (v, row) => row.sim_counted === false ? <span className="text-slate-500 italic whitespace-nowrap text-xs">Not Count</span> : <PercentChangeBadge value={v || 0} /> },
    { key: 'status', header: 'Status Orig', width: '96px', sortable: true, render: v => <StatusBadge status={v || 'N/A'} /> },
    { key: 'sim_status', header: 'Status Sim', width: '96px', sortable: true, render: v => <StatusBadge status={v || 'N/A'} /> },
    { key: 'score', header: 'Score', width: '80px', sortable: true, render: v => <ScoreCell value={v} /> },
    { key: 'regime', header: 'Regime', width: '70px', sortable: true, render: v => <span className="inline-flex items-center px-2 py-1 rounded-md bg-slate-700 text-slate-200 text-[11px] whitespace-nowrap">{v === 'SIDEWAYS' ? 'SW' : v || 'N/A'}</span> },
    { key: 'entry_time', header: 'Opened', width: '90px', sortable: true, render: (v, row) => <span className="text-[11px] whitespace-nowrap text-slate-400">{utcToVN(v || row.created_at || row.candle_time)}</span> },
    { key: 'exit_time', header: 'Closed', width: '90px', sortable: true, render: v => <span className="text-[11px] whitespace-nowrap text-slate-400">{utcToVN(v)}</span> },
  ];

  const $ = v => v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const clr = v => v >= 0 ? 'text-emerald-400' : 'text-red-400';

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Microscope className="w-7 h-7 text-indigo-400" />
        <div><h2 className="text-2xl font-bold text-white">Strategy Research</h2><p className="text-slate-400 mt-0.5">Real Trade Mode — {trades.length} trades loaded</p></div>
      </div>

      <div className="flex flex-col xl:flex-row gap-6">
        <div className="w-full xl:w-80 xl:flex-shrink-0 space-y-3">
          <div className="flex gap-2"><Button variant="primary" className="flex-1" icon={running ? undefined : <Play className="w-4 h-4" />} loading={running} onClick={handleRun}>Run</Button><Button variant="ghost" icon={<RotateCcw className="w-4 h-4" />} onClick={handleReset}>Reset</Button></div>

          <Card padding="sm"><p className="text-xs font-semibold text-slate-500 uppercase mb-2">Capital</p><div className="grid grid-cols-2 gap-2"><Input type="number" label="Initial ($)" value={cfg.initialCapital} onChange={e => set('initialCapital', Number(e.target.value) || 10000)} /><Input type="number" label="Position ($)" value={cfg.positionSize} onChange={e => set('positionSize', Number(e.target.value) || 1000)} /></div></Card>

          <Card padding="sm"><p className="text-xs font-semibold text-slate-500 uppercase mb-2">Feature Index</p><div className="space-y-2">
            <div className="grid grid-cols-2 gap-2"><Input type="date" label="Start" value={cfg.startDate} onChange={e => set('startDate', e.target.value)} /><Input type="date" label="End (inclusive)" value={cfg.endDate} onChange={e => set('endDate', e.target.value)} /></div>
            <div><label className="text-xs text-slate-400 block mb-1">Date Filter Field</label><div className="flex gap-1"><button onClick={() => set('dateField', 'exit_time')} className={`flex-1 px-2 py-1.5 rounded text-xs font-medium ${cfg.dateField === 'exit_time' ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>Exit Time</button><button onClick={() => set('dateField', 'created_at')} className={`flex-1 px-2 py-1.5 rounded text-xs font-medium ${cfg.dateField === 'created_at' ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>Created At</button></div></div>
            <div><label className="text-xs text-slate-400 block mb-1">Symbol</label><div className="flex gap-1"><input type="text" value={cfg.symbols} onChange={e => set('symbols', e.target.value)} placeholder="BTC ETH..." className="flex-1 bg-slate-900 border border-slate-600 rounded-lg px-2 py-1.5 text-white text-sm" /><button onClick={() => set('symbolMode', cfg.symbolMode === 'include' ? 'exclude' : 'include')} className={`px-2 py-1 rounded-lg text-xs font-bold ${cfg.symbolMode === 'include' ? 'bg-emerald-600 text-white' : 'bg-red-600 text-white'}`}>{cfg.symbolMode === 'include' ? 'Incl' : 'Excl'}</button></div></div>
            <div className="grid grid-cols-2 gap-2">
              <div><label className="text-xs text-slate-400 block mb-1">Timeframe</label><div className="flex gap-1">{['15m', '1h', '4h'].map(tf => <button key={tf} onClick={() => toggleTF(tf)} className={`px-2 py-1 rounded text-xs font-medium ${cfg.timeframes.includes(tf) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{tf}</button>)}</div></div>
              <div><label className="text-xs text-slate-400 block mb-1">Engine</label><div className="flex gap-1"><select value={cfg.engineVersion} onChange={e => set('engineVersion', e.target.value)} className="flex-1 bg-slate-900 border border-slate-600 rounded-lg px-2 py-1.5 text-white text-xs"><option value="all">All</option>{engineVersions.map(v => <option key={v} value={v}>v{v}</option>)}</select><button onClick={() => set('engineMode', cfg.engineMode === 'only' ? 'newest' : cfg.engineMode === 'newest' ? 'older' : 'only')} className={`px-2 py-1 rounded-lg text-xs font-bold ${cfg.engineMode !== 'only' ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{cfg.engineMode === 'only' ? 'Only' : cfg.engineMode === 'newest' ? '+New' : '+Old'}</button></div></div>
            </div>
            <div className="grid grid-cols-2 gap-2"><Select label="Direction" value={cfg.direction} onChange={v => set('direction', v)} options={[{ value: 'all', label: 'All' }, { value: 'LONG', label: 'LONG' }, { value: 'SHORT', label: 'SHORT' }]} size="sm" /><Select label="Strategy" value={cfg.strategy} onChange={v => set('strategy', v)} options={[{ value: 'all', label: 'All' }, ...allStrategies.map(s => ({ value: s, label: s }))]} size="sm" /></div>
            <div><label className="text-xs text-slate-400 block mb-1">Pattern</label><div className="flex flex-wrap gap-1">{allPatterns.map(p => <button key={p} onClick={() => set('patterns', cfg.patterns.includes(p) ? cfg.patterns.filter(x => x !== p) : [...cfg.patterns, p])} className={`px-2 py-1 rounded text-xs ${cfg.patterns.includes(p) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{p}</button>)}</div></div>
            <div><label className="text-xs text-slate-400 block mb-1">Regime</label><div className="flex gap-1">{['BULL', 'BEAR', 'SIDEWAYS'].map(r => <button key={r} onClick={() => set('regimes', cfg.regimes.includes(r) ? cfg.regimes.filter(x => x !== r) : [...cfg.regimes, r])} className={`px-2 py-1 rounded text-xs ${cfg.regimes.includes(r) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{r}</button>)}</div></div>
          </div></Card>

          <Card padding="sm"><p className="text-xs font-semibold text-slate-500 uppercase mb-2">Indicator Index</p><div className="space-y-2">
            <div className="grid grid-cols-2 gap-2"><Input type="number" label="RSI Min" value={cfg.rsiMin} onChange={e => set('rsiMin', e.target.value)} /><Input type="number" label="RSI Max" value={cfg.rsiMax} onChange={e => set('rsiMax', e.target.value)} /></div>
            <Input type="number" label="Volume Ratio >=" value={cfg.volumeRatioMin} onChange={e => set('volumeRatioMin', e.target.value)} />
            <Input type="number" label="ATR Ratio >=" value={cfg.atrRatioMin} onChange={e => set('atrRatioMin', e.target.value)} />
            <div className="grid grid-cols-2 gap-2"><Input type="number" label="EMA Dist Min" value={cfg.emaDistMin} onChange={e => set('emaDistMin', e.target.value)} /><Input type="number" label="EMA Dist Max" value={cfg.emaDistMax} onChange={e => set('emaDistMax', e.target.value)} /></div>
          </div></Card>

          <Card padding="sm"><p className="text-xs font-semibold text-slate-500 uppercase mb-2">Score Index</p><div className="space-y-2">
            <div className="grid grid-cols-2 gap-2"><Input type="number" label="Score Min" value={cfg.scoreMin} onChange={e => set('scoreMin', e.target.value)} /><Input type="number" label="Score Max" value={cfg.scoreMax} onChange={e => set('scoreMax', e.target.value)} /></div>
            <div className="grid grid-cols-2 gap-2"><Input type="number" label="Trend >=" value={cfg.trendScoreMin} onChange={e => set('trendScoreMin', e.target.value)} /><Input type="number" label="Momentum >=" value={cfg.momentumScoreMin} onChange={e => set('momentumScoreMin', e.target.value)} /></div>
            <div className="grid grid-cols-2 gap-2"><Input type="number" label="Volume >=" value={cfg.volumeScoreMin} onChange={e => set('volumeScoreMin', e.target.value)} /><div className="grid grid-cols-2 gap-1"><Input type="number" label="MTF>=" value={cfg.mtfScoreMin} onChange={e => set('mtfScoreMin', e.target.value)} /><Input type="number" label="MTF<=" value={cfg.mtfScoreMax} onChange={e => set('mtfScoreMax', e.target.value)} /></div></div>
          </div></Card>

          <Card padding="sm"><p className="text-xs font-semibold text-slate-500 uppercase mb-2">RR Simulation</p><div className="space-y-2">
            <Input type="number" label="RR Ratio (e.g. 1.5 = 1:1.5)" value={cfg.rrOverride} onChange={e => set('rrOverride', e.target.value)} placeholder="default 1:2" />
            <div className="grid grid-cols-2 gap-2"><Input type="number" label="SL (% from entry)" value={cfg.slPct} onChange={e => set('slPct', e.target.value)} placeholder="e.g. 2" /><Input type="number" label="TP (% from entry)" value={cfg.tpPct} onChange={e => set('tpPct', e.target.value)} placeholder="e.g. 4" /></div>
            <p className="text-xs text-slate-600">SL/TP overrides RR if both set. Empty = original.</p>
            <div className="pt-1 border-t border-slate-700">
              <div className="flex items-center justify-between">
                <div><span className="text-xs text-slate-400">Reverse Direction</span><p className="text-[10px] text-slate-600">LONG/SHORT, replayed on the same 1m candles.</p></div>
                <button onClick={() => set('reverseDirection', !cfg.reverseDirection)} className={`relative w-12 h-6 rounded-full transition-colors ${cfg.reverseDirection ? 'bg-orange-600' : 'bg-slate-700'}`}><div className={`absolute top-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow ${cfg.reverseDirection ? 'translate-x-6' : 'translate-x-0.5'}`} /></button>
              </div>
              {cfg.reverseDirection && <p className="text-[10px] text-orange-400 mt-1">⚠ Entry is unchanged; SL/TP are recalculated for the reversed side.</p>}
            </div>
          </div></Card>
        </div>

        <div className="flex-1 min-w-0 space-y-6">
          {running && (
          <Card className="h-48 flex items-center justify-center">
            <div className="text-center w-full max-w-md">
              <div className="w-12 h-12 relative mx-auto mb-3">
                <div className="absolute inset-0 rounded-full border-4 border-indigo-500/20" />
                <div className="absolute inset-0 rounded-full border-4 border-indigo-500 border-t-transparent animate-spin" />
              </div>
              {fetchProgress >= (
                <>
                  <p className="text-slate-300 mb-2">
                    Fetching klines from Binance... {fetchProgress.done}/{fetchProgress.total} symbols
                  </p>
                  <div className="w-full bg-slate-800 rounded-full h-2 overflow-hidden">
                    <div
                      className="bg-indigo-500 h-full transition-all duration-300"
                      style={{ width: `${(fetchProgress.done / fetchProgress.total) * 100}%` }}
                    />
                  </div>
                </>
              ) : (
                <p className="text-slate-400">Processing...</p>
              )}
            </div>
          </Card>
        )}
          {!running && results && (
            <>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                <Card className="p-3 text-center"><p className="text-xs text-slate-400">Final NAV</p><p className={`text-lg font-bold ${clr(results.pnl)}`}>${$(results.nav)}</p></Card>
                <Card className="p-3 text-center"><p className="text-xs text-slate-400">Counted Trades</p><p className="text-lg font-bold text-white">{results.counted}</p></Card>
                <Card className="p-3 text-center"><p className="text-xs text-slate-400">Win Rate</p><p className={`text-lg font-bold ${results.wr >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{results.wr.toFixed(1)}%</p></Card>
                <Card className="p-3 text-center"><p className="text-xs text-slate-400">Max DD</p><p className="text-lg font-bold text-red-400">{results.maxDD.toFixed(2)}%</p></Card>
                <Card className="p-3 text-center"><p className="text-xs text-slate-400">Not Count</p><p className="text-lg font-bold text-orange-400">{results.notCount}</p></Card>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Card><CardHeader title="Performance" /><div className="space-y-3">
                  {[['Total Trades', String(results.counted)], ['Profit Factor', results.pf === Infinity ? 'Infinity' : results.pf.toFixed(2)], ['Expectancy', `${results.exp.toFixed(2)}%`], ['Sharpe', results.sharpe.toFixed(2)], ['Wins / Losses', `${results.wins} / ${results.losses}`], ['Avg P / Avg L', `${results.avgP.toFixed(2)}% / ${results.avgL.toFixed(2)}%`], ['Long / Short WR', `${results.longWR.toFixed(1)}% (${results.longTotal}) / ${results.shortWR.toFixed(1)}% (${results.shortTotal})`]].map(([l, v]) => <div key={l} className="flex justify-between py-2 border-b border-slate-700 last:border-0"><span className="text-slate-400">{l}</span><span className="font-bold text-white">{v}</span></div>)}
                </div></Card>
                <Card><CardHeader title="Risk" /><div className="space-y-3">
                  {[['Final Equity', `$${$(results.nav)}`, clr(results.pnl)], ['Total P&L', `${results.pnl >= 0 ? '+' : ''}$${$(results.pnl)}`, clr(results.pnl)], ['Peak NAV', `$${$(results.peakNav)}`, 'text-emerald-400'], ['Trough NAV', `$${$(results.troughNav)}`, 'text-red-400'], ['Max Gain', `${results.maxGain.toFixed(2)}%`, 'text-emerald-400'], ['Max DD', `${results.maxDD.toFixed(2)}%`, 'text-red-400'], ['Max Win / Loss Streak', `${results.maxWinStreak} / ${results.maxLossStreak}`, 'text-white'], ['Avg Duration', results.avgDurStr, 'text-white']].map(([l, v, c]) => <div key={l} className="flex justify-between py-2 border-b border-slate-700 last:border-0"><span className="text-slate-400">{l}</span><span className={`font-bold ${c}`}>{v}</span></div>)}
                </div></Card>
              </div>

              <Card><CardHeader title="Equity Curve" /><ResponsiveContainer width="100%" height={280}><LineChart data={results.curve}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="time" stroke="#64748b" fontSize={10} interval="preserveStartEnd" /><YAxis stroke="#64748b" fontSize={10} tickFormatter={v => `$${(v / 1000).toFixed(1)}k`} /><Tooltip content={<ChartTip />} /><Line type="monotone" dataKey="equity" name="Equity" stroke="#6366f1" strokeWidth={2} dot={false} activeDot={{ r: 4, fill: '#6366f1', stroke: '#fff', strokeWidth: 2 }} /></LineChart></ResponsiveContainer></Card>
              <Card><CardHeader title="Drawdown" /><ResponsiveContainer width="100%" height={160}><AreaChart data={results.curve}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="time" stroke="#64748b" fontSize={10} interval="preserveStartEnd" /><YAxis stroke="#64748b" fontSize={10} tickFormatter={v => `-${v}%`} reversed /><Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} formatter={v => [`-${Number(v).toFixed(2)}%`]} /><Area type="monotone" dataKey="dd" name="Drawdown" stroke="#ef4444" fill="#ef4444" fillOpacity={0.2} /></AreaChart></ResponsiveContainer></Card>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                <Card><CardHeader title="Regime Breakdown" /><DataTable columns={[{ key: 'regime', header: 'Regime', render: v => <StatusBadge status={v} /> }, { key: 'trades', header: 'Trades', sortable: true, align: 'right' }, { key: 'winrate', header: 'WR', sortable: true, align: 'right', render: v => <span className={v >= 50 ? 'text-emerald-400' : 'text-red-400'}>{v.toFixed(1)}%</span> }, { key: 'profitFactor', header: 'PF', sortable: true, align: 'right', render: v => v === Infinity ? 'Infinity' : v.toFixed(2) }]} data={regimeData} pageSize={5} /></Card>
                <Card><CardHeader title="Feature: RSI" /><DataTable columns={[{ key: 'range', header: 'RSI Range' }, { key: 'trades', header: 'Trades', sortable: true, align: 'right' }, { key: 'winrate', header: 'WR', sortable: true, align: 'right', render: v => <span className={v >= 50 ? 'text-emerald-400' : 'text-red-400'}>{v.toFixed(1)}%</span> }, { key: 'pf', header: 'PF', sortable: true, align: 'right', render: v => v === Infinity ? 'Infinity' : v.toFixed(2) }, { key: 'expectancy', header: 'Exp', sortable: true, align: 'right', render: v => <span className={v >= 0 ? 'text-emerald-400' : 'text-red-400'}>{v.toFixed(2)}%</span> }]} data={rsiBuckets} pageSize={10} /></Card>
              </div>

              <Card><CardHeader title="Pattern x Timeframe Heatmap" />{patternHM.length > 0 ? <Heatmap data={patternHM} xLabel="TF" yLabel="Pattern" valueLabel="WR%" colorScale="green-red" showValues /> : <div className="h-48 flex items-center justify-center text-slate-500">No data</div>}</Card>
              <Card><CardHeader title="Volume Ratio x RSI Heatmap" subtitle="Profit Factor" />{volRsiHM.length > 0 ? <Heatmap data={volRsiHM} xLabel="Volume Ratio" yLabel="RSI" valueLabel="PF" colorScale="green-red" showValues /> : <div className="h-48 flex items-center justify-center text-slate-500">No data</div>}</Card>
              <Card><CardHeader title="Score Distribution" subtitle="Wins vs Losses by score" />{scoreDist.length > 0 ? <ResponsiveContainer width="100%" height={220}><ReBarChart data={scoreDist}><CartesianGrid strokeDasharray="3 3" stroke="#334155" /><XAxis dataKey="range" stroke="#64748b" fontSize={12} /><YAxis stroke="#64748b" fontSize={12} /><Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }} /><Legend /><Bar dataKey="wins" name="Wins" fill="#10b981" radius={[4, 4, 0, 0]} /><Bar dataKey="losses" name="Losses" fill="#ef4444" radius={[4, 4, 0, 0]} /></ReBarChart></ResponsiveContainer> : <div className="h-48 flex items-center justify-center text-slate-500">No data</div>}</Card>

              <Card>
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-4">
                  <div><h3 className="text-lg font-semibold text-white">Simulated Trades</h3><p className="text-sm text-slate-400">{trades.length} trades{results.notCount > 0 ? ` (${results.notCount} not counted)` : ''}</p></div>
                  <div className="flex flex-wrap gap-2">
                    <button onClick={() => { const streak = tradesDesc.map(t => t.sim_status === 'WIN' ? 'W' : t.sim_status === 'LOSS' ? 'L' : t.sim_status === 'NOT_COUNT' ? 'N' : '-').join(' '); navigator.clipboard.writeText(streak); alert(`Copied ${tradesDesc.length} simulated results`); }} className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg text-xs">📋 Streak</button>
                    <button onClick={() => {
                      const headers = ['#','Symbol','Dir','TF','Pattern','Entry','SL_Sim','TP_Sim','PnL_Sim','Status_Orig','Status_Sim','Score','Regime','Opened','Closed'];
                      const rows = tradesDesc.map((t, i) => [i+1, t.symbol, t.direction, t.timeframe, t.pattern, t.entry_price, t.sim_sl, t.sim_tp, t.sim_result, t.status, t.sim_status, t.score, t.regime, t.entry_time || t.created_at || t.candle_time, t.exit_time].join(','));
                      const csv = [headers.join(','), ...rows].join('\n');
                      const blob = new Blob([csv], { type: 'text/csv' });
                      const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = `simulated_trades_${Date.now()}.csv`; a.click(); URL.revokeObjectURL(url);
                    }} className="px-3 py-1.5 bg-emerald-700 hover:bg-emerald-600 text-white rounded-lg text-xs">📥 CSV</button>
                  </div>
                </div>
                <DataTable
                    columns={tradeColumns}
                    data={tradesDesc.map((t, i) => ({ ...t, __idx: i + 1 }))}
                    pageSize={20}
                    onRowClick={(row) => setSelectedTrade(row)}
                  />
              </Card>

              {(cfg.slPct || cfg.tpPct || cfg.rrOverride) && trades.some(t => t._debug_sl_pct != null) && <DebugPanel trades={tradesDesc} />}
            </>
          )}
        </div>
      </div>
      {selectedTrade && (
        <TradeDetailModal
          trade={selectedTrade}
          klines={klineCache.get(selectedTrade.symbol) || []}
          onClose={() => setSelectedTrade(null)}
        />
      )}
    </div>
  );
}
