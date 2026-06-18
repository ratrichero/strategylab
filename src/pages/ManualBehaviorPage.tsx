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
import { parseUtcMs, utcToVN, getTodayVN, normalizeSignalDates } from '../utils/time';

const API = '/api';
const VN_MS = 7 * 3600 * 1000;

function exitToVNDate(exitTime) {
  if (!exitTime) return '';
  const ms = parseUtcMs(exitTime);
  if (!ms) return '';
  const vn = new Date(ms + VN_MS);
  return `${vn.getUTCFullYear()}-${String(vn.getUTCMonth()+1).padStart(2,'0')}-${String(vn.getUTCDate()).padStart(2,'0')}`;
}

/** Derive WIN/LOSS from entry, exit, direction for non-WIN/LOSS statuses */
function deriveOutcome(s) {
  const entry = Number(s.entry_price) || 0;
  const exit = Number(s.exit_price) || 0;
  if (!entry || !exit) return { derivedStatus: s.status, derivedPnl: s.result_percent || 0 };

  const pnl = s.direction === 'LONG'
    ? ((exit - entry) / entry) * 100
    : ((entry - exit) / entry) * 100;

  return {
    derivedStatus: pnl >= 0 ? 'WIN' : 'LOSS',
    derivedPnl: pnl,
  };
}

export function ManualBehaviorPage() {
  const todayVN = getTodayVN();
  const [allSignals, setAllSignals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filters, setFilters] = useState({
    startDate: '', endDate: '', timeframe: 'all', strategy: 'all',
    regime: 'all', pattern: 'all', direction: 'all', statusView: 'all',
  });
  const [applied, setApplied] = useState({ ...filters });
  const set = (k, v) => setFilters(prev => ({ ...prev, [k]: v }));

  const [strategies, setStrategies] = useState([]);
  const [regimes, setRegimes] = useState([]);
  const [patterns, setPatterns] = useState([]);

  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        const res = await fetch(`${API}/signals?limit=10000`).then(r => r.json()).catch(() => ({ data: [] }));
        const sigs = (res.data || []).map(normalizeSignalDates);
        setAllSignals(sigs);
        setStrategies(Array.from(new Set(sigs.map(s => s.strategy_name).filter(Boolean))).sort());
        setRegimes(Array.from(new Set(sigs.map(s => s.regime).filter(Boolean))).sort());
        setPatterns(Array.from(new Set(sigs.map(s => s.pattern).filter(Boolean))).sort());
      } catch (e) { console.error(e); }
      finally { setLoading(false); }
    })();
  }, []);

  // All closed signals (WIN + LOSS + MANUAL + any other closed status)
  const allClosed = useMemo(() => {
    return allSignals.filter(s => s.status !== 'OPEN' && s.exit_time);
  }, [allSignals]);

  // Enrich with derived outcome
  const enriched = useMemo(() => {
    return allClosed.map(s => {
      const isStandard = s.status === 'WIN' || s.status === 'LOSS';
      const { derivedStatus, derivedPnl } = isStandard
        ? { derivedStatus: s.status, derivedPnl: s.result_percent || 0 }
        : deriveOutcome(s);
      return {
        ...s,
        originalStatus: s.status,
        derivedStatus,
        derivedPnl,
        isManual: !isStandard,
        actualPnl: s.result_percent || 0,
        plannedPnl: derivedPnl,
      };
    });
  }, [allClosed]);

  // Unique non-standard statuses
  const uniqueStatuses = useMemo(() => {
    return Array.from(new Set(enriched.filter(s => s.isManual).map(s => s.originalStatus))).sort();
  }, [enriched]);

  // Filtered
  const filtered = useMemo(() => {
    const af = applied;
    return enriched.filter(s => {
      // Status view filter
      if (af.statusView === 'unique' && !s.isManual) return false;
      if (af.statusView !== 'all' && af.statusView !== 'unique' && s.originalStatus !== af.statusView) return false;

      // Date filter
      if (af.startDate || af.endDate) {
        const vnDate = exitToVNDate(s.exit_time);
        if (!vnDate) return false;
        if (af.startDate && vnDate < af.startDate) return false;
        if (af.endDate && vnDate > af.endDate) return false;
      }

      if (af.timeframe !== 'all' && s.timeframe !== af.timeframe) return false;
      if (af.strategy !== 'all' && s.strategy_name !== af.strategy) return false;
      if (af.regime !== 'all' && s.regime !== af.regime) return false;
      if (af.pattern !== 'all' && s.pattern !== af.pattern) return false;
      if (af.direction !== 'all' && s.direction !== af.direction) return false;
      return true;
    });
  }, [enriched, applied]);

  // KPI
  const kpi = useMemo(() => {
    const total = filtered.length;
    const manualCount = filtered.filter(s => s.isManual).length;
    const wins = filtered.filter(s => s.derivedStatus === 'WIN').length;
    const wr = total > 0 ? (wins / total) * 100 : 0;

    const manualSignals = filtered.filter(s => s.isManual);
    const manualWins = manualSignals.filter(s => s.derivedStatus === 'WIN').length;
    const manualWR = manualSignals.length > 0 ? (manualWins / manualSignals.length) * 100 : 0;

    // Impact: avg result of manual vs avg result of standard
    const stdSignals = filtered.filter(s => !s.isManual);
    const avgStdPnl = stdSignals.length > 0 ? stdSignals.reduce((a, s) => a + s.actualPnl, 0) / stdSignals.length : 0;
    const avgManualPnl = manualSignals.length > 0 ? manualSignals.reduce((a, s) => a + s.actualPnl, 0) / manualSignals.length : 0;

    // Planned vs actual for manual signals
    const plannedTotal = manualSignals.reduce((a, s) => a + Math.abs(s.derivedPnl), 0);
    const actualTotal = manualSignals.reduce((a, s) => a + s.actualPnl, 0);

    return {
      total, manualCount, wins, wr, manualWR, manualWins,
      manualTotal: manualSignals.length,
      avgStdPnl, avgManualPnl,
      plannedTotal, actualTotal,
      impact: avgManualPnl - avgStdPnl,
    };
  }, [filtered]);

  const handleApply = () => setApplied({ ...filters });

  const columns = [
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: v => <DirectionBadge direction={v || 'LONG'} /> },
    { key: 'timeframe', header: 'TF', sortable: true },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'entry_price', header: 'Entry', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'exit_price', header: 'Exit', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'actualPnl', header: 'Actual %', sortable: true, render: v => <PercentChangeBadge value={v || 0} /> },
    { key: 'originalStatus', header: 'Status', sortable: true, render: v => <StatusBadge status={v} /> },
    { key: 'derivedStatus', header: 'Derived', sortable: true, render: v => <StatusBadge status={v} /> },
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
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-3">
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
        <div className="grid grid-cols-2 md:grid-cols-5 lg:grid-cols-9 gap-3">
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
          <CardHeader title="Standard Signals (WIN/LOSS)" subtitle={`${filtered.filter(s => !s.isManual).length} signals`} />
          <div className="space-y-3">
            {(() => {
              const std = filtered.filter(s => !s.isManual);
              const w = std.filter(s => s.derivedStatus === 'WIN').length;
              const wr = std.length > 0 ? (w / std.length) * 100 : 0;
              const avgPnl = std.length > 0 ? std.reduce((a, s) => a + s.actualPnl, 0) / std.length : 0;
              const gp = std.filter(s => s.actualPnl > 0).reduce((a, s) => a + s.actualPnl, 0);
              const gl = Math.abs(std.filter(s => s.actualPnl < 0).reduce((a, s) => a + s.actualPnl, 0));
              const pf = gl > 0 ? gp / gl : gp > 0 ? Infinity : 0;
              return [
                ['Total', std.length], ['Wins', w], ['Win Rate', `${wr.toFixed(1)}%`],
                ['Avg PnL', `${avgPnl >= 0 ? '+' : ''}${avgPnl.toFixed(2)}%`],
                ['Profit Factor', pf === Infinity ? '∞' : pf.toFixed(2)],
              ].map(([l, v]) => (
                <div key={l} className="flex justify-between py-2 border-b border-slate-700 last:border-0">
                  <span className="text-slate-400">{l}</span><span className="font-bold text-white">{v}</span>
                </div>
              ));
            })()}
          </div>
        </Card>

        <Card>
          <CardHeader title="Manual Signals (Derived)" subtitle={`${filtered.filter(s => s.isManual).length} signals`} />
          <div className="space-y-3">
            {(() => {
              const man = filtered.filter(s => s.isManual);
              const w = man.filter(s => s.derivedStatus === 'WIN').length;
              const wr = man.length > 0 ? (w / man.length) * 100 : 0;
              const avgPnl = man.length > 0 ? man.reduce((a, s) => a + s.actualPnl, 0) / man.length : 0;
              const gp = man.filter(s => s.actualPnl > 0).reduce((a, s) => a + s.actualPnl, 0);
              const gl = Math.abs(man.filter(s => s.actualPnl < 0).reduce((a, s) => a + s.actualPnl, 0));
              const pf = gl > 0 ? gp / gl : gp > 0 ? Infinity : 0;
              return [
                ['Total', man.length], ['Derived Wins', w], ['Derived WR', `${wr.toFixed(1)}%`],
                ['Avg Actual PnL', `${avgPnl >= 0 ? '+' : ''}${avgPnl.toFixed(2)}%`],
                ['Profit Factor', pf === Infinity ? '∞' : pf.toFixed(2)],
              ].map(([l, v]) => (
                <div key={l} className="flex justify-between py-2 border-b border-slate-700 last:border-0">
                  <span className="text-slate-400">{l}</span><span className="font-bold text-white">{v}</span>
                </div>
              ));
            })()}
          </div>
        </Card>
      </div>

      {/* Table */}
      <Card>
        <CardHeader title="Signal Details" subtitle={`${filtered.length} signals — Derived = WIN/LOSS based on entry/exit/direction`} />
        <DataTable columns={columns} data={[...filtered].sort((a, b) => parseUtcMs(b.exit_time) - parseUtcMs(a.exit_time))} pageSize={20} emptyMessage="No signals found" />
      </Card>
    </div>
  );
}
