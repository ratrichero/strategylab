// @ts-nocheck
/* eslint-disable */
import { useEffect, useState, useMemo, useRef } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Select } from '../components/ui/Select';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { DataTable } from '../components/ui/Table';
import { DirectionBadge, PercentChangeBadge, StatusBadge } from '../components/ui/Badge';
import { Heatmap } from '../components/charts/Heatmap';
import { Zap, Clock, Filter, RefreshCw, Loader2, Target, BarChart3, CalendarCheck, X } from 'lucide-react';
import { AreaChart, Area, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { parseUtcMs, utcToVN, getTodayVN, normalizeSignalDates } from '../utils/time';
import toast from 'react-hot-toast';
import { TradeDetailModal } from '../components/TradeDetailModal';
import { buildFetchPlan, fetchKlines1m } from '../utils/klineSimulator';
import { useAppStore } from '../store/appStore';
import { fetchDashboardOverview, fetchDashboardPortfolio, fetchDashboardBreakdowns, fetchDashboardRecentTrades } from '../services/dashboardApi';
import { buildAnalyticsFilter } from '../utils/analyticsFilters';

const API = '/api';
async function fetchAPI(ep) { const r = await fetch(`${API}${ep}`); if (!r.ok) throw new Error(`${r.status}`); return r.json(); }
function ScoreCell({ value }) { const v = Number(value) || 0; return <span className={`font-mono text-sm ${v >= 8 ? 'text-emerald-400' : v >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>{v.toFixed(2)}</span>; }
const fetchBinancePrices = async () => { try { const r = await fetch('https://fapi.binance.com/fapi/v1/ticker/price'); const d = await r.json(); const p = {}; d.forEach((i) => { p[i.symbol] = parseFloat(i.price); }); return p; } catch { return {}; } };
const fmtMoney = (v) => Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const isInfiniteMetric = (v) => !Number.isFinite(Number(v)) || Number(v) >= 1000000000;
const fmtPrice = (v) => {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n.toFixed(n > 100 ? 2 : 4) : '-';
};


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
  const { appRole } = useAppStore();
  const isBotDashboard = appRole === 'BOT';
  const INIT_CAP = 10000;
  const todayVN = getTodayVN();

  const [activeSignals, setActiveSignals] = useState([]);
  const [pendingSignals, setPendingSignals] = useState([]);
  const [pendingCount, setPendingCount] = useState(0);
  const [maxOpen, setMaxOpen] = useState(50);
  const [engineVersions, setEngineVersions] = useState([]);
  const [strategies, setStrategies] = useState([]);
  const [allRegimes, setAllRegimes] = useState([]);
  const [allPatterns, setAllPatterns] = useState([]);
  const [allTimeframes, setAllTimeframes] = useState([]);
  const [binancePrices, setBinancePrices] = useState({});
  const [priceFlash, setPriceFlash] = useState({});
  const [loading, setLoading] = useState(true);
  const [apiError, setApiError] = useState('');

  const [filters, setFilters] = useState({ startDate: '', endDate: '', timeframe: 'all', engineVersion: 'all', scoreMin: '', scoreMax: '', strategy: 'all', regime: 'all', pattern: 'all', direction: 'all', capPsize: '10000|1000' });
  const [appliedFilters, setAppliedFilters] = useState(filters);
  const [statusMode, setStatusMode] = useState('WL'); // WL = WIN/LOSS only, ALL = all statuses
  const [recentSearch, setRecentSearch] = useState('');
  const [recentTradesPage, setRecentTradesPage] = useState(1);
  const [recentRefreshNonce, setRecentRefreshNonce] = useState(0);
  const [selectedTrade, setSelectedTrade] = useState(null);
  const [selectedTradeKlines, setSelectedTradeKlines] = useState([]);
  const [tradeKlineCache, setTradeKlineCache] = useState(new Map());
  const [tradeKlineLoading, setTradeKlineLoading] = useState(false);
  const selectedTradeKeyRef = useRef('');

  // Backend data states
  const [overviewData, setOverviewData] = useState(null);
  const [portfolioData, setPortfolioData] = useState(null);
  const [breakdownsData, setBreakdownsData] = useState(null);
  const [recentTradesData, setRecentTradesData] = useState({ data: [], total: 0, page: 1, limit: 10, pages: 1 });

  // Parse CAP|PSize from filter
  const parseCapPsize = (v) => {
    const parts = (v || '10000|1000').split('|');
    return { cap: parseFloat(parts[0]) || 10000, psize: parseFloat(parts[1]) || 1000 };
  };

  const setFilterInstant = (key, value) => {
    const next = { ...filters, [key]: value };
    setFilters(next);
    if (['timeframe', 'engineVersion', 'strategy', 'regime', 'pattern', 'direction'].includes(key)) {
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

  // Helper function to add days to a date string (YYYY-MM-DD format)
  const addDaysToDateString = (dateString, delta) => {
    if (!dateString) return dateString;
    const [year, month, day] = dateString.split('-').map(Number);
    const date = new Date(Date.UTC(year, month - 1, day));
    date.setUTCDate(date.getUTCDate() + delta);
    const newYear = date.getUTCFullYear();
    const newMonth = String(date.getUTCMonth() + 1).padStart(2, '0');
    const newDay = String(date.getUTCDate()).padStart(2, '0');
    return `${newYear}-${newMonth}-${newDay}`;
  };

  // Shift both start and end dates by delta days
  const shiftDateRange = (delta) => {
    const todayVN = getTodayVN();
    let newStartDate, newEndDate;
    
    if (!filters.startDate && !filters.endDate) {
      // Both empty: start from today and shift
      newStartDate = addDaysToDateString(todayVN, delta);
      newEndDate = addDaysToDateString(todayVN, delta);
    } else {
      // At least one is set: shift only the ones that are set
      newStartDate = filters.startDate ? addDaysToDateString(filters.startDate, delta) : filters.startDate;
      newEndDate = filters.endDate ? addDaysToDateString(filters.endDate, delta) : filters.endDate;
    }
    
    setFilters({ ...filters, startDate: newStartDate, endDate: newEndDate });
  };

  const getTradeKlineKey = (trade) => {
    const plan = buildFetchPlan([trade])[0];
    return plan ? `${plan.symbol}_${plan.startMs}_${plan.endMs}` : '';
  };

  const handleRecentTradeClick = async (row) => {
    const modalTrade = {
      ...row,
      entry_time: row.entry_time || row.created_at || row.candle_time,
      sim_result: row.sim_result ?? row._derivedPct ?? row.result_percent,
      sim_status: row.sim_status || row._derivedStatus || row.status,
      sim_counted: row.sim_counted ?? true,
      sim_sl: row.sim_sl ?? row.stop_loss,
      sim_tp: row.sim_tp ?? row.take_profit,
    };
    const plan = buildFetchPlan([modalTrade])[0];
    const key = getTradeKlineKey(modalTrade);

    setSelectedTrade(modalTrade);
    setSelectedTradeKlines([]);
    selectedTradeKeyRef.current = key;

    if (!plan || !key) {
      toast.error('Cannot load kline window for this trade');
      return;
    }

    const cached = tradeKlineCache.get(key);
    if (cached) {
      setSelectedTradeKlines(cached);
      return;
    }

    setTradeKlineLoading(true);
    try {
      const klines = await fetchKlines1m(plan.symbol, plan.startMs, plan.endMs);
      setTradeKlineCache(prev => {
        const next = new Map(prev);
        next.set(key, klines);
        return next;
      });
      if (selectedTradeKeyRef.current === key) {
        setSelectedTradeKlines(klines);
      }
    } catch (e) {
      console.error(e);
      toast.error('Failed to load Binance klines');
    } finally {
      if (selectedTradeKeyRef.current === key) {
        setTradeKlineLoading(false);
      }
    }
  };

  const refreshRealtimeTables = async () => {
    const [openSigs, pending] = await Promise.all([
      fetchAPI('/signals?status=OPEN&limit=10000'),
      fetchAPI('/pending-signals?status=WAIT&limit=200').catch(() => ({ data: [], total: 0 })),
    ]);
    setActiveSignals((openSigs.data || []).map(normalizeSignalDates));
    setPendingSignals((pending.data || []).map(normalizeSignalDates));
    setPendingCount(pending.total || 0);
  };

  const refreshViewsAndRecent = async () => {
    await fetch(`${API}/admin/refresh-views`, { method: 'POST' }).catch(e => console.error('[Dashboard] view refresh failed:', e));
    setRecentRefreshNonce(v => v + 1);
  };

  // ========== LOAD ==========
  useEffect(() => {
    (async () => {
      setLoading(true); setApiError('');
      try {
        console.log('[Dashboard] todayVN:', todayVN);
        const [openSigs, pending, vers, filterOptions, prices, appCfg] = await Promise.all([
          fetchAPI('/signals?status=OPEN&limit=10000').catch(e => { setApiError(p => p + ' active:' + e.message); return { data: [] }; }),
          fetchAPI('/pending-signals?status=WAIT&limit=200').catch(() => ({ data: [], total: 0 })),
          fetchAPI('/engine/versions').catch(() => []),
          fetchAPI('/filter-options?source=closed').catch(() => ({ strategies: [], patterns: [], regimes: [], timeframes: [] })),
          fetchBinancePrices(),
          fetchAPI('/app-config').catch(() => ({})),
        ]);
        const active = (openSigs.data || []).map(normalizeSignalDates);
        console.log('[Dashboard] active:', active.length);

        setActiveSignals(active);
        setPendingSignals((pending.data || []).map(normalizeSignalDates));
        setPendingCount(pending.total || 0);
        setEngineVersions((filterOptions.engine_versions?.length ? filterOptions.engine_versions : vers.map(v => String(v.engine_version))).filter(Boolean).sort().reverse());
        setStrategies((filterOptions.strategies?.length ? filterOptions.strategies : Array.from(new Set(active.map(s => s.strategy_name).filter(Boolean)))).sort());
        setAllRegimes((filterOptions.regimes?.length ? filterOptions.regimes : Array.from(new Set(active.map(s => s.regime).filter(Boolean)))).sort());
        setAllPatterns((filterOptions.patterns?.length ? filterOptions.patterns : Array.from(new Set(active.map(s => s.pattern).filter(Boolean)))).sort());
        setAllTimeframes((filterOptions.timeframes?.length ? filterOptions.timeframes : ['15m', '1h', '4h']).sort());
        setBinancePrices(prices);
        setMaxOpen(parseInt(appCfg['MAX_OPEN_TRADES'] || '10'));
      } catch (e) { console.error(e); setApiError(String(e)); }
      finally { setLoading(false); }
    })();
  }, [todayVN]);

  // Fetch backend aggregates when filters change
  useEffect(() => {
    (async () => {
      setLoading(true); setApiError('');
      try {
        const payload = buildAnalyticsFilter({
          start_date: appliedFilters.startDate,
          end_date: appliedFilters.endDate,
          date_field: 'exit_time',
          timeframes: appliedFilters.timeframe !== 'all' ? [appliedFilters.timeframe] : [],
          strategies: appliedFilters.strategy !== 'all' ? [appliedFilters.strategy] : [],
          patterns: appliedFilters.pattern !== 'all' ? [appliedFilters.pattern] : [],
          regimes: appliedFilters.regime !== 'all' ? [appliedFilters.regime] : [],
          directions: appliedFilters.direction !== 'all' ? [appliedFilters.direction] : [],
          engine_version: appliedFilters.engineVersion !== 'all' ? appliedFilters.engineVersion : 'all',
          engine_mode: 'only',
          score_min: appliedFilters.scoreMin ? Number(appliedFilters.scoreMin) : undefined,
          score_max: appliedFilters.scoreMax ? Number(appliedFilters.scoreMax) : undefined,
          include_manual: statusMode !== 'WL',
        });
        const { cap, psize } = parseCapPsize(appliedFilters.capPsize);
        const [overview, portfolio, breakdowns, recentTrades] = await Promise.all([
          fetchDashboardOverview(payload).catch(e => { console.error('overview:', e); return null; }),
          fetchDashboardPortfolio(payload, cap, psize).catch(e => { console.error('portfolio:', e); return null; }),
          fetchDashboardBreakdowns(payload).catch(e => { console.error('breakdowns:', e); return null; }),
          fetchDashboardRecentTrades(payload, recentTradesPage, 10, recentSearch).catch(e => { console.error('recent-trades:', e); return { data: [], total: 0, page: 1, limit: 10, pages: 1 }; }),
        ]);
        setOverviewData(overview);
        setPortfolioData(portfolio);
        setBreakdownsData(breakdowns);
        setRecentTradesData(recentTrades);
      } catch (e) {
        console.error(e);
        setApiError(String(e));
      } finally {
        setLoading(false);
      }
    })();
  }, [appliedFilters, statusMode, recentTradesPage, recentSearch, recentRefreshNonce]);

  // Auto-refresh realtime tables so Active drops out quickly when trades close.
  useEffect(() => {
    const iv = setInterval(() => {
      refreshRealtimeTables().catch(e => console.error('[Dashboard] realtime refresh failed:', e));
    }, 10000);
    return () => clearInterval(iv);
  }, []);

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
  const allOpen = useMemo(() => activeSignals.filter(s => s.status === 'OPEN').sort((a, b) => new Date(b.candle_time || 0).getTime() - new Date(a.candle_time || 0).getTime()), [activeSignals]);

  // ========== BACKEND DATA DERIVATIONS ==========
  const { cap: appliedCap, psize: appliedPsize } = parseCapPsize(appliedFilters.capPsize);

  // KPI from backend overview
  const totalTradesDisplay = overviewData?.total_trades || 0;
  const tradesTodayCount = overviewData?.trades_today || 0;
  const winsToday = overviewData?.wins_today || 0;
  const lossesToday = overviewData?.losses_today || 0;
  const winRateToday = overviewData?.win_rate_today || 0;
  const wins = overviewData?.wins || 0;
  const losses = overviewData?.losses || 0;
  const winRate = overviewData?.win_rate || 0;
  const profitFactor = overviewData?.profit_factor || 0;
  const expectancy = overviewData?.expectancy || 0;
  const tradeSharpe = overviewData?.sharpe || 0;
  const streaks = {
    candle: {
      maxWin: overviewData?.streaks?.candle?.max_win || overviewData?.streaks?.candle?.maxWin || 0,
      maxLoss: overviewData?.streaks?.candle?.max_loss || overviewData?.streaks?.candle?.maxLoss || 0,
    },
    exit: {
      maxWin: overviewData?.streaks?.exit?.max_win || overviewData?.streaks?.exit?.maxWin || 0,
      maxLoss: overviewData?.streaks?.exit?.max_loss || overviewData?.streaks?.exit?.maxLoss || 0,
    },
  };
  const longShortWR = {
    longWR: overviewData?.direction?.long?.win_rate || 0,
    longTotal: overviewData?.direction?.long?.total || 0,
    shortWR: overviewData?.direction?.short?.win_rate || 0,
    shortTotal: overviewData?.direction?.short?.total || 0,
  };
  const avgDuration = overviewData?.avg_duration_display || '-';

  // Portfolio from backend
  const normalizePortfolioMode = (mode) => ({
    nav: Number(mode?.final_nav ?? mode?.nav ?? 0),
    pnl: Number(mode?.total_pnl ?? mode?.pnl ?? 0),
    ret: Number(mode?.return_pct ?? mode?.ret ?? 0),
    maxDD: Number(mode?.max_dd_pct ?? mode?.maxDD ?? 0),
    maxGain: Number(mode?.max_gain_pct ?? mode?.maxGain ?? 0),
    peakNav: Number(mode?.peak_nav ?? mode?.peakNav ?? 0),
    troughNav: Number(mode?.trough_nav ?? mode?.troughNav ?? 0),
    sharpe: Number(mode?.sharpe ?? 0),
    calmar: Number(mode?.calmar ?? 0),
    curve: Array.isArray(mode?.curve) ? mode.curve : [],
  });
  const pComp = normalizePortfolioMode(portfolioData?.compounding);
  const pFixed = normalizePortfolioMode(portfolioData?.fixed);

  // Regime breakdown from backend
  const regimeBreakdown = useMemo(() => {
    if (!breakdownsData?.regime_breakdown) return [];
    return breakdownsData.regime_breakdown.map(r => ({
      regime: r.regime,
      trades: r.trades,
      wins: r.wins,
      winrate: r.win_rate,
      expectancy: r.expectancy,
      profitFactor: r.profit_factor,
      totalReturn: r.total_return,
    }));
  }, [breakdownsData]);

  // Heatmap from backend
  const heatmapData = useMemo(() => {
    if (!breakdownsData?.heatmap) return [];
    return breakdownsData.heatmap.map(h => ({
      x: h.timeframe,
      y: h.pattern,
      value: h.win_rate,
      count: h.count,
    }));
  }, [breakdownsData]);

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

  // ========== HANDLERS ==========
  // Total Unrealized P&L for Active Signals
  const totalUnrealizedPnL = useMemo(() => {
    return activeWithPrice.reduce((sum, s) => sum + (s.pnl || 0), 0);
  }, [activeWithPrice]);

  const handleCancelActive = async (id) => {
    if (!confirm('Close this signal?')) return;
    try {
      const res = await fetch(`${API}/signals/${id}/close`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed');
      toast.success('Signal closed');
      await refreshRealtimeTables();
      await refreshViewsAndRecent();
    } catch (e) { toast.error('Failed to close signal'); }
  };
  const handleCancelAllActive = async () => {
    if (!confirm('Close all active signals?')) return;
    try {
      const res = await fetch(`${API}/admin/cancel-all-active`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed');
      toast.success('All signals closed');
      await refreshRealtimeTables();
      await refreshViewsAndRecent();
    } catch (e) { toast.error('Failed to close all signals'); }
  };
  const handleCancelPending = async (id) => {
    if (!confirm('Cancel this pending?')) return;
    try {
      const res = await fetch(`${API}/pending/${id}/cancel`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed');
      toast.success('Pending cancelled');
      await refreshRealtimeTables();
    } catch (e) { toast.error('Failed to cancel pending'); }
  };
  const handleCancelAllPending = async () => {
    if (!confirm('Cancel all pending signals?')) return;
    try {
      const res = await fetch(`${API}/admin/cancel-all-pending`, { method: 'POST' });
      if (!res.ok) throw new Error('Failed');
      toast.success('All pending cancelled');
      await refreshRealtimeTables();
    } catch (e) { toast.error('Failed to cancel all pending'); }
  };

  // ========== TABLE COLUMNS ==========
  const activeColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: v => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'entry_price', header: 'Entry', render: v => fmtPrice(v) },
    { key: 'currentPrice', header: 'Current', render: (v, row) => (
      <span className={`font-mono transition-all duration-300 ${row.flash === 'up' ? 'text-emerald-400 bg-emerald-500/20 px-1 rounded' : row.flash === 'down' ? 'text-red-400 bg-red-500/20 px-1 rounded' : 'text-white'}`}>
        {fmtPrice(v)}
      </span>
    )},
    { key: 'stop_loss', header: 'SL', render: v => fmtPrice(v) },
    { key: 'take_profit', header: 'TP', render: v => fmtPrice(v) },
    { key: 'quantity', header: 'Qty', sortable: true, align: 'right', render: v => v ? Number(v).toFixed(4) : '-' },
    { key: 'pnl', header: 'P&L', sortable: true, render: v => <PercentChangeBadge value={v || 0} /> },
    { key: 'regime', header: 'Regime', sortable: true, render: v => <StatusBadge status={v || 'N/A'} /> },
    { key: 'score', header: 'Score', sortable: true, render: v => <ScoreCell value={v} /> },
    { key: 'candle_time', header: 'Opened', sortable: true, render: v => utcToVN(v) },
    { key: 'action', header: '', width: '50px', render: (_, row) => (
      <button onClick={() => handleCancelActive(row.id)} className="p-1.5 hover:bg-red-500/20 rounded transition-colors" title="Close signal">
        <X className="w-4 h-4 text-red-400" />
      </button>
    )}
  ];

  const pendingColumns = [
    { key: 'id', header: 'ID', width: '60px', render: v => <span className="text-slate-500">{v}</span> },
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: v => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'regime', header: 'Regime', sortable: true, render: v => <StatusBadge status={v || 'N/A'} /> },
    { key: 'trigger_price', header: 'Entry', render: v => fmtPrice(v) },
    { key: 'currentPrice', header: 'Current', render: (v, row) => (
      <span className={`font-mono transition-all duration-300 ${row.flash === 'up' ? 'text-emerald-400 bg-emerald-500/20 px-1 rounded' : row.flash === 'down' ? 'text-red-400 bg-red-500/20 px-1 rounded' : 'text-white'}`}>
        {fmtPrice(v)}
      </span>
    )},
    { key: 'stop_loss', header: 'SL', render: v => fmtPrice(v) },
    { key: 'take_profit', header: 'TP', render: v => fmtPrice(v) },
    { key: 'order_quantity', header: 'OrderQty', align: 'right', render: v => v ? Number(v).toFixed(4) : '-' },
    { key: 'executed_qty', header: 'ExeQty', align: 'right', render: v => v ? Number(v).toFixed(4) : '-' },
    { key: 'status', header: 'Status', sortable: true, render: v => <StatusBadge status={v} /> },
    { key: 'signal_score', header: 'Score', sortable: true, render: v => <ScoreCell value={v} /> },
    { key: 'exchange_status', header: 'EStatus', render: v => v || '-' },
    { key: 'placed_at', header: 'OrderAt', sortable: true, render: v => v ? utcToVN(v) : '-' },
    { key: 'action', header: '', width: '50px', render: (_, row) => (
      <button onClick={() => handleCancelPending(row.id)} className="p-1.5 hover:bg-red-500/20 rounded transition-colors" title="Cancel pending">
        <X className="w-4 h-4 text-red-400" />
      </button>
    )}
  ];

  const recentColumns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: v => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'entry_price', header: 'Entry', render: v => fmtPrice(v) },
    { key: 'exit_price', header: 'Exit', render: v => fmtPrice(v) },
    { key: 'stop_loss', header: 'SL', render: v => fmtPrice(v) },
    { key: 'take_profit', header: 'TP', render: v => fmtPrice(v) },
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
    { key: 'profitFactor', header: 'PF', sortable: true, align: 'right', render: v => isInfiniteMetric(v) ? 'Infinity' : v.toFixed(2) },
    { key: 'totalReturn', header: 'Total Return', sortable: true, render: v => <PercentChangeBadge value={v} /> },
  ];

  const $ = fmtMoney;
  const clr = v => v >= 0 ? 'text-emerald-400' : 'text-red-400';

  // ========== RENDER ==========
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">Performance Overview</h2>
          <p className="text-slate-400 mt-1">{loading ? 'Loading data...' : `Strategy analytics - ${appliedFilters.startDate} -> ${appliedFilters.endDate}`}</p>
        </div>
        <Button variant="ghost" icon={loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />} onClick={() => window.location.reload()}>Refresh</Button>
      </div>

      {apiError && <div className="px-4 py-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">Warning: {apiError}</div>}

      {/* OVERVIEW KPI */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Card className="flex items-center gap-4"><div className="p-3 bg-indigo-500/20 rounded-xl"><BarChart3 className="w-6 h-6 text-indigo-400" /></div><div><p className="text-sm text-slate-400">Total Trades</p><p className="text-2xl font-bold text-white">{totalTradesDisplay}</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-cyan-500/20 rounded-xl"><CalendarCheck className="w-6 h-6 text-cyan-400" /></div><div><p className="text-sm text-slate-400">Trades Today</p><p className="text-2xl font-bold text-white">{tradesTodayCount}</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-emerald-500/20 rounded-xl"><Target className="w-6 h-6 text-emerald-400" /></div><div><p className="text-sm text-slate-400">Today's Win Rate</p><p className={`text-2xl font-bold ${winRateToday >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{winRateToday.toFixed(1)}%</p><p className="text-xs text-slate-500">{winsToday} win / {lossesToday} loss</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-yellow-500/20 rounded-xl"><Zap className="w-6 h-6 text-yellow-400" /></div><div><p className="text-sm text-slate-400">Active Signals</p><p className="text-2xl font-bold text-white">{allOpen.length}</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-purple-500/20 rounded-xl"><Clock className="w-6 h-6 text-purple-400" /></div><div><p className="text-sm text-slate-400">Pending Signals</p><p className="text-2xl font-bold text-white">{pendingCount}</p></div></Card>
        <Card className="flex items-center gap-4"><div className="p-3 bg-orange-500/20 rounded-xl"><Filter className="w-6 h-6 text-orange-400" /></div><div><p className="text-sm text-slate-400">Open / Max</p><p className="text-2xl font-bold text-white">{allOpen.length} / {maxOpen}</p></div></Card>
      </div>

      {/* FILTERS */}
      <Card>
        <div className="flex items-center gap-2 mb-4"><Filter className="w-5 h-5 text-slate-400" /><h3 className="font-semibold text-white">Filters</h3><span className="text-xs text-slate-500 ml-2">- Metrics, Portfolio, Charts, Regime</span></div>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 lg:grid-cols-10 gap-3">
          <div className="flex items-end gap-1">
            <Input type="date" label="From" value={filters.startDate} onChange={e => setFilters({ ...filters, startDate: e.target.value })} />
            <button onClick={() => shiftDateRange(-1)} className="mb-2 px-2 py-1.5 bg-slate-700 hover:bg-slate-600 text-white rounded text-xs font-bold border border-slate-600 transition-colors" title="Shift range back 1 day">&lt;&lt;</button>
            <button onClick={() => shiftDateRange(1)} className="mb-2 px-2 py-1.5 bg-slate-700 hover:bg-slate-600 text-white rounded text-xs font-bold border border-slate-600 transition-colors" title="Shift range forward 1 day">&gt;&gt;</button>
          </div>
          <Input type="date" label="To" value={filters.endDate} onChange={e => setFilters({ ...filters, endDate: e.target.value })} className="flex-1" />
          <Select label="Strategy" value={filters.strategy} onChange={v => setFilterInstant('strategy', v)} options={[{ value: 'all', label: 'All' }, ...strategies.map(s => ({ value: s, label: s }))]} />
          <Select label="Pattern" value={filters.pattern} onChange={v => setFilterInstant('pattern', v)} options={[{ value: 'all', label: 'All' }, ...allPatterns.map(p => ({ value: p, label: p }))]} />
          <Select label="Direction" value={filters.direction} onChange={v => setFilterInstant('direction', v)} options={[{ value: 'all', label: 'All' }, { value: 'LONG', label: 'LONG' }, { value: 'SHORT', label: 'SHORT' }]} />
          <Select label="Regime" value={filters.regime} onChange={v => setFilterInstant('regime', v)} options={[{ value: 'all', label: 'All' }, ...allRegimes.map(r => ({ value: r, label: r }))]} />
          <Select label="TF" value={filters.timeframe} onChange={v => setFilterInstant('timeframe', v)} options={[{ value: 'all', label: 'All' }, ...allTimeframes.map(tf => ({ value: tf, label: tf }))]} />
          <Select label="Score" value={getScorePreset()} onChange={setScoreFilter} options={[{ value: 'all', label: 'All' }, { value: '6-7', label: '6 ~ 7' }, { value: '7-8', label: '7 ~ 8' }, { value: '8-9', label: '8 ~ 9' }, { value: '9-10', label: '9 ~ 10' }]} />
          <Input type="text" label="CAP / PSize($)" value={filters.capPsize} onChange={e => setFilters({ ...filters, capPsize: e.target.value })} placeholder="10000|1000" />
          <div className="flex items-end gap-2">
            <button onClick={() => setStatusMode(statusMode === 'WL' ? 'ALL' : 'WL')} className={`px-3 py-2 rounded-lg text-xs font-bold border transition-colors ${statusMode === 'WL' ? 'bg-indigo-600 text-white border-indigo-500' : 'bg-orange-600 text-white border-orange-500'}`} title={statusMode === 'WL' ? 'WIN/LOSS only' : 'All statuses (derived)'}>{statusMode}</button>
            <Button variant="primary" onClick={handleApply}>Apply</Button>
          </div>
        </div>
      </Card>

      {/* METRICS + PORTFOLIO */}
      <div className={`grid grid-cols-1 ${isBotDashboard ? 'lg:grid-cols-2' : 'lg:grid-cols-3'} gap-6`}>
        {/* Strategy Metrics */}
        <Card>
          <div className="flex items-center justify-between mb-4">
            <div><h3 className="text-lg font-semibold text-white">Strategy Metrics</h3><p className="text-sm text-slate-400">Trade-Level</p></div>
          </div>
          <div className="space-y-3">
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Win / Loss / WinRate</span><span className="font-bold"><span className="text-emerald-400">{wins}</span> / <span className="text-red-400">{losses}</span> / <span className={winRate >= 50 ? 'text-emerald-400' : 'text-red-400'}>{winRate.toFixed(1)}%</span></span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Profit Factor</span><span className={`font-bold ${profitFactor >= 1 ? 'text-emerald-400' : 'text-red-400'}`}>{isInfiniteMetric(profitFactor) ? 'Infinity' : profitFactor.toFixed(2)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Expectancy</span><span className={`font-bold ${clr(expectancy)}`}>{expectancy.toFixed(2)}%</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Sharpe</span><span className="font-bold text-white">{tradeSharpe.toFixed(2)}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Max Loss Streak</span><span className="font-bold text-red-400">{streaks.candle.maxLoss} / {streaks.exit.maxLoss}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Max Win Streak</span><span className="font-bold text-emerald-400">{streaks.candle.maxWin} / {streaks.exit.maxWin}</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Long Win Rate</span><span className={`font-bold ${longShortWR.longWR >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{longShortWR.longWR.toFixed(1)}%</span></div>
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Short Win Rate</span><span className={`font-bold ${longShortWR.shortWR >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{longShortWR.shortWR.toFixed(1)}%</span></div>
            <div className="flex justify-between py-2"><span className="text-slate-400">Avg Duration</span><span className="font-bold text-white">{avgDuration}</span></div>
          </div>
        </Card>

        {!isBotDashboard && (
          <Card>
            <CardHeader title="Portfolio (Compounding)" subtitle={`Size = $${appliedPsize} x (NAV/$${appliedCap.toLocaleString()})`} />
            <div className="space-y-3">
              <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Initial Capital</span><span className="font-bold text-white">${appliedCap.toLocaleString()}</span></div>
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
        )}

        {/* Portfolio Fixed */}
        <Card>
          <CardHeader title={`Portfolio (Fixed $${appliedPsize})`} subtitle={`Size always = $${appliedPsize}`} />
          <div className="space-y-3">
            <div className="flex justify-between py-2 border-b border-slate-700"><span className="text-slate-400">Initial Capital</span><span className="font-bold text-white">${appliedCap.toLocaleString()}</span></div>
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
        <CardHeader title="Equity Curve" subtitle="Hover for details - Compounding vs Fixed" />
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

      {/* ACTIVE (UNFILTERED) */}
      <Card>
        <CardHeader
          title="Active Signals"
          subtitle={`${allOpen.length} open - P&L: ${totalUnrealizedPnL >= 0 ? '+' : ''}${totalUnrealizedPnL.toFixed(2)}% - Live 10s`}
          action={
            <div className="flex items-center gap-3">
              <span className="text-xs text-emerald-400 animate-pulse">Live</span>
              <Button variant="danger" size="sm" onClick={handleCancelAllActive} icon={<X className="w-4 h-4" />}>Close All</Button>
            </div>
          }
        />
        <DataTable columns={activeColumns} data={activeWithPrice} pageSize={10} emptyMessage="No active signals" onRowClick={handleRecentTradeClick} />
      </Card>

      {/* PENDING SIGNALS (WAIT) */}
      <Card>
        <CardHeader
          title="Pending Signals"
          subtitle={`${pendingSignals.length} waiting - Trigger price orders`}
          action={
            <div className="flex items-center gap-3">
              <span className="text-xs text-yellow-400">Pending</span>
              <Button variant="danger" size="sm" onClick={handleCancelAllPending} icon={<X className="w-4 h-4" />}>Cancel All</Button>
            </div>
          }
        />
        <DataTable columns={pendingColumns} data={pendingWithPrice} pageSize={10} emptyMessage="No pending signals" />
      </Card>

      {/* RECENT (BACKEND PAGINATED) */}
      <Card>
        <CardHeader
          title="Recent Trades"
          subtitle={`${recentTradesData.data.length} / ${recentTradesData.total} closed trades - Page ${recentTradesData.page} of ${recentTradesData.pages}`}
          action={
            <Input
              type="text"
              placeholder="Search symbols e.g. BTC ETH"
              value={recentSearch}
              onChange={e => setRecentSearch(e.target.value)}
              className="w-full sm:w-52"
            />
          }
        />
        <DataTable
          columns={recentColumns}
          data={recentTradesData.data}
          pageSize={10}
          emptyMessage="No closed trades"
          onRowClick={handleRecentTradeClick}
          pagination={{
            total: recentTradesData.total,
            page: recentTradesData.page,
            limit: recentTradesData.limit,
            pages: recentTradesData.pages,
            onPageChange: setRecentTradesPage,
          }}
        />
      </Card>

      {/* REGIME */}
      <Card>
        <CardHeader title="Regime Breakdown" subtitle="Filtered" />
        {regimeBreakdown.length > 0 ? <DataTable columns={regimeColumns} data={regimeBreakdown} pageSize={5} /> : <div className="h-48 flex items-center justify-center text-slate-500">No data</div>}
      </Card>

      {/* HEATMAP (UNFILTERED) */}
      <Card>
        <CardHeader title="Pattern x Timeframe Heatmap" subtitle="All data" />
        {heatmapData.length > 0 ? <Heatmap data={heatmapData} xLabel="Timeframe" yLabel="Pattern" valueLabel="Win Rate %" colorScale="green-red" showValues /> : <div className="h-64 flex items-center justify-center text-slate-500">No data</div>}
      </Card>
      {selectedTrade && (
        <TradeDetailModal
          trade={selectedTrade}
          klines={selectedTradeKlines}
          loadingKlines={tradeKlineLoading}
          onClose={() => {
            selectedTradeKeyRef.current = '';
            setSelectedTrade(null);
            setSelectedTradeKlines([]);
            setTradeKlineLoading(false);
          }}
        />
      )}
    </div>
  );
}
