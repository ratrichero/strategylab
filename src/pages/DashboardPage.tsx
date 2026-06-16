// @ts-nocheck
/* eslint-disable */
import { useEffect, useState, useMemo } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Select } from '../components/ui/Select';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { DataTable } from '../components/ui/Table';
import { DirectionBadge, PercentChangeBadge, StatusBadge } from '../components/ui/Badge';
import { Heatmap } from '../components/charts/Heatmap';
import { Zap, Clock, Filter, RefreshCw, Loader2, Target, BarChart3, CalendarCheck } from 'lucide-react';
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { parseUtcMs, utcToVN, getTodayVN, normalizeSignalDates } from '../utils/time';

const API = '/api';
async function fetchAPI(ep) { const r = await fetch(`${API}${ep}`); if (!r.ok) throw new Error(`${r.status}`); return r.json(); }
function ScoreCell({ value }) { const v = Number(value) || 0; return <span className={`font-mono text-sm ${v >= 8 ? 'text-emerald-400' : v >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>{v.toFixed(2)}</span>; }
const fetchBinancePrices = async () => { try { const r = await fetch('https://fapi.binance.com/fapi/v1/ticker/price'); const d = await r.json(); const p = {}; d.forEach((i) => { p[i.symbol] = parseFloat(i.price); }); return p; } catch { return {}; } };


function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl text-sm">
      <p className="text-slate-400 mb-2 font-medium">{label}</p>
      {payload.map((entry, i) => (
        <div key={i} className="flex items-center gap-2 mb-1">
          <div className="w-3 h-3 rounded-full" style={{ backgroundColor: entry.color }} />
          <span className="text-slate-300">{entry.name}:</span>
          <span className="font-bold text-white">
            {entry.name.includes('DD') ? `-${Number(entry.value).toFixed(2)}%` : `$${Number(entry.value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`}
          </span>
        </div>
      ))}
    </div>
  );
}

export function Dashboard() {
  const INIT_CAP = 10000;
  const todayVN = getTodayVN();

  const [allSignals, setAllSignals] = useState([]);
  const [pendingSignals, setPendingSignals] = useState([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [maxOpen, setMaxOpen] = useState(50);
  const [engineVersions, setEngineVersions] = useState([]);
  const [strategies, setStrategies] = useState([]);
  const [binancePrices, setBinancePrices] = useState({});
  const [priceFlash, setPriceFlash] = useState({});
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState('');


  const [filters, setFilters] = useState({ startDate: todayVN, endDate: todayVN, timeframe: 'all', engineVersion: 'all', scoreMin: '', scoreMax: '', strategy: 'all', fixedSize: 1000 });
  const [appliedFilters, setAppliedFilters] = useState(filters);

  const setFilterInstant = (key, value) => {
    const next = { ...filters, [key]: value };
    setFilters(next);
    if (['timeframe', 'engineVersion', 'strategy'].includes(key)) {
      setAppliedFilters(prev => ({ ...prev, [key]: value }));
    }
  };

  const setScoreFilter = (preset) => {
    let min = '', max = '';
    if (preset === '6-7') { min = '6'; max = '7'; }
    else if (preset === '7-8') { min = '7'; max = '8'; }
    else if (preset === '8-9') { min = '8'; max = '9'; }
    else if (preset === '9-10') { min = '9'; max = '10'; }
    const next = { ...filters, scoreMin: min, scoreMax: max };
    setFilters(next);
    setAppliedFilters(prev => ({ ...prev, scoreMin: min, scoreMax: max }));
  };

  const getScorePreset = () => {
    const { scoreMin, scoreMax } = filters;
    if (scoreMin === '6' && scoreMax === '7') return '6-7';
    if (scoreMin === '7' && scoreMax === '8') return '7-8';
    if (scoreMin === '8' && scoreMax === '9') return '8-9';
    if (scoreMin === '9' && scoreMax === '10') return '9-10';
    return 'all';
  };

  const handleApply = () => setAppliedFilters({ ...filters });

  // ========== LOAD ==========
  useEffect(() => {
    (async () => {
      setLoading(true); setApiError('');
      try {
        console.log('[Dashboard] todayVN:', todayVN);
        const [allSigs, pending, vers, prices, appCfg] = await Promise.all([
          fetchAPI('/signals?limit=2000').catch(e => { setApiError(p => p + ' signals:' + e.message); return { data: [] }; }),
          fetchAPI('/pending-signals?status=WAIT&limit=200').catch(() => ({ data: [], total: 0 })),
          fetchAPI('/engine/versions').catch(() => []),
          fetchBinancePrices(),
          fetchAPI('/app-config').catch(() => ({})),
        ]);
        const signals = (allSigs.data || []).map(normalizeSignalDates);
        console.log('[Dashboard] all:', signals.length);

        setAllSignals(signals);
        setPendingSignals((pending.data || []).map(normalizeSignalDates));
        setPendingCount(pending.total || 0);
        setEngineVersions(vers.map(v => String(v.engine_version)).filter(Boolean).sort().reverse());
        setStrategies(Array.from(new Set(signals.map(s => s.strategy_name).filter(Boolean))).sort());
        setBinancePrices(prices);
        setMaxOpen(parseInt(appCfg['MAX_OPEN_TRADES'] || '10'));
      } catch (e) { console.error(e); setApiError(String(e)); }
      finally { setLoading(false); }
    })();
  }, [todayVN]);

  // Debug log when applied VN date range changes (all filtering is local)
  useEffect(() => {
    console.log('[Dashboard] Filter applied:', appliedFilters.startDate || '(all)', '→', appliedFilters.endDate || '(all)', '| allSignals:', allSignals.length);
  }, [appliedFilters.startDate, appliedFilters.endDate, allSignals]);

  // Auto-refresh prices
  useEffect(() => {
    const iv = setInterval(async () => {
      const np = await fetchBinancePrices();
      setBinancePrices(prev => {
        const fl = {};
        Object.keys(np).forEach(s => { if (prev[s] && np[s] !== prev[s]) fl[s] = np[s] > prev[s] ? 'up' : 'down'; });
        setPriceFlash(fl);
        setTimeout(() => setPriceFlash({}), 600);
        return np;
      });
    }, 10000);
    return () => clearInterval(iv);
  }, []);

  // ========== DATA SPLITS ==========
  const allOpen = useMemo(() => allSignals.filter(s => s.status === 'OPEN').sort((a, b) => new Date(b.candle_time || 0).getTime() - new Date(a.candle_time || 0).getTime()), [allSignals]);
  const allClosed = useMemo(() => allSignals.filter(s => s.status === 'WIN' || s.status === 'LOSS').sort((a, b) => parseUtcMs(b.exit_time || '') - parseUtcMs(a.exit_time || '')), [allSignals]);

  // VN date range filtering is done locally from allSignals (single source of truth)
  const metricClosed = useMemo(() => {
    const VN_MS = 7 * 3600 * 1000;
    const startVN = appliedFilters.startDate;
    const endVN = appliedFilters.endDate;
    return allSignals.filter(s => {
      if (s.status !== 'WIN' && s.status !== 'LOSS') return false;
      if (!s.exit_time) return false;
      const exitMs = parseUtcMs(s.exit_time);
      if (!exitMs) return false;
      const vnDate = new Date(exitMs + VN_MS);
      const vnDateStr = `${vnDate.getUTCFullYear()}-${String(vnDate.getUTCMonth()+1).padStart(2,'0')}-${String(vnDate.getUTCDate()).padStart(2,'0')}`;
      if (startVN && vnDateStr < startVN) return false;
      if (endVN && vnDateStr > endVN) return false;
      return true;
    }).sort((a, b) => parseUtcMs(b.exit_time || '') - parseUtcMs(a.exit_time || ''));
  }, [allSignals, appliedFilters.startDate, appliedFilters.endDate]);

  // Date filter is already done server-side. Client-side only: timeframe, engine, score, strategy.
  const filteredClosed = useMemo(() => {
    const af = appliedFilters;
    return metricClosed.filter(s => {
      if (af.timeframe !== 'all' && s.timeframe !== af.timeframe) return false;
      if (af.engineVersion !== 'all' && String(s.engine_version) !== af.engineVersion) return false;
      const rawScore = Number(s.score) || 0;
      if (af.scoreMin && rawScore < Number(af.scoreMin)) return false;
      if (af.scoreMax && rawScore >= Number(af.scoreMax)) return false;
      if (af.strategy !== 'all' && s.strategy_name !== af.strategy) return false;
      return true;
    });
  }, [metricClosed, appliedFilters]);

  // ========== TRADE-LEVEL METRICS ==========
  const filteredTradesCount = filteredClosed.length;
  const totalTradesAllTime = allClosed.length;
  const tradesTodayCount = useMemo(() => {
    const VN_MS = 7 * 3600 * 1000;
    return allClosed.filter(s => {
      if (!s.exit_time) return false;
      const exitMs = parseUtcMs(s.exit_time);
      if (!exitMs) return false;
      const vnDate = new Date(exitMs + VN_MS);
      const vnDateStr = `${vnDate.getUTCFullYear()}-${String(vnDate.getUTCMonth()+1).padStart(2,'0')}-${String(vnDate.getUTCDate()).padStart(2,'0')}`;
      return vnDateStr === todayVN;
    }).length;
  }, [allClosed, todayVN]);

  const wins = filteredClosed.filter(s => s.status === 'WIN').length;
  const winRate = filteredTradesCount > 0 ? (wins / filteredTradesCount) * 100 : 0;

  const profitFactor = useMemo(() => {
    const gp = filteredClosed.filter(s => (s.result_percent || 0) > 0).reduce((a, s) => a + (s.result_percent || 0), 0);
    const gl = Math.abs(filteredClosed.filter(s => (s.result_percent || 0) < 0).reduce((a, s) => a + (s.result_percent || 0), 0));
    return gl > 0 ? gp / gl : gp > 0 ? Infinity : 0;
  }, [filteredClosed]);

  const expectancy = useMemo(() => {
    if (!filteredTradesCount) return 0;
    const wA = filteredClosed.filter(s => (s.result_percent || 0) > 0);
    const lA = filteredClosed.filter(s => (s.result_percent || 0) < 0);
    const avgW = wA.length ? wA.reduce((a, s) => a + (s.result_percent || 0), 0) / wA.length : 0;
    const avgL = lA.length ? Math.abs(lA.reduce((a, s) => a + (s.result_percent || 0), 0) / lA.length) : 0;
    return (wins / filteredTradesCount) * avgW - ((filteredTradesCount - wins) / filteredTradesCount) * avgL;
  }, [filteredClosed, filteredTradesCount, wins]);

  const tradeSharpe = useMemo(() => {
    const r = filteredClosed.map(s => s.result_percent || 0);
    if (r.length < 2) return 0;
    const avg = r.reduce((a, b) => a + b, 0) / r.length;
    const std = Math.sqrt(r.reduce((s, x) => s + (x - avg) ** 2, 0) / r.length);
    return std > 0.0001 ? avg / std : 0;
  }, [filteredClosed]);

  const streaks = useMemo(() => {
    const calc = (arr) => {
      let mw = 0, ml = 0, cw = 0, cl = 0;
      arr.forEach(s => {
        if (s.status === 'WIN') { cw++; cl = 0; mw = Math.max(mw, cw); }
        else { cl++; cw = 0; ml = Math.max(ml, cl); }
      });
      return { maxWin: mw, maxLoss: ml };
    };
    return {
      candle: calc([...filteredClosed].sort((a, b) => new Date(a.candle_time || 0).getTime() - new Date(b.candle_time || 0).getTime())),
      exit: calc([...filteredClosed].sort((a, b) => new Date(a.exit_time || 0).getTime() - new Date(b.exit_time || 0).getTime())),
    };
  }, [filteredClosed]);

  const longShortWR = useMemo(() => {
    const longs = filteredClosed.filter(s => s.direction === 'LONG');
    const shorts = filteredClosed.filter(s => s.direction === 'SHORT');
    const longWins = longs.filter(s => s.status === 'WIN').length;
    const shortWins = shorts.filter(s => s.status === 'WIN').length;
    return {
      longWR: longs.length > 0 ? (longWins / longs.length) * 100 : 0, longTotal: longs.length,
      shortWR: shorts.length > 0 ? (shortWins / shorts.length) * 100 : 0, shortTotal: shorts.length,
    };
  }, [filteredClosed]);

  const avgDuration = useMemo(() => {
    const durations = filteredClosed.filter(s => s.candle_time && s.exit_time).map(s => parseUtcMs(s.exit_time) - parseUtcMs(s.candle_time)).filter(d => d > 0);
    if (!durations.length) return '-';
    const avgMs = durations.reduce((a, b) => a + b, 0) / durations.length;
    const mins = Math.round(avgMs / 60000);
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60); const remainMins = mins % 60;
    if (hrs < 24) return `${hrs}h ${remainMins}m`;
    const days = Math.floor(hrs / 24); const remainHrs = hrs % 24;
    return `${days}d ${remainHrs}h`;
  }, [filteredClosed]);

  // ========== PORTFOLIO: COMPOUNDING ==========
  const pComp = useMemo(() => {
    const fsInput = appliedFilters.fixedSize || 1000;
    const sorted = [...filteredClosed].sort((a, b) => parseUtcMs(a.exit_time || '') - parseUtcMs(b.exit_time || ''));
    let nav = INIT_CAP, peakNav = nav, troughNav = nav, maxDD = 0, maxGain = 0;
    const curve = [];
    const pnlList = [];
    sorted.forEach(s => {
      const rp = s.result_percent || 0;
      const dynamicPosSize = fsInput * (nav / INIT_CAP);
      const pnl = dynamicPosSize * (rp / 100);
      nav += pnl; pnlList.push(pnl);
      peakNav = Math.max(peakNav, nav); troughNav = Math.min(troughNav, nav);
      const dd = (peakNav - nav) / peakNav * 100;
      maxDD = Math.max(maxDD, dd); maxGain = Math.max(maxGain, (nav - INIT_CAP) / INIT_CAP * 100);
      curve.push({ time: s.exit_time ? utcToVN(s.exit_time) : '', nav: Math.round(nav * 100) / 100, dd: Math.round(dd * 100) / 100, symbol: s.symbol, pnl: Math.round(pnl * 100) / 100, rp });
    });
    const ret = ((nav - INIT_CAP) / INIT_CAP) * 100;
    const pctReturns = pnlList.map(p => (p / INIT_CAP) * 100);
    const avg = pctReturns.length ? pctReturns.reduce((a, b) => a + b, 0) / pctReturns.length : 0;
    const std = pctReturns.length ? Math.sqrt(pctReturns.reduce((s, x) => s + (x - avg) ** 2, 0) / pctReturns.length) : 0;
    return { nav, pnl: nav - INIT_CAP, ret, maxDD, maxGain, peakNav, troughNav, sharpe: std > 0 ? avg / std : 0, calmar: maxDD > 0 ? ret / maxDD : 0, curve };
  }, [filteredClosed, appliedFilters.fixedSize]);

  // ========== PORTFOLIO: FIXED SIZE ==========
  const pFixed = useMemo(() => {
    const fs = appliedFilters.fixedSize || 1000;
    const sorted = [...filteredClosed].sort((a, b) => parseUtcMs(a.exit_time || '') - parseUtcMs(b.exit_time || ''));
    let nav = INIT_CAP, peakNav = nav, troughNav = nav, maxDD = 0, maxGain = 0;
    const curve = [];
    const pnlList = [];
    sorted.forEach(s => {
      const rp = s.result_percent || 0;
      const pnl = fs * (rp / 100);
      nav += pnl; pnlList.push(pnl);
      peakNav = Math.max(peakNav, nav); troughNav = Math.min(troughNav, nav);
      const dd = (peakNav - nav) / peakNav * 100;
      maxDD = Math.max(maxDD, dd); maxGain = Math.max(maxGain, (nav - INIT_CAP) / INIT_CAP * 100);
      curve.push({ time: s.exit_time ? utcToVN(s.exit_time) : '', nav: Math.round(nav * 100) / 100, dd: Math.round(dd * 100) / 100, symbol: s.symbol, pnl: Math.round(pnl * 100) / 100, rp });
    });
    const ret = ((nav - INIT_CAP) / INIT_CAP) * 100;
    const pctReturns = pnlList.map(p => (p / INIT_CAP) * 100);
    const avg = pctReturns.length ? pctReturns.reduce((a, b) => a + b, 0) / pctReturns.length : 0;
    const std = pctReturns.length ? Math.sqrt(pctReturns.reduce((s, x) => s + (x - avg) ** 2, 0) / pctReturns.length) : 0;
    return { nav, pnl: nav - INIT_CAP, ret, maxDD, maxGain, peakNav, troughNav, sharpe: std > 0 ? avg / std : 0, calmar: maxDD > 0 ? ret / maxDD : 0, curve };
  }, [filteredClosed, appliedFilters.fixedSize]);

  // ========== REGIME ==========
  const regimeBreakdown = useMemo(() => {
    const reg = {};
    filteredClosed.forEach(s => {
      const r = s.regime || 'UNKNOWN';
      if (!reg[r]) reg[r] = { total: 0, wins: 0, returns: [] };
      reg[r].total++; if (s.status === 'WIN') reg[r].wins++;
      reg[r].returns.push(s.result_percent || 0);
    });
    return Object.entries(reg).map(([regime, d]) => {
      const wr = d.total > 0 ? (d.wins / d.total) * 100 : 0;
      const wA = d.returns.filter(r => r > 0), lA = d.returns.filter(r => r < 0);
      const avgW = wA.length ? wA.reduce((a, b) => a + b, 0) / wA.length : 0;
      const avgL = lA.length ? Math.abs(lA.reduce((a, b) => a + b, 0) / lA.length) : 0;
      const gp = wA.reduce((a, b) => a + b, 0), gl = Math.abs(lA.reduce((a, b) => a + b, 0));
      return { regime, trades: d.total, wins: d.wins, winrate: wr, expectancy: (wr / 100) * avgW - ((1 - wr / 100) * avgL), profitFactor: gl > 0 ? gp / gl : gp > 0 ? Infinity : 0, totalReturn: d.returns.reduce((a, b) => a + b, 0) };
    }).sort((a, b) => b.trades - a.trades);
  }, [filteredClosed]);

  // ========== HEATMAP (UNFILTERED) ==========
  const heatmapData = useMemo(() => {
    const data = [], patterns = new Set();
    const g = {};
    allClosed.forEach(s => {
      if (!s.pattern) return; patterns.add(s.pattern);
      if (!g[s.pattern]) g[s.pattern] = { All: { w: 0, t: 0 } };
      if (!g[s.pattern][s.timeframe]) g[s.pattern][s.timeframe] = { w: 0, t: 0 };
      g[s.pattern][s.timeframe].t++; g[s.pattern].All.t++;
      if (s.status === 'WIN') { g[s.pattern][s.timeframe].w++; g[s.pattern].All.w++; }
    });
    patterns.forEach(p => ['15m', '1h', '4h', 'All'].forEach(tf => {
      const st = g[p]?.[tf] || { w: 0, t: 0 };
      data.push({ x: tf, y: p, value: st.t > 0 ? (st.w / st.t) * 100 : 50, count: st.t });
    }));
    return data;
  }, [allClosed]);

  // ========== ACTIVE WITH PRICE ==========
  const activeWithPrice = useMemo(() => allOpen.map(s => {
    const cp = binancePrices[s.symbol] || 0;
    const pnl = cp && s.entry_price ? (s.direction === 'LONG' ? ((cp - s.entry_price) / s.entry_price) : ((s.entry_price - cp) / s.entry_price)) * 100 : 0;
    return { ...s, currentPrice: cp, pnl, flash: priceFlash[s.symbol] };
  }), [allOpen, binancePrices, priceFlash]);

  // ========== PENDING WITH PRICE ==========
  const pendingWithPrice = useMemo(() => pendingSignals.map(s => {
    const cp = binancePrices[s.symbol] || 0;
    return { ...s, currentPrice: cp, flash: priceFlash[s.symbol] };
  }), [pendingSignals, binancePrices, priceFlash]);

  // ========== EQUITY CURVE COMBINED ==========
  const eqCurve = useMemo(() => {
    const n = Math.max(pComp.curve.length, pFixed.curve.length);
    return Array.from({ length: n }, (_, i) => ({
      time: pComp.curve[i]?.time || pFixed.curve[i]?.time || '',
      compounding: pComp.curve[i]?.nav ?? null,
      fixed: pFixed.curve[i]?.nav ?? null,
      ddComp: pComp.curve[i]?.dd || 0,
      ddFixed: pFixed.curve[i]?.dd || 0,
    }));
  }, [pComp.curve, pFixed.curve]);

  // ========== TABLE COLUMNS ==========
  const activeColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: v => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'entry_price', header: 'Entry', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'currentPrice', header: 'Current', render: (v, row) => (
      <span className={`font-mono transition-all duration-300 ${row.flash === 'up' ? 'text-emerald-400 bg-emerald-500/20 px-1 rounded' : row.flash === 'down' ? 'text-red-400 bg-red-500/20 px-1 rounded' : 'text-white'}`}>
        {v?.toFixed(v > 100 ? 2 : 4) || '-'}
      </span>
    )},
    { key: 'stop_loss', header: 'SL', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'take_profit', header: 'TP', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'pnl', header: 'P&L', sortable: true, render: v => <PercentChangeBadge value={v || 0} /> },
    { key: 'regime', header: 'Regime', sortable: true, render: v => <StatusBadge status={v || 'N/A'} /> },
    { key: 'score', header: 'Score', sortable: true, render: v => <ScoreCell value={v} /> },
    { key: 'candle_time', header: 'Opened', sortable: true, render: v => utcToVN(v) },
  ];

  const pendingColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: v => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'trigger_price', header: 'Entry', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'currentPrice', header: 'Current', render: (v, row) => (
      <span className={`font-mono transition-all duration-300 ${row.flash === 'up' ? 'text-emerald-400 bg-emerald-500/20 px-1 rounded' : row.flash === 'down' ? 'text-red-400 bg-red-500/20 px-1 rounded' : 'text-white'}`}>
        {v?.toFixed(v > 100 ? 2 : 4) || '-'}
      </span>
    )},
    { key: 'stop_loss', header: 'SL', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'take_profit', header: 'TP', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'regime', header: 'Regime', sortable: true, render: v => <StatusBadge status={v || 'N/A'} /> },
    { key: 'signal_score', header: 'Score', sortable: true, render: v => <ScoreCell value={v} /> },
    { key: 'created_at', header: 'Opened', sortable: true, render: v => utcToVN(v) },
  ];

  const recentColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: v => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'entry_price', header: 'Entry', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'exit_price', header: 'Exit', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'stop_loss', header: 'SL', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'take_profit', header: 'TP', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'result_percent', header: 'P&L', sortable: true, render: v => <PercentChangeBadge value={v || 0} /> },
    { key: 'status', header: 'Status', sortable: true, render: v => <StatusBadge status={v || 'N/A'} /> },
    { key: 'regime', header: 'Regime', sortable: true, render: v => <StatusBadge status={v || 'N/A'} /> },
    { key: 'score', header: 'Score', sortable: true, render: v => <ScoreCell value={v} /> },
    { key: 'candle_time', header: 'Opened', sortable: true, render: v => utcToVN(v) },
    { key: 'exit_time', header: 'Closed', sortable: true, render: v => utcToVN(v) },
  ];

  const regimeColumns = [
    { key: 'regime', header: 'Regime', sortable: true, render: v => <StatusBadge status={v} /> },
    { key: 'trades', header: 'Trades', sortable: true, align: 'right' },
    { key: 'wins', header: 'Wins', sortable: true, align: 'right' },
    { key: 'winrate', header: 'Win Rate', sortable: true, align: 'right', render: v => <span className={v >= 50 ? 'text-emerald-400' : 'text-red-400'}>{v.toFixed(1)}%</span> },
    { key: 'expectancy', header: 'Expectancy', sortable: true, align: 'right', render: v => <span className={v >= 0 ? 'text-emerald-400' : 'text-red-400'}>{v.toFixed(2)}</span> },
    { key: 'profitFactor', header: 'PF', sortable: true, align: 'right', render: v => v === Infinity ? '∞' : v.toFixed(2) },
    { key: 'totalReturn', header: 'Total Return', sortable: true, render: v => <PercentChangeBadge value={v} /> },
  ];

  const $ = v => v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const clr = v => v >= 0 ? 'text-emerald-400' : 'text-red-400';

  // ========== RENDER ==========
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Performance Overview</h2>
          <p className="text-slate-400 mt-1">{loading ? 'Loading data...' : `Strategy analytics — ${appliedFilters.startDate} → ${appliedFilters.endDate}`}</p>
        </div>
        <Button variant="ghost" icon={loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} onClick={() => window.location.reload()}>Refresh</Button>
      </div>

      {apiError && <div className="px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">⚠️ {apiError}</div>}

      {/* OVERVIEW KPI */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Card className="flex items-center gap-4"><div className="p-3 bg-indigo-500/20 rounded-xl"><BarChart3 className="w-6 h-6 text-indigo-400" /></div><div><p className="text-sm text-slate-400">Total Trades</p><p className="text-2xl font-bold text-white">{filteredTradesCount}</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-cyan-500/20 rounded-xl"><CalendarCheck className="w-6 h-6 text-cyan-400" /></div><div><p className="text-sm text-slate-400">Trades Today</p><p className="text-2xl font-bold text-white">{tradesTodayCount}</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-emerald-500/20 rounded-xl"><Target className="w-6 h-6 text-emerald-400" /></div><div><p className="text-sm text-slate-400">Win Rate</p><p className={`text-2xl font-bold ${winRate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{winRate.toFixed(1)}%</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-yellow-500/20 rounded-xl"><Zap className="w-6 h-6 text-yellow-400" /></div><div><p className="text-sm text-slate-400">Active Signals</p><p className="text-2xl font-bold text-white">{allOpen.length}</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-purple-500/20 rounded-xl"><Clock className="w-6 h-6 text-purple-400" /></div><div><p className="text-sm text-slate-400">Pending Signals</p><p className="text-2xl font-bold text-white">{pendingCount}</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-orange-500/20 rounded-xl"><Filter className="w-6 h-6 text-orange-400" /></div><div><p className="text-sm text-slate-400">Open / Max</p><p className="text-2xl font-bold text-white">{allOpen.length} / {maxOpen}</p></div></Card>
      </div>

      {/* FILTERS */}
      <Card>
        <div className="flex items-center gap-2 mb-4"><Filter className="w-5 h-5 text-slate-400" /><h3 className="font-semibold text-white">Filters</h3><span className="text-xs text-slate-500 ml-2">→ Metrics, Portfolio, Charts, Regime</span></div>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
          <Input type="date" label="From" value={filters.startDate} onChange={e => setFilters({ ...filters, startDate: e.target.value })} />
          <Input type="date" label="To" value={filters.endDate} onChange={e => setFilters({ ...filters, endDate: e.target.value })} />
          <Select label="Timeframe" value={filters.timeframe} onChange={v => setFilterInstant('timeframe', v)} options={[{ value: 'all', label: 'All' }, { value: '15m', label: '15m' }, { value: '1h', label: '1h' }, { value: '4h', label: '4h' }]} />
          <Select label="Engine" value={filters.engineVersion} onChange={v => setFilterInstant('engineVersion', v)} options={[{ value: 'all', label: 'All' }, ...engineVersions.map(v => ({ value: v, label: `v${v}` }))]} />
          <Select label="Score" value={getScorePreset()} onChange={setScoreFilter} options={[{ value: 'all', label: 'All' }, { value: '6-7', label: '6 ~ 7' }, { value: '7-8', label: '7 ~ 8' }, { value: '8-9', label: '8 ~ 9' }, { value: '9-10', label: '9 ~ 10' }]} />
          <Select label="Strategy" value={filters.strategy} onChange={v => setFilterInstant('strategy', v)} options={[{ value: 'all', label: 'All' }, ...strategies.map(s => ({ value: s, label: s }))]} />
          <Input type="number" label="Fixed Size ($)" value={filters.fixedSize} onChange={e => setFilters({ ...filters, fixedSize: Number(e.target.value) || 1000 })} />
          <div className="flex items-end"><Button variant="primary" onClick={handleApply} className="w-full">Apply</Button></div>
        </div>
      </Card>

      {/* METRICS + PORTFOLIO */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Strategy Metrics */}
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div><h3 className="text-lg font-semibold text-white">Strategy Metrics</h3><p className="text-sm text-slate-400">Trade-Level</p></div>
          </div>
          <div className="space-y-3">
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Profit Factor</span><span className={`font-bold ${profitFactor >= 1 ? 'text-emerald-400' : 'text-red-400'}`}>{profitFactor === Infinity ? '∞' : profitFactor.toFixed(2)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Expectancy</span><span className={`font-bold ${clr(expectancy)}`}>{expectancy.toFixed(2)}%</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Sharpe</span><span className="font-bold text-white">{tradeSharpe.toFixed(2)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Max Loss Streak</span><span className="font-bold text-red-400">{streaks.candle.maxLoss} / {streaks.exit.maxLoss}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Max Win Streak</span><span className="font-bold text-emerald-400">{streaks.candle.maxWin} / {streaks.exit.maxWin}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Long Win Rate</span><span className={`font-bold ${longShortWR.longWR >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{longShortWR.longWR.toFixed(1)}%</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Short Win Rate</span><span className={`font-bold ${longShortWR.shortWR >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{longShortWR.shortWR.toFixed(1)}%</span></div>
            <div className="flex justify-between py-2"><span className="text-slate-400">Avg Duration</span><span className="font-bold text-white">{avgDuration}</span></div>
          </div>
        </Card>

        {/* Portfolio Compounding */}
        <Card>
          <CardHeader title="Portfolio (Compounding)" subtitle={`Size = $${appliedFilters.fixedSize} × (NAV/$${INIT_CAP.toLocaleString()})`} />
          <div className="space-y-3">
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Initial Capital</span><span className="font-bold text-white">${INIT_CAP.toLocaleString()}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Final NAV</span><span className={`font-bold ${clr(pComp.pnl)}`}>${$(pComp.nav)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Total P&L</span><span className={`font-bold ${clr(pComp.pnl)}`}>{pComp.pnl >= 0 ? '+' : ''}${$(pComp.pnl)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Peak NAV</span><span className="font-bold text-emerald-400">${$(pComp.peakNav)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Trough NAV</span><span className="font-bold text-red-400">${$(pComp.troughNav)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Max DD</span><span className="font-bold text-red-400">{pComp.maxDD.toFixed(2)}%</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Max Gain</span><span className="font-bold text-emerald-400">{pComp.maxGain.toFixed(2)}%</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Calmar</span><span className="font-bold text-white">{pComp.calmar.toFixed(2)}</span></div>
            <div className="flex justify-between py-2"><span className="text-slate-400">Sharpe</span><span className="font-bold text-white">{pComp.sharpe.toFixed(2)}</span></div>
          </div>
        </Card>

        {/* Portfolio Fixed */}
        <Card>
          <CardHeader title={`Portfolio (Fixed $${appliedFilters.fixedSize})`} subtitle={`Size always = $${appliedFilters.fixedSize}`} />
          <div className="space-y-3">
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Initial Capital</span><span className="font-bold text-white">${INIT_CAP.toLocaleString()}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Final NAV</span><span className={`font-bold ${clr(pFixed.pnl)}`}>${$(pFixed.nav)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Total P&L</span><span className={`font-bold ${clr(pFixed.pnl)}`}>{pFixed.pnl >= 0 ? '+' : ''}${$(pFixed.pnl)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Peak NAV</span><span className="font-bold text-emerald-400">${$(pFixed.peakNav)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Trough NAV</span><span className="font-bold text-red-400">${$(pFixed.troughNav)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Max DD</span><span className="font-bold text-red-400">{pFixed.maxDD.toFixed(2)}%</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Max Gain</span><span className="font-bold text-emerald-400">{pFixed.maxGain.toFixed(2)}%</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Calmar</span><span className="font-bold text-white">{pFixed.calmar.toFixed(2)}</span></div>
            <div className="flex justify-between py-2"><span className="text-slate-400">Sharpe</span><span className="font-bold text-white">{pFixed.sharpe.toFixed(2)}</span></div>
          </div>
        </Card>
      </div>

      {/* EQUITY CURVE */}
      <Card>
        <CardHeader title="Equity Curve" subtitle="Hover for details — Compounding vs Fixed" />
        {eqCurve.length > 0 ? (
          <ResponsiveContainer width="100%" height={380}>
            <LineChart data={eqCurve} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="time" stroke="#64748b" fontSize={11} interval="preserveStartEnd" />
              <YAxis stroke="#64748b" fontSize={11} tickFormatter={v => `$${(v / 1000).toFixed(1)}k`} />
              <Tooltip content={<ChartTooltip />} />
              <Legend />
              <Line type="monotone" dataKey="compounding" name="Compounding" stroke="#6366f1" strokeWidth={2} dot={false} activeDot={{ r: 5, fill: '#6366f1', stroke: '#fff', strokeWidth: 2 }} />
              <Line type="monotone" dataKey="fixed" name="Fixed Size" stroke="#10b981" strokeWidth={2} dot={false} activeDot={{ r: 5, fill: '#10b981', stroke: '#fff', strokeWidth: 2 }} />
            </LineChart>
          </ResponsiveContainer>
        ) : <div className="h-[380px] flex items-center justify-center text-slate-500">No closed trades</div>}
      </Card>

      {/* DRAWDOWN */}
      <Card>
        <CardHeader title="Drawdown" subtitle="Hover for details" />
        {eqCurve.length > 0 ? (
          <ResponsiveContainer width="100%" height={220}>
            <AreaChart data={eqCurve} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
              <XAxis dataKey="time" stroke="#64748b" fontSize={11} interval="preserveStartEnd" />
              <YAxis stroke="#64748b" fontSize={11} tickFormatter={v => `-${v}%`} reversed />
              <Tooltip content={<ChartTooltip />} />
              <Legend />
              <Area type="monotone" dataKey="ddComp" name="Compounding DD" stroke="#ef4444" fill="#ef4444" fillOpacity={0.2} activeDot={{ r: 5, fill: '#ef4444', stroke: '#fff', strokeWidth: 2 }} />
              <Area type="monotone" dataKey="ddFixed" name="Fixed DD" stroke="#f97316" fill="#f97316" fillOpacity={0.2} activeDot={{ r: 5, fill: '#f97316', stroke: '#fff', strokeWidth: 2 }} />
            </AreaChart>
          </ResponsiveContainer>
        ) : <div className="h-[220px] flex items-center justify-center text-slate-500">No data</div>}
      </Card>

      {/* REGIME */}
      <Card>
        <CardHeader title="Regime Breakdown" subtitle="Filtered" />
        {regimeBreakdown.length > 0 ? <DataTable columns={regimeColumns} data={regimeBreakdown} pageSize={5} /> : <div className="h-48 flex items-center justify-center text-slate-500">No data</div>}
      </Card>

      {/* ACTIVE (UNFILTERED) */}
      <Card>
        <CardHeader title="Active Signals" subtitle={`${allOpen.length} open • Live 10s`} action={<span className="text-xs text-emerald-400 animate-pulse">● Live</span>} />
        <DataTable columns={activeColumns} data={activeWithPrice} pageSize={10} emptyMessage="No active signals" />
      </Card>

      {/* PENDING SIGNALS (WAIT) */}
      <Card>
        <CardHeader title="Pending Signals" subtitle={`${pendingSignals.length} waiting • Trigger price orders`} action={<span className="text-xs text-yellow-400">⏳ Pending</span>} />
        <DataTable columns={pendingColumns} data={pendingWithPrice} pageSize={10} emptyMessage="No pending signals" />
      </Card>

      {/* RECENT (UNFILTERED) */}
      <Card>
        <CardHeader title="Recent Trades" subtitle={`${filteredClosed.length} closed trades • By exit time`} />
        <DataTable columns={recentColumns} data={filteredClosed} pageSize={10} emptyMessage="No closed trades today" />
      </Card>

      {/* HEATMAP (UNFILTERED) */}
      <Card>
        <CardHeader title="Pattern × Timeframe Heatmap" subtitle="All data" />
        {heatmapData.length > 0 ? <Heatmap data={heatmapData} xLabel="Timeframe" yLabel="Pattern" valueLabel="Win Rate %" colorScale="green-red" showValues /> : <div className="h-64 flex items-center justify-center text-slate-500">No data</div>}
      </Card>
    </div>
  );
}
