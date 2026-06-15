import { useEffect, useState, useMemo } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Select } from '../components/ui/Select';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { DataTable } from '../components/ui/Table';
import { DirectionBadge, PercentChangeBadge, StatusBadge } from '../components/ui/Badge';
import { Heatmap } from '../components/charts/Heatmap';
import { Zap, Clock, Filter, RefreshCw, Loader2, Target, BarChart3 } from 'lucide-react';
import { format } from 'date-fns';
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend
} from 'recharts';

// ========== TYPES ==========
interface Signal {
  id: number; symbol: string; pattern: string; direction: string;
  timeframe: string; entry_price: number; stop_loss: number;
  take_profit: number; score: number; regime: string; status: string;
  result_percent: number; candle_time: string; exit_time: string;
  exit_price: number; strategy_name: string; engine_version: number;
  created_at: string;
}

interface Filters {
  startDate: string; endDate: string; timeframe: string;
  engineVersion: string; scoreMin: string; scoreMax: string;
  strategy: string; fixedSize: number;
}

// ========== HELPERS ==========
const API = '/api';
async function fetchAPI<T>(ep: string): Promise<T> {
  const r = await fetch(`${API}${ep}`); if (!r.ok) throw new Error(`${r.status}`); return r.json();
}
// DB stores naive UTC — append Z so browser converts to local (VN = UTC+7)
function parseUtcMs(v: string): number {
  if (!v) return 0;
  let s = String(v);
  if (!s.includes('Z') && !s.includes('+')) s += 'Z';
  const d = new Date(s);
  return isNaN(d.getTime()) ? 0 : d.getTime();
}
function utcToLocal(v: string): string {
  if (!v) return '-';
  const ms = parseUtcMs(v);
  return ms ? format(new Date(ms), 'MM/dd HH:mm') : '-';
}
// Score: display raw value from DB — no conversion at all
function ScoreCell({ value }: { value: number }) {
  const v = Number(value) || 0;
  return <span className={`font-mono text-sm ${v >= 8 ? 'text-emerald-400' : v >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>{v.toFixed(2)}</span>;
}

const fetchBinancePrices = async (): Promise<Record<string, number>> => {
  try {
    const r = await fetch('https://fapi.binance.com/fapi/v1/ticker/price');
    const d = await r.json(); const p: Record<string, number> = {};
    d.forEach((i: any) => { p[i.symbol] = parseFloat(i.price); }); return p;
  } catch { return {}; }
};

function normalizeUtcString(v?: string) {
  if (!v) return v as any;
  const s = String(v);
  return (!s.includes('Z') && !s.includes('+')) ? s + 'Z' : s;
}

function normalizeSignalDates<T extends Record<string, any>>(s: T): T {
  return {
    ...s,
    candle_time: normalizeUtcString(s.candle_time),
    exit_time: normalizeUtcString(s.exit_time),
    created_at: normalizeUtcString(s.created_at),
  } as T;
}

// Custom tooltip for charts
function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-slate-800 border border-slate-600 rounded-lg p-3 shadow-xl text-sm">
      <p className="text-slate-400 mb-2 font-medium">{label}</p>
      {payload.map((entry: any, i: number) => (
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

function getTodayVN() {
  return new Date(Date.now() + 7 * 60 * 60 * 1000).toISOString().slice(0, 10);
}
function toUtcRangeFromVNDate(startDate: string, endDate: string) {
  const start = startDate ? new Date(startDate + 'T00:00:00+07:00').toISOString() : '';
  const end = endDate ? new Date(new Date(endDate + 'T00:00:00+07:00').getTime() + 24 * 60 * 60 * 1000).toISOString() : '';
  return { start, end };
}

// ========== COMPONENT ==========
export function Dashboard() {
  const INIT_CAP = 10000;
  const todayVN = getTodayVN();

  const [allSignals, setAllSignals] = useState<Signal[]>([]);
  const [metricSignals, setMetricSignals] = useState<Signal[]>([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [maxOpen, setMaxOpen] = useState(50);
  const [engineVersions, setEngineVersions] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);
  const [binancePrices, setBinancePrices] = useState<Record<string, number>>({});
  const [priceFlash, setPriceFlash] = useState<Record<string, 'up' | 'down' | null>>({});
  const [loading, setLoading] = useState(true);

  // Filters — combobox changes apply instantly, date/fixedSize need Apply
  const [filters, setFilters] = useState<Filters>({
    startDate: todayVN, endDate: todayVN, timeframe: 'all',
    engineVersion: 'all', scoreMin: '', scoreMax: '',
    strategy: 'all', fixedSize: 1000,
  });
  const [appliedFilters, setAppliedFilters] = useState<Filters>(filters);

  // Instant apply for combobox changes
  const setFilterInstant = (key: keyof Filters, value: string) => {
    const next = { ...filters, [key]: value };
    setFilters(next);
    // Instant apply for dropdown selects
    if (['timeframe', 'engineVersion', 'strategy'].includes(key)) {
      setAppliedFilters(prev => ({ ...prev, [key]: value }));
    }
  };

  // Score filter — DB stores raw numeric: 6, 6.5, 8.25, etc.
  const setScoreFilter = (preset: string) => {
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
      setLoading(true);
      try {
        const { start, end } = toUtcRangeFromVNDate(todayVN, todayVN);
        const [allSigs, metricSigs, pending, vers, prices, appCfg] = await Promise.all([
          // ALL signals (no date filter) for Active/Recent/Heatmap
          fetchAPI<{ data: Signal[] }>('/signals?limit=2000'),
          // Metrics: current VN day by exit_time
          fetchAPI<{ data: Signal[] }>(`/signals?limit=2000&date_field=exit_time&start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`)
            .catch(() => ({ data: [] })),
          fetchAPI<{ total: number }>('/pending-signals?status=WAIT&limit=1').catch(() => ({ total: 0 })),
          fetchAPI<any[]>('/engine/versions').catch(() => []),
          fetchBinancePrices(),
          fetchAPI<Record<string, string>>('/app-config').catch(() => ({})),
        ]);
        const signals = ((allSigs.data || []).map(normalizeSignalDates) as Signal[]);
        setAllSignals(signals);
        setMetricSignals(((metricSigs.data || []).map(normalizeSignalDates) as Signal[]));
        setPendingCount(pending.total || 0);
        setEngineVersions(vers.map((v: any) => String(v.engine_version)).filter(Boolean).sort().reverse());
        setStrategies(Array.from(new Set(signals.map(s => s.strategy_name).filter(Boolean))).sort());
        setBinancePrices(prices);
        setMaxOpen(parseInt(appCfg['MAX_OPEN_TRADES'] || '10'));
      } catch (e) { console.error(e); }
      finally { setLoading(false); }
    })();
  }, [todayVN]);

  // Refetch metric dataset when applied date changes (default = current VN day)
  useEffect(() => {
    (async () => {
      try {
        const { start, end } = toUtcRangeFromVNDate(appliedFilters.startDate, appliedFilters.endDate);
        const sigs = await fetchAPI<{ data: Signal[] }>(`/signals?limit=2000&date_field=exit_time&start_date=${encodeURIComponent(start)}&end_date=${encodeURIComponent(end)}`);
        setMetricSignals(((sigs.data || []).map(normalizeSignalDates) as Signal[]));
      } catch (e) { console.error('metric refetch failed', e); }
    })();
  }, [appliedFilters.startDate, appliedFilters.endDate]);

  // Auto-refresh prices
  useEffect(() => {
    const iv = setInterval(async () => {
      const np = await fetchBinancePrices();
      setBinancePrices(prev => {
        const fl: Record<string, 'up' | 'down' | null> = {};
        Object.keys(np).forEach(s => {
          if (prev[s] && np[s] !== prev[s]) fl[s] = np[s] > prev[s] ? 'up' : 'down';
        });
        setPriceFlash(fl);
        setTimeout(() => setPriceFlash({}), 600);
        return np;
      });
    }, 10000);
    return () => clearInterval(iv);
  }, []);

  // ========== DATA SPLITS ==========
  const allOpen = useMemo(() =>
    allSignals.filter(s => s.status === 'OPEN').sort((a, b) => new Date(b.candle_time || 0).getTime() - new Date(a.candle_time || 0).getTime()),
    [allSignals]);

  const allClosed = useMemo(() =>
    allSignals.filter(s => s.status === 'WIN' || s.status === 'LOSS').sort((a, b) => parseUtcMs(b.exit_time || '') - parseUtcMs(a.exit_time || '')),
    [allSignals]);

  const metricClosed = useMemo(() =>
    metricSignals.filter(s => s.status === 'WIN' || s.status === 'LOSS').sort((a, b) => parseUtcMs(b.exit_time || '') - parseUtcMs(a.exit_time || '')),
    [metricSignals]);

  // ========== FILTERED CLOSED (for metrics only) ==========
  // Dashboard: filter by exit_time (realized PnL window)
  // End inclusive: Start 8/6 End 8/6 = whole 8/6, Start 8/6 End 9/6 = 8/6 + 9/6
  const filteredClosed = useMemo(() => {
    const af = appliedFilters;
    const startUTC = af.startDate ? new Date(af.startDate + 'T00:00:00+07:00').getTime() : null;
    const endUTC = af.endDate
      ? new Date(new Date(af.endDate + 'T00:00:00+07:00').getTime() + 24 * 60 * 60 * 1000).getTime()
      : null;

    return metricClosed.filter(s => {
      // Dashboard uses exit_time for date filter
      const exitMs = parseUtcMs(s.exit_time || '');
      if (startUTC && exitMs < startUTC) return false;
      if (endUTC && exitMs >= endUTC) return false;
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
  const totalTrades = filteredClosed.length;
  const wins = filteredClosed.filter(s => s.status === 'WIN').length;
  const winRate = totalTrades > 0 ? (wins / totalTrades) * 100 : 0;

  const profitFactor = useMemo(() => {
    const gp = filteredClosed.filter(s => (s.result_percent || 0) > 0).reduce((a, s) => a + (s.result_percent || 0), 0);
    const gl = Math.abs(filteredClosed.filter(s => (s.result_percent || 0) < 0).reduce((a, s) => a + (s.result_percent || 0), 0));
    return gl > 0 ? gp / gl : gp > 0 ? Infinity : 0;
  }, [filteredClosed]);

  const expectancy = useMemo(() => {
    if (!totalTrades) return 0;
    const wA = filteredClosed.filter(s => (s.result_percent || 0) > 0);
    const lA = filteredClosed.filter(s => (s.result_percent || 0) < 0);
    const avgW = wA.length ? wA.reduce((a, s) => a + (s.result_percent || 0), 0) / wA.length : 0;
    const avgL = lA.length ? Math.abs(lA.reduce((a, s) => a + (s.result_percent || 0), 0) / lA.length) : 0;
    return (wins / totalTrades) * avgW - ((totalTrades - wins) / totalTrades) * avgL;
  }, [filteredClosed, totalTrades, wins]);

  const tradeSharpe = useMemo(() => {
    const r = filteredClosed.map(s => s.result_percent || 0);
    if (!r.length) return 0;
    const avg = r.reduce((a, b) => a + b, 0) / r.length;
    const std = Math.sqrt(r.reduce((s, x) => s + (x - avg) ** 2, 0) / r.length);
    return std > 0 ? avg / std : 0;
  }, [filteredClosed]);

  const streaks = useMemo(() => {
    const calc = (arr: Signal[]) => {
      let mw = 0, ml = 0, cw = 0, cl = 0;
      arr.forEach(s => { if (s.status === 'WIN') { cw++; cl = 0; mw = Math.max(mw, cw); } else { cl++; cw = 0; ml = Math.max(ml, cl); } });
      return { maxWin: mw, maxLoss: ml };
    };
    return {
      candle: calc([...filteredClosed].sort((a, b) => new Date(a.candle_time || 0).getTime() - new Date(b.candle_time || 0).getTime())),
      exit: calc([...filteredClosed].sort((a, b) => new Date(a.exit_time || 0).getTime() - new Date(b.exit_time || 0).getTime())),
    };
  }, [filteredClosed]);

  // Long / Short Win Rate
  const longShortWR = useMemo(() => {
    const longs = filteredClosed.filter(s => s.direction === 'LONG');
    const shorts = filteredClosed.filter(s => s.direction === 'SHORT');
    const longWins = longs.filter(s => s.status === 'WIN').length;
    const shortWins = shorts.filter(s => s.status === 'WIN').length;
    return {
      longWR: longs.length > 0 ? (longWins / longs.length) * 100 : 0,
      longTotal: longs.length,
      shortWR: shorts.length > 0 ? (shortWins / shorts.length) * 100 : 0,
      shortTotal: shorts.length,
    };
  }, [filteredClosed]);

  // Avg Duration (candle_time → exit_time)
  const avgDuration = useMemo(() => {
    const durations = filteredClosed
      .filter(s => s.candle_time && s.exit_time)
      .map(s => {
        const entry = parseUtcMs(s.candle_time);
        const exit = parseUtcMs(s.exit_time);
        return exit - entry; // milliseconds
      })
      .filter(d => d > 0);
    if (!durations.length) return '-';
    const avgMs = durations.reduce((a, b) => a + b, 0) / durations.length;
    const mins = Math.round(avgMs / 60000);
    if (mins < 60) return `${mins}m`;
    const hrs = Math.floor(mins / 60);
    const remainMins = mins % 60;
    if (hrs < 24) return `${hrs}h ${remainMins}m`;
    const days = Math.floor(hrs / 24);
    const remainHrs = hrs % 24;
    return `${days}d ${remainHrs}h`;
  }, [filteredClosed]);

  // ========== PORTFOLIO: COMPOUNDING ==========
  // dynamic_position_size = fixed_size_input × (current_NAV / initial_capital)
  // PnL = dynamic_position_size × result_percent
  // NAV scales position size → true compounding
  const pComp = useMemo(() => {
    const fsInput = appliedFilters.fixedSize || 1000;
    const sorted = [...filteredClosed].sort((a, b) => parseUtcMs(a.exit_time || '') - parseUtcMs(b.exit_time || ''));
    let nav = INIT_CAP, peakNav = nav, troughNav = nav, maxDD = 0, maxGain = 0;
    const curve: { time: string; nav: number; dd: number; symbol: string; pnl: number; rp: number }[] = [];
    const pnlList: number[] = [];

    sorted.forEach(s => {
      const rp = s.result_percent || 0;
      const dynamicPosSize = fsInput * (nav / INIT_CAP);
      const pnl = dynamicPosSize * (rp / 100);
      nav += pnl;
      pnlList.push(pnl);
      peakNav = Math.max(peakNav, nav);
      troughNav = Math.min(troughNav, nav);
      const dd = (peakNav - nav) / peakNav * 100;
      maxDD = Math.max(maxDD, dd);
      maxGain = Math.max(maxGain, (nav - INIT_CAP) / INIT_CAP * 100);
      curve.push({ time: s.exit_time ? format(new Date(s.exit_time), 'MM/dd HH:mm') : '', nav: Math.round(nav * 100) / 100, dd: Math.round(dd * 100) / 100, symbol: s.symbol, pnl: Math.round(pnl * 100) / 100, rp });
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
    const sorted = [...filteredClosed].sort((a, b) => new Date(a.exit_time || 0).getTime() - new Date(b.exit_time || 0).getTime());
    let nav = INIT_CAP, peakNav = nav, troughNav = nav, maxDD = 0, maxGain = 0;
    const curve: { time: string; nav: number; dd: number; symbol: string; pnl: number; rp: number }[] = [];
    const pnlList: number[] = [];
    sorted.forEach(s => {
      const rp = s.result_percent || 0;
      const pnl = fs * (rp / 100);
      nav += pnl;
      pnlList.push(pnl);
      peakNav = Math.max(peakNav, nav);
      troughNav = Math.min(troughNav, nav);
      const dd = (peakNav - nav) / peakNav * 100;
      maxDD = Math.max(maxDD, dd);
      maxGain = Math.max(maxGain, (nav - INIT_CAP) / INIT_CAP * 100);
      curve.push({ time: s.exit_time ? format(new Date(s.exit_time), 'MM/dd HH:mm') : '', nav: Math.round(nav * 100) / 100, dd: Math.round(dd * 100) / 100, symbol: s.symbol, pnl: Math.round(pnl * 100) / 100, rp });
    });
    const ret = ((nav - INIT_CAP) / INIT_CAP) * 100;
    const pctReturns = pnlList.map(p => (p / INIT_CAP) * 100);
    const avg = pctReturns.length ? pctReturns.reduce((a, b) => a + b, 0) / pctReturns.length : 0;
    const std = pctReturns.length ? Math.sqrt(pctReturns.reduce((s, x) => s + (x - avg) ** 2, 0) / pctReturns.length) : 0;
    return { nav, pnl: nav - INIT_CAP, ret, maxDD, maxGain, peakNav, troughNav, sharpe: std > 0 ? avg / std : 0, calmar: maxDD > 0 ? ret / maxDD : 0, curve };
  }, [filteredClosed, appliedFilters.fixedSize]);

  // ========== REGIME (filtered) ==========
  const regimeBreakdown = useMemo(() => {
    const reg: Record<string, { total: number; wins: number; returns: number[] }> = {};
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
      return { regime, trades: d.total, wins: d.wins, winrate: wr,
        expectancy: (wr / 100) * avgW - ((1 - wr / 100) * avgL),
        profitFactor: gl > 0 ? gp / gl : gp > 0 ? Infinity : 0,
        totalReturn: d.returns.reduce((a, b) => a + b, 0) };
    }).sort((a, b) => b.trades - a.trades);
  }, [filteredClosed]);

  // ========== HEATMAP (UNFILTERED) ==========
  const heatmapData = useMemo(() => {
    const data: any[] = [], patterns = new Set<string>();
    const g: Record<string, Record<string, { w: number; t: number }>> = {};
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
  const activeWithPrice = useMemo(() =>
    allOpen.map(s => {
      const cp = binancePrices[s.symbol] || 0;
      const pnl = cp && s.entry_price ? (s.direction === 'LONG' ? ((cp - s.entry_price) / s.entry_price) : ((s.entry_price - cp) / s.entry_price)) * 100 : 0;
      return { ...s, currentPrice: cp, pnl, flash: priceFlash[s.symbol] };
    }), [allOpen, binancePrices, priceFlash]);

  // ========== EQUITY CURVE COMBINED ==========
  const eqCurve = useMemo(() => {
    const n = Math.max(pComp.curve.length, pFixed.curve.length);
    return Array.from({ length: n }, (_, i) => ({
      time: pComp.curve[i]?.time || pFixed.curve[i]?.time || '',
      compounding: pComp.curve[i]?.nav ?? null,
      fixed: pFixed.curve[i]?.nav ?? null,
      ddComp: pComp.curve[i]?.dd || 0,
      ddFixed: pFixed.curve[i]?.dd || 0,
      symbol: pComp.curve[i]?.symbol || '',
      pnlComp: pComp.curve[i]?.pnl || 0,
      pnlFixed: pFixed.curve[i]?.pnl || 0,
      rpComp: pComp.curve[i]?.rp || 0,
    }));
  }, [pComp.curve, pFixed.curve]);

  // ========== TABLE COLUMNS ==========
  const activeColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: (v: string) => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'entry_price', header: 'Entry', render: (v: number) => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'currentPrice', header: 'Current', render: (v: number, row: any) => (
      <span className={`font-mono transition-all duration-300 ${row.flash === 'up' ? 'text-emerald-400 bg-emerald-500/20 px-1 rounded' : row.flash === 'down' ? 'text-red-400 bg-red-500/20 px-1 rounded' : 'text-white'}`}>
        {v?.toFixed(v > 100 ? 2 : 4) || '-'}
      </span>)},
    { key: 'stop_loss', header: 'SL', render: (v: number) => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'take_profit', header: 'TP', render: (v: number) => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'pnl', header: 'P&L', sortable: true, render: (v: number) => <PercentChangeBadge value={v || 0} /> },
    { key: 'regime', header: 'Regime', sortable: true, render: (v: string) => <StatusBadge status={v || 'N/A'} /> },
    { key: 'score', header: 'Score', sortable: true, render: (v: number) => <ScoreCell value={v} /> },
    { key: 'candle_time', header: 'Opened', sortable: true, render: (v: string) => utcToLocal(v) },
  ];

  const recentColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: (v: string) => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'entry_price', header: 'Entry', render: (v: number) => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'exit_price', header: 'Exit', render: (v: number) => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'stop_loss', header: 'SL', render: (v: number) => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'take_profit', header: 'TP', render: (v: number) => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'result_percent', header: 'P&L', sortable: true, render: (v: number) => <PercentChangeBadge value={v || 0} /> },
    { key: 'status', header: 'Status', sortable: true, render: (v: string) => <StatusBadge status={v || 'N/A'} /> },
    { key: 'regime', header: 'Regime', sortable: true, render: (v: string) => <StatusBadge status={v || 'N/A'} /> },
    { key: 'score', header: 'Score', sortable: true, render: (v: number) => <ScoreCell value={v} /> },
    { key: 'candle_time', header: 'Opened', sortable: true, render: (v: string) => utcToLocal(v) },
    { key: 'exit_time', header: 'Closed', sortable: true, render: (v: string) => utcToLocal(v) },
  ];

  const regimeColumns = [
    { key: 'regime', header: 'Regime', sortable: true, render: (v: string) => <StatusBadge status={v} /> },
    { key: 'trades', header: 'Trades', sortable: true, align: 'right' as const },
    { key: 'wins', header: 'Wins', sortable: true, align: 'right' as const },
    { key: 'winrate', header: 'Win Rate', sortable: true, align: 'right' as const, render: (v: number) => <span className={v >= 50 ? 'text-emerald-400' : 'text-red-400'}>{v.toFixed(1)}%</span> },
    { key: 'expectancy', header: 'Expectancy', sortable: true, align: 'right' as const, render: (v: number) => <span className={v >= 0 ? 'text-emerald-400' : 'text-red-400'}>{v.toFixed(2)}</span> },
    { key: 'profitFactor', header: 'PF', sortable: true, align: 'right' as const, render: (v: number) => v === Infinity ? '∞' : v.toFixed(2) },
    { key: 'totalReturn', header: 'Total Return', sortable: true, render: (v: number) => <PercentChangeBadge value={v} /> },
  ];

  const $ = (v: number) => v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const clr = (v: number) => v >= 0 ? 'text-emerald-400' : 'text-red-400';

  if (loading && !allSignals.length) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin text-indigo-500" /></div>;

  // ========== RENDER ==========
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Performance Overview</h2>
          <p className="text-slate-400 mt-1">Strategy analytics and portfolio simulation</p>
        </div>
        <Button variant="ghost" icon={<RefreshCw className="w-4 h-4" />} onClick={() => window.location.reload()}>Refresh</Button>
      </div>

      {/* OVERVIEW */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Card className="flex items-center gap-4">
          <div className="p-3 bg-indigo-500/20 rounded-xl"><BarChart3 className="w-6 h-6 text-indigo-400" /></div>
          <div><p className="text-sm text-slate-400">Total Trades</p><p className="text-2xl font-bold text-white">{totalTrades}</p></div>
        </Card>
        <Card className="flex items-center gap-4">
          <div className="p-3 bg-emerald-500/20 rounded-xl"><Target className="w-6 h-6 text-emerald-400" /></div>
          <div><p className="text-sm text-slate-400">Win Rate</p><p className={`text-2xl font-bold ${winRate >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{winRate.toFixed(1)}%</p></div>
        </Card>
        <Card className="flex items-center gap-4">
          <div className="p-3 bg-yellow-500/20 rounded-xl"><Zap className="w-6 h-6 text-yellow-400" /></div>
          <div><p className="text-sm text-slate-400">Active Signals</p><p className="text-2xl font-bold text-white">{allOpen.length}</p></div>
        </Card>
        <Card className="flex items-center gap-4">
          <div className="p-3 bg-purple-500/20 rounded-xl"><Clock className="w-6 h-6 text-purple-400" /></div>
          <div><p className="text-sm text-slate-400">Pending Signals</p><p className="text-2xl font-bold text-white">{pendingCount}</p></div>
        </Card>
        <Card className="flex items-center gap-4">
          <div className="p-3 bg-orange-500/20 rounded-xl"><Filter className="w-6 h-6 text-orange-400" /></div>
          <div><p className="text-sm text-slate-400">Open / Max</p><p className="text-2xl font-bold text-white">{allOpen.length} / {maxOpen}</p></div>
        </Card>
      </div>

      {/* FILTERS */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <Filter className="w-5 h-5 text-slate-400" />
          <h3 className="font-semibold text-white">Filters</h3>
          <span className="text-xs text-slate-500 ml-2">→ Metrics, Portfolio, Charts, Regime</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-8 gap-3">
          <Input type="date" label="From" value={filters.startDate} onChange={e => setFilters({...filters, startDate: e.target.value})} />
          <Input type="date" label="To" value={filters.endDate} onChange={e => setFilters({...filters, endDate: e.target.value})} />
          <Select label="Timeframe" value={filters.timeframe} onChange={v => setFilterInstant('timeframe', v)}
            options={[{ value: 'all', label: 'All' }, { value: '15m', label: '15m' }, { value: '1h', label: '1h' }, { value: '4h', label: '4h' }]} />
          <Select label="Engine" value={filters.engineVersion} onChange={v => setFilterInstant('engineVersion', v)}
            options={[{ value: 'all', label: 'All' }, ...engineVersions.map(v => ({ value: v, label: `v${v}` }))]} />
          <Select label="Score" value={getScorePreset()} onChange={setScoreFilter}
            options={[{ value: 'all', label: 'All' }, { value: '6-7', label: '6 ~ 7' }, { value: '7-8', label: '7 ~ 8' }, { value: '8-9', label: '8 ~ 9' }, { value: '9-10', label: '9 ~ 10' }]} />
          <Select label="Strategy" value={filters.strategy} onChange={v => setFilterInstant('strategy', v)}
            options={[{ value: 'all', label: 'All' }, ...strategies.map(s => ({ value: s, label: s }))]} />
          <Input type="number" label="Fixed Size ($)" value={filters.fixedSize} onChange={e => setFilters({...filters, fixedSize: Number(e.target.value) || 1000})} />
          <div className="flex items-end"><Button variant="primary" onClick={handleApply} className="w-full">Apply</Button></div>
        </div>
      </Card>

      {/* METRICS + PORTFOLIO */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-white">Strategy Metrics</h3>
              <p className="text-sm text-slate-400">Trade-Level</p>
            </div>
            <button onClick={() => {
              const sorted = [...filteredClosed].sort((a, b) => new Date(a.exit_time || 0).getTime() - new Date(b.exit_time || 0).getTime());
              const streak = sorted.map(s => s.status === 'WIN' ? 'W' : 'L').join(' ');
              navigator.clipboard.writeText(streak);
              alert(`Copied ${sorted.length} results`);
            }} className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded-lg text-xs">
              📋 Trade Streak
            </button>
          </div>
          <div className="space-y-3">
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Profit Factor</span><span className={`font-bold ${profitFactor >= 1 ? 'text-emerald-400' : 'text-red-400'}`}>{profitFactor === Infinity ? '∞' : profitFactor.toFixed(2)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Expectancy</span><span className={`font-bold ${clr(expectancy)}`}>{expectancy.toFixed(2)}%</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Sharpe</span><span className="font-bold text-white">{tradeSharpe.toFixed(2)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700">
              <span className="text-slate-400">Max Loss Streak <span className="text-slate-600 text-xs">(Candle / Exit)</span></span>
              <span className="font-bold text-red-400">{streaks.candle.maxLoss} / {streaks.exit.maxLoss}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-slate-700">
              <span className="text-slate-400">Max Win Streak <span className="text-slate-600 text-xs">(Candle / Exit)</span></span>
              <span className="font-bold text-emerald-400">{streaks.candle.maxWin} / {streaks.exit.maxWin}</span>
            </div>
            <div className="flex justify-between py-2 border-b border-slate-700">
              <span className="text-slate-400">Long Win Rate</span>
              <span className={`font-bold ${longShortWR.longWR >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{longShortWR.longWR.toFixed(1)}% <span className="text-slate-500 text-xs">({longShortWR.longTotal})</span></span>
            </div>
            <div className="flex justify-between py-2 border-b border-slate-700">
              <span className="text-slate-400">Short Win Rate</span>
              <span className={`font-bold ${longShortWR.shortWR >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{longShortWR.shortWR.toFixed(1)}% <span className="text-slate-500 text-xs">({longShortWR.shortTotal})</span></span>
            </div>
            <div className="flex justify-between py-2">
              <span className="text-slate-400">Avg Duration</span>
              <span className="font-bold text-white">{avgDuration}</span>
            </div>
          </div>
        </Card>

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
              <YAxis stroke="#64748b" fontSize={11} tickFormatter={v => `$${(v/1000).toFixed(1)}k`} />
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
        {regimeBreakdown.length > 0 ? <DataTable columns={regimeColumns} data={regimeBreakdown} pageSize={5} /> :
          <div className="h-48 flex items-center justify-center text-slate-500">No data</div>}
      </Card>

      {/* ACTIVE (UNFILTERED) */}
      <Card>
        <CardHeader title="Active Signals" subtitle={`${allOpen.length} open • Live 10s`} action={<span className="text-xs text-emerald-400 animate-pulse">● Live</span>} />
        <DataTable columns={activeColumns} data={activeWithPrice} pageSize={10} emptyMessage="No active signals" />
      </Card>

      {/* RECENT (UNFILTERED) */}
      <Card>
        <CardHeader title="Recent Trades" subtitle={`${allClosed.length} closed • By exit time`} />
        <DataTable columns={recentColumns} data={allClosed} pageSize={10} emptyMessage="No closed trades" />
      </Card>

      {/* HEATMAP (UNFILTERED) */}
      <Card>
        <CardHeader title="Pattern × Timeframe Heatmap" subtitle="All data" />
        {heatmapData.length > 0 ? <Heatmap data={heatmapData} xLabel="Timeframe" yLabel="Pattern" valueLabel="Win Rate %" colorScale="green-red" showValues /> :
          <div className="h-64 flex items-center justify-center text-slate-500">No data</div>}
      </Card>
    </div>
  );
}
