// @ts-nocheck
/* eslint-disable */
import { useState, useMemo, useEffect } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Select } from '../components/ui/Select';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { DataTable } from '../components/ui/Table';
import { DirectionBadge, PercentChangeBadge, StatusBadge } from '../components/ui/Badge';
import { Loader2, UserX, RefreshCw } from 'lucide-react';
import { parseUtcMs, utcToVN, getTodayVN } from '../utils/time';
import { manualApi } from '../services/manualApi';

const VN_MS = 7 * 3600 * 1000;

function exitToVNDate(exitTime) {
  if (!exitTime) return '';
  const ms = parseUtcMs(exitTime);
  if (!ms) return '';
  const vn = new Date(ms + VN_MS);
  return `${vn.getUTCFullYear()}-${String(vn.getUTCMonth()+1).padStart(2,'0')}-${String(vn.getUTCDate()).padStart(2,'0')}`;
}

export function ManualBehaviorPage() {
  const todayVN = getTodayVN();
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    startDate: '', endDate: '', timeframe: 'all', strategy: 'all',
    regime: 'all', pattern: 'all', direction: 'all', statusView: 'all',
  });
  const [applied, setApplied] = useState({ ...filters });
  const set = (k, v) => setFilters(prev => ({ ...prev, [k]: v }));

  const [overviewData, setOverviewData] = useState(null);
  const [comparisonData, setComparisonData] = useState(null);
  const [tradesData, setTradesData] = useState([]);
  const [tradesTotal, setTradesTotal] = useState(0);
  const [tradesPage, setTradesPage] = useState(1);

  const [strategies, setStrategies] = useState([]);
  const [regimes, setRegimes] = useState([]);
  const [patterns, setPatterns] = useState([]);

  // Load filter options
  useEffect(() => {
    (async () => {
      try {
        const res = await fetch('/api/filter-options').then(r => r.json()).catch(() => ({ strategies: [], patterns: [], regimes: [] }));
        setStrategies(res.strategies || []);
        setRegimes(res.regimes || []);
        setPatterns(res.patterns || []);
      } catch (e) { console.error(e); }
    })();
  }, []);

  // Load data when filters change
  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const filterParams = buildAnalysisParams();
        const [overview, comparison, trades] = await Promise.all([
          manualApi.fetchOverview(filterParams).catch(() => null),
          manualApi.fetchComparison(filterParams).catch(() => null),
          manualApi.fetchTrades({ ...filterParams, page: tradesPage, limit: 20, search_symbols: '', sort_by: 'exit_time', sort_order: 'desc' }).catch(() => ({ data: [], total: 0 })),
        ]);
        setOverviewData(overview);
        setComparisonData(comparison);
        setTradesData(trades.data || []);
        setTradesTotal(trades.total || 0);
      } catch (e) { console.error(e); }
      finally { setLoading(false); }
    })();
  }, [applied, tradesPage]);

  const buildAnalysisParams = () => {
    const af = applied;
    const p: any = {};
    if (af.startDate) p.start_date = af.startDate;
    if (af.endDate) p.end_date = af.endDate;
    if (af.timeframe !== 'all') p.timeframes = [af.timeframe];
    if (af.strategy !== 'all') p.strategies = [af.strategy];
    if (af.regime !== 'all') p.regimes = [af.regime];
    if (af.pattern !== 'all') p.patterns = [af.pattern];
    if (af.direction !== 'all') p.directions = [af.direction];
    return p;
  };

  // KPI from backend
  const kpi = useMemo(() => {
    if (!overviewData) {
      return {
        total: 0, manualCount: 0, wins: 0, wr: 0, manualWR: 0, manualWins: 0,
        manualTotal: 0, avgStdPnl: 0, avgManualPnl: 0, plannedTotal: 0, actualTotal: 0, impact: 0,
      };
    }
    return {
      total: overviewData.total,
      manualCount: overviewData.manual_count,
      wins: overviewData.wins,
      wr: overviewData.win_rate,
      manualWR: overviewData.manual_win_rate,
      manualWins: overviewData.manual_wins,
      manualTotal: overviewData.manual_count,
      avgStdPnl: overviewData.avg_std_pnl,
      avgManualPnl: overviewData.avg_manual_pnl,
      plannedTotal: overviewData.planned_total,
      actualTotal: overviewData.actual_total,
      impact: overviewData.impact,
    };
  }, [overviewData]);

  // Unique statuses from trades data
  const uniqueStatuses = useMemo(() => {
    return Array.from(new Set(tradesData.filter(s => s.is_manual).map(s => s.status))).sort();
  }, [tradesData]);

  const handleApply = () => setApplied({ ...filters });

  const columns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: v => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'entry_price', header: 'Entry', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'exit_price', header: 'Exit', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'derived_pnl', header: 'Actual %', sortable: true, render: v => <PercentChangeBadge value={v || 0} /> },
    { key: 'status', header: 'Status', sortable: true, render: v => <StatusBadge status={v} /> },
    { key: 'derived_status', header: 'Derived', sortable: true, render: v => <StatusBadge status={v} /> },
    { key: 'regime', header: 'Regime', sortable: true, render: v => <StatusBadge status={v || 'N/A'} /> },
    { key: 'score', header: 'Score', sortable: true, render: v => {
      const n = Number(v) || 0;
      return <span className={`font-mono text-sm ${n >= 8 ? 'text-emerald-400' : n >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>{n.toFixed(2)}</span>;
    }},
    { key: 'exit_time', header: 'Closed', sortable: true, render: v => utcToVN(v) },
  ];

  const clr = v => v >= 0 ? 'text-emerald-400' : 'text-red-400';

  if (loading) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin text-indigo-500" /></div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <UserX className="w-7 h-7 text-orange-400" />
        <div>
          <h2 className="text-2xl font-bold text-white">Manual Behavior Analysis</h2>
          <p className="text-slate-400 mt-0.5">Impact of manual interventions (Kill Switch, Manual Close)</p>
        </div>
      </div>

      {/* KPI */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Total Signals</p><p className="text-2xl font-bold text-white">{kpi.total}</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Manual Count</p><p className="text-2xl font-bold text-orange-400">{kpi.manualCount}</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Overall WR (Derived)</p><p className={`text-2xl font-bold ${kpi.wr >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{kpi.wr.toFixed(1)}%</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Manual WR (Derived)</p><p className={`text-2xl font-bold ${kpi.manualWR >= 50 ? 'text-emerald-400' : 'text-red-400'}`}>{kpi.manualWR.toFixed(1)}%</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Avg Manual PnL</p><p className={`text-2xl font-bold ${clr(kpi.avgManualPnl)}`}>{kpi.avgManualPnl >= 0 ? '+' : ''}{kpi.avgManualPnl.toFixed(2)}%</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Impact vs Std</p><p className={`text-2xl font-bold ${clr(kpi.impact)}`}>{kpi.impact >= 0 ? '+' : ''}{kpi.impact.toFixed(2)}%</p></Card>
      </div>

      {/* Filters */}
      <Card>
        <div className="flex items-center gap-2 mb-4"><span className="text-sm font-semibold text-white">Filters</span></div>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 lg:grid-cols-9 gap-3">
          <Input type="date" label="From" value={filters.startDate} onChange={e => set('startDate', e.target.value)} />
          <Input type="date" label="To" value={filters.endDate} onChange={e => set('endDate', e.target.value)} />
          <Select label="Status View" value={filters.statusView} onChange={v => set('statusView', v)} options={[
            { value: 'all', label: 'All (Derived)' },
            { value: 'unique', label: 'Non-WIN/LOSS Only' },
            ...uniqueStatuses.map(s => ({ value: s, label: s })),
          ]} />
          <Select label="Strategy" value={filters.strategy} onChange={v => set('strategy', v)} options={[{ value: 'all', label: 'All' }, ...strategies.map(s => ({ value: s, label: s }))]} />
          <Select label="Pattern" value={filters.pattern} onChange={v => set('pattern', v)} options={[{ value: 'all', label: 'All' }, ...patterns.map(p => ({ value: p, label: p }))]} />
          <Select label="Direction" value={filters.direction} onChange={v => set('direction', v)} options={[{ value: 'all', label: 'All' }, { value: 'LONG', label: 'LONG' }, { value: 'SHORT', label: 'SHORT' }]} />
          <Select label="Regime" value={filters.regime} onChange={v => set('regime', v)} options={[{ value: 'all', label: 'All' }, ...regimes.map(r => ({ value: r, label: r }))]} />
          <Select label="TF" value={filters.timeframe} onChange={v => set('timeframe', v)} options={[{ value: 'all', label: 'All' }, { value: '15m', label: '15m' }, { value: '1h', label: '1h' }, { value: '4h', label: '4h' }]} />
          <div className="flex items-end"><Button variant="primary" onClick={handleApply} className="w-full">Apply</Button></div>
        </div>
      </Card>

      {/* Comparison cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader title="Standard Signals (WIN/LOSS)" subtitle={`${comparisonData?.standard?.total || 0} signals`} />
          <div className="space-y-3">
            {comparisonData?.standard ? [
              ['Total', comparisonData.standard.total], ['Wins', comparisonData.standard.wins], ['Win Rate', `${comparisonData.standard.win_rate.toFixed(1)}%`],
              ['Avg PnL', `${comparisonData.standard.avg_pnl >= 0 ? '+' : ''}${comparisonData.standard.avg_pnl.toFixed(2)}%`],
              ['Profit Factor', comparisonData.standard.profit_factor === Infinity ? '∞' : comparisonData.standard.profit_factor.toFixed(2)],
            ].map(([l, v]) => (
              <div key={l} className="flex justify-between py-2 border-b border-slate-700 last:border-0">
                <span className="text-slate-400">{l}</span><span className="font-bold text-white">{v}</span>
              </div>
            )) : null}
          </div>
        </Card>

        <Card>
          <CardHeader title="Manual Signals (Derived)" subtitle={`${comparisonData?.manual?.total || 0} signals`} />
          <div className="space-y-3">
            {comparisonData?.manual ? [
              ['Total', comparisonData.manual.total], ['Derived Wins', comparisonData.manual.wins], ['Derived WR', `${comparisonData.manual.win_rate.toFixed(1)}%`],
              ['Avg Actual PnL', `${comparisonData.manual.avg_pnl >= 0 ? '+' : ''}${comparisonData.manual.avg_pnl.toFixed(2)}%`],
              ['Profit Factor', comparisonData.manual.profit_factor === Infinity ? '∞' : comparisonData.manual.profit_factor.toFixed(2)],
            ].map(([l, v]) => (
              <div key={l} className="flex justify-between py-2 border-b border-slate-700 last:border-0">
                <span className="text-slate-400">{l}</span><span className="font-bold text-white">{v}</span>
              </div>
            )) : null}
          </div>
        </Card>
      </div>

      {/* Table */}
      <Card>
        <CardHeader title="Signal Details" subtitle={`${tradesTotal} signals — Derived = WIN/LOSS based on entry/exit/direction`} />
        <DataTable 
          columns={columns} 
          data={tradesData} 
          pageSize={20} 
          total={tradesTotal}
          page={tradesPage}
          onPageChange={setTradesPage}
          emptyMessage="No signals found" 
        />
      </Card>
    </div>
  );
}
