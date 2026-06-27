// @ts-nocheck
/* eslint-disable */
import { useState, useMemo, useEffect } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Select } from '../components/ui/Select';
import { DataTable } from '../components/ui/Table';
import { StatusBadge, DirectionBadge } from '../components/ui/Badge';
import { Loader2, Clock } from 'lucide-react';
import { parseUtcMs, utcToVN, getTodayVN, normalizeSignalDates } from '../utils/time';

const API = '/api';
const VN_MS = 7 * 3600 * 1000;

/** Convert created_at UTC → VN date string "YYYY-MM-DD" */
function createdToVNDate(createdAt) {
  if (!createdAt) return '';
  const ms = parseUtcMs(createdAt);
  if (!ms) return '';
  const vn = new Date(ms + VN_MS);
  return `${vn.getUTCFullYear()}-${String(vn.getUTCMonth()+1).padStart(2,'0')}-${String(vn.getUTCDate()).padStart(2,'0')}`;
}

function renderRejectReason(reason) {
  if (!reason) return '-';

  return (
    <span
      className="block max-w-[340px] whitespace-normal break-words font-mono text-[11px] leading-4 text-slate-300"
      title={reason}
    >
      {reason}
    </span>
  );
}

export function PendingSignalsPage() {
  const today = getTodayVN();
  const [loading, setLoading] = useState(true);
  const [pendingSignals, setPendingSignals] = useState([]);
  const [allStrategies, setAllStrategies] = useState([]);
  const [allPatterns, setAllPatterns] = useState([]);
  const [allRegimes, setAllRegimes] = useState([]);

  const [f, setF] = useState({
    startDate: '', endDate: '', status: 'all', rejectReason: 'all', exchangeStatus: 'all',
    symbols: '', symbolMode: 'include',
    timeframes: [], strategies: [], patterns: [], regimes: [], directions: [],
    engineVersion: 'all', engineMode: 'only', scoreMin: 0, scoreMax: 10
  });
  const [applied, setApplied] = useState({ ...f });
  const set = (k, v) => setF(prev => ({ ...prev, [k]: v }));
  const toggleArr = (k, v) => setF(prev => {
    const arr = prev[k];
    return { ...prev, [k]: arr.includes(v) ? arr.filter(x => x !== v) : [...arr, v] };
  });

  // Load all pending signals
  useEffect(() => {
    (async () => {
      setLoading(true);
      try {
        // Default: filter by today
        const res = await fetch(`${API}/pending-signals?limit=10000`).then(r => r.json()).catch(() => ({ data: [] }));
        const signals = (res.data || []).map(normalizeSignalDates);
        setPendingSignals(signals);
        setAllStrategies(Array.from(new Set(signals.map(s => s.strategy_name).filter(Boolean))).sort());
        setAllPatterns(Array.from(new Set(signals.map(s => s.pattern).filter(Boolean))).sort());
        setAllRegimes(Array.from(new Set(signals.map(s => s.regime).filter(Boolean))).sort());
        // Set default date filter to today
        setF(prev => ({ ...prev, startDate: today, endDate: today }));
        setApplied(prev => ({ ...prev, startDate: today, endDate: today }));
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  // Local filtering from pendingSignals
  const filtered = useMemo(() => {
    return pendingSignals.filter(s => {
      const c = applied;
      // VN date range filter
      if (c.startDate || c.endDate) {
        const vnDate = createdToVNDate(s.created_at);
        if (!vnDate) return false;
        if (c.startDate && vnDate < c.startDate) return false;
        if (c.endDate && vnDate > c.endDate) return false;
      }
      // Status filter
      if (c.status !== 'all' && s.status !== c.status) return false;
      // Reject reason filter (match prefix)
      if (c.rejectReason !== 'all' && s.rejection_reason) {
        const prefix = s.rejection_reason.split('::')[0];
        if (prefix !== c.rejectReason) return false;
      } else if (c.rejectReason !== 'all' && !s.rejection_reason) {
        return false;
      }
      // Exchange status filter
      if (c.exchangeStatus !== 'all' && s.exchange_status !== c.exchangeStatus) return false;
      // Symbol filter
      if (c.symbols?.trim()) {
        const list = c.symbols.replace(/,/g, ' ').split(/\s+/).map(s => s.trim().toUpperCase()).filter(Boolean).map(s => s.endsWith('USDT') ? s : s + 'USDT');
        if (list.length) {
          const match = list.includes(s.symbol);
          if (c.symbolMode === 'include' ? !match : match) return false;
        }
      }
      // Score filter
      const score = Number(s.signal_score) || 0;
      if (c.scoreMin > 0 && score < c.scoreMin) return false;
      if (c.scoreMax < 10 && score > c.scoreMax) return false;
      // Engine filter
      if (c.engineVersion !== 'all') {
        if (c.engineMode === 'newest' && Number(s.engine_version) < Number(c.engineVersion)) return false;
        if (c.engineMode === 'older' && Number(s.engine_version) > Number(c.engineVersion)) return false;
        if (c.engineMode === 'only' && String(s.engine_version) !== c.engineVersion) return false;
      }
      // Array filters
      if (c.timeframes.length && !c.timeframes.includes(s.timeframe)) return false;
      if (c.strategies.length && !c.strategies.includes(s.strategy_name)) return false;
      if (c.patterns.length && !c.patterns.includes(s.pattern)) return false;
      if (c.regimes.length && !c.regimes.includes(s.regime)) return false;
      if (c.directions.length && !c.directions.includes(s.direction)) return false;
      return true;
    });
  }, [pendingSignals, applied]);

  // KPI counts
  const kpi = useMemo(() => {
    const counts = { WAIT: 0, FILLED: 0, REJECTED: 0, CANCELLED: 0 };
    pendingSignals.forEach(s => {
      if (counts[s.status] !== undefined) counts[s.status]++;
    });
    return { total: pendingSignals.length, ...counts };
  }, [pendingSignals]);

  // Get unique rejection reasons (grouped by prefix)
  const allRejectReasons = useMemo(() => {
    const reasons = new Set();
    pendingSignals.forEach(s => {
      if (s.rejection_reason) {
        // Group by prefix (e.g., "PREFILL:" from "PREFILL::whitelist::not_in_whitelist")
        const parts = s.rejection_reason.split('::');
        reasons.add(parts[0]);
      }
    });
    return Array.from(reasons).sort();
  }, [pendingSignals]);

  // Get unique exchange statuses
  const allExchangeStatuses = useMemo(() => {
    const statuses = new Set();
    pendingSignals.forEach(s => {
      if (s.exchange_status) statuses.add(s.exchange_status);
    });
    return Array.from(statuses).sort();
  }, [pendingSignals]);

  const handleApply = () => setApplied({ ...f });

  const columns = [
    { key: 'id', header: 'ID', sortable: true, width: '60px' },
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'timeframe', header: 'TF', sortable: true, width: '60px' },
    { key: 'pattern', header: 'Pattern', sortable: true },
    { key: 'direction', header: 'Dir', sortable: true, render: v => v ? <DirectionBadge direction={v} /> : '-' },
    { key: 'regime', header: 'Regime', sortable: true, render: v => v ? <StatusBadge status={v} /> : '-' },
    { key: 'trigger_price', header: 'Entry', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'stop_loss', header: 'SL', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'take_profit', header: 'TP', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'status', header: 'Status', sortable: true, render: v => <StatusBadge status={v} /> },
    { key: 'rejection_reason', header: 'Reason', render: v => renderRejectReason(v) },
    { key: 'signal_score', header: 'Score', sortable: true, render: v => v ? <span className={`font-mono text-sm ${v >= 8 ? 'text-emerald-400' : v >= 6 ? 'text-yellow-400' : 'text-red-400'}`}>{v.toFixed(2)}</span> : '-' },
    { key: 'exchange_status', header: 'EStatus', render: v => v || '-' },
    { key: 'placed_at', header: 'OrderAt', sortable: true, render: v => v ? utcToVN(v) : '-' },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-2">
        <Clock className="w-6 h-6 text-indigo-400" />
        <h2 className="text-2xl font-bold text-white">Pending Signals {loading && <Loader2 className="w-5 h-5 animate-spin text-indigo-400" />}</h2>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 gap-3">
        <Card className="p-3 text-center">
          <p className="text-xs text-slate-400">Total Pending</p>
          <p className="text-2xl font-bold text-white">{kpi.total}</p>
        </Card>
        <Card className="p-3 text-center">
          <p className="text-xs text-slate-400">WAIT</p>
          <p className="text-2xl font-bold text-yellow-400">{kpi.WAIT}</p>
        </Card>
        <Card className="p-3 text-center">
          <p className="text-xs text-slate-400">FILLED</p>
          <p className="text-2xl font-bold text-emerald-400">{kpi.FILLED}</p>
        </Card>
        <Card className="p-3 text-center">
          <p className="text-xs text-slate-400">REJECTED</p>
          <p className="text-2xl font-bold text-red-400">{kpi.REJECTED}</p>
        </Card>
        <Card className="p-3 text-center">
          <p className="text-xs text-slate-400">CANCELLED</p>
          <p className="text-2xl font-bold text-slate-400">{kpi.CANCELLED}</p>
        </Card>
      </div>

      {/* Filters */}
      <Card>
        <div className="flex items-center gap-2 mb-4">
          <span className="text-sm font-semibold text-white">Filters</span>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-5 lg:grid-cols-10 gap-3 mb-4">
          <Input type="date" label="Start" value={f.startDate} onChange={e => set('startDate', e.target.value)} />
          <Input type="date" label="End" value={f.endDate} onChange={e => set('endDate', e.target.value)} />
          <Select label="Status" value={f.status} onChange={v => set('status', v)} options={[
            { value: 'all', label: 'All' },
            { value: 'WAIT', label: 'WAIT' },
            { value: 'FILLED', label: 'FILLED' },
            { value: 'REJECTED', label: 'REJECTED' },
            { value: 'CANCELLED', label: 'CANCELLED' }
          ]} />
          <Select label="Reject Reason" value={f.rejectReason} onChange={v => set('rejectReason', v)} options={[
            { value: 'all', label: 'All' },
            ...allRejectReasons.map(r => ({ value: r, label: r }))
          ]} />
          <Select label="Exchange Status" value={f.exchangeStatus} onChange={v => set('exchangeStatus', v)} options={[
            { value: 'all', label: 'All' },
            ...allExchangeStatuses.map(s => ({ value: s, label: s }))
          ]} />
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-slate-400 mb-1.5">Symbol</label>
            <div className="flex gap-1">
              <input type="text" value={f.symbols} onChange={e => set('symbols', e.target.value)} placeholder="BTC ETH SOL..." className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm" />
              <button onClick={() => set('symbolMode', f.symbolMode === 'include' ? 'exclude' : 'include')} className={`px-3 py-2 rounded-lg text-xs font-bold ${f.symbolMode === 'include' ? 'bg-emerald-600 text-white' : 'bg-red-600 text-white'}`}>{f.symbolMode === 'include' ? 'Include' : 'Exclude'}</button>
            </div>
          </div>
          <div className="sm:col-span-2">
            <label className="block text-sm font-medium text-slate-400 mb-1.5">Score {f.scoreMin.toFixed(1)} – {f.scoreMax.toFixed(1)}</label>
            <input type="range" min={0} max={10} step={0.5} value={f.scoreMin} onChange={e => set('scoreMin', Number(e.target.value))} className="w-full accent-indigo-500 h-1.5" />
            <input type="range" min={0} max={10} step={0.5} value={f.scoreMax} onChange={e => set('scoreMax', Number(e.target.value))} className="w-full accent-indigo-500 h-1.5" />
          </div>
          <div className="flex items-end">
            <Button variant="primary" className="w-full" onClick={handleApply}>Apply</Button>
          </div>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-12 gap-4 pt-3 border-t border-slate-700">
          <div className="sm:col-span-1">
            <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">TF</p>
            <div className="flex gap-1">{['15m', '1h', '4h'].map(tf =>
              <button key={tf} onClick={() => toggleArr('timeframes', tf)} className={`px-2.5 py-1.5 rounded text-xs ${f.timeframes.includes(tf) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{tf}</button>
            )}</div>
          </div>
          <div className="sm:col-span-2">
            <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Strategy</p>
            <div className="flex gap-1 flex-wrap">{allStrategies.map(s =>
              <button key={s} onClick={() => toggleArr('strategies', s)} className={`px-2 py-1 rounded text-xs ${f.strategies.includes(s) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{s}</button>
            )}</div>
          </div>
          <div className="sm:col-span-5">
            <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Pattern</p>
            <div className="flex gap-1 flex-wrap">{allPatterns.map(p =>
              <button key={p} onClick={() => toggleArr('patterns', p)} className={`px-2 py-1 rounded text-xs ${f.patterns.includes(p) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{p}</button>
            )}</div>
          </div>
          <div className="sm:col-span-2">
            <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Regime</p>
            <div className="flex gap-1 flex-wrap">{allRegimes.map(r =>
              <button key={r} onClick={() => toggleArr('regimes', r)} className={`px-2 py-1 rounded text-xs ${f.regimes.includes(r) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{r}</button>
            )}</div>
          </div>
          <div className="sm:col-span-2">
            <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Direction</p>
            <div className="flex gap-1 flex-wrap">{['LONG', 'SHORT'].map(d =>
              <button key={d} onClick={() => toggleArr('directions', d)} className={`px-2 py-1 rounded text-xs ${f.directions.includes(d) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{d}</button>
            )}</div>
          </div>
        </div>
      </Card>

      {/* Data Table */}
      <Card>
        <CardHeader title="Pending Signals" subtitle={`${filtered.length} signals`} />
        <DataTable
          columns={columns}
          data={[...filtered].sort((a, b) => parseUtcMs(b.created_at) - parseUtcMs(a.created_at))}
          pageSize={20}
          emptyMessage="No pending signals"
        />
      </Card>
    </div>
  );
}
