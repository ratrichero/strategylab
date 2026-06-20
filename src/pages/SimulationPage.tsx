// @ts-nocheck
/* eslint-disable */
import { useState, useEffect, useRef } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { DataTable } from '../components/ui/Table';
import { DirectionBadge } from '../components/ui/Badge';
import { Loader2, Play, FlaskConical, AlertCircle, CheckCircle, X, Plus, RotateCcw } from 'lucide-react';
import { utcToVN } from '../utils/time';
import toast from 'react-hot-toast';

const API = '/api';

const EXIT_COLORS = {
  TP: 'text-emerald-400',
  SL_INITIAL: 'text-red-400',
  SL_BE: 'text-yellow-400',
  SL_LOCK_0_5R: 'text-orange-400',
  SL_LOCK_1R: 'text-orange-400',
  SL_LOCK_1_5R: 'text-orange-400',
  HORIZON: 'text-slate-400',
  AMBIGUOUS_SL: 'text-red-300',
};

const ACTIONS = [
  { value: 'move_to_entry', label: 'Move to Entry + Buffer (BE)' },
  { value: 'move_stop_to_profit_pct', label: 'Move Stop to Profit %' },
];

const TIMEFRAMES = ['15m', '1h', '4h'];

const DEFAULT_POLICY = {
  mode: 'percent',
  timeframes: {
    '15m': {
      sl_pct: 2.0,
      tp_pct: 4.0,
      levels: [
        { trigger_pct: 2.0, action: 'move_to_entry', buffer_pct: 0.2 },
        { trigger_pct: 3.0, action: 'move_stop_to_profit_pct', target_profit_pct: 1.5 },
      ],
    },
    '1h': {
      sl_pct: 2.5,
      tp_pct: 5.0,
      levels: [
        { trigger_pct: 2.5, action: 'move_to_entry', buffer_pct: 0.25 },
      ],
    },
    '4h': {
      sl_pct: 3.0,
      tp_pct: 6.0,
      levels: [
        { trigger_pct: 3.0, action: 'move_to_entry', buffer_pct: 0.3 },
      ],
    },
  },
};

// Convert display % (e.g. 2.0) to decimal (0.02) for API
function pctToDecimal(v) {
  return (parseFloat(v) || 0) / 100;
}

// Convert decimal (0.02) to display % (2.0)
function decimalToPct(v) {
  return parseFloat(((parseFloat(v) || 0) * 100).toFixed(4));
}

function buildApiPolicy(displayPolicy) {
  const result = { mode: 'percent', timeframes: {} };
  for (const tf of TIMEFRAMES) {
    const src = displayPolicy.timeframes[tf];
    if (!src) continue;
    result.timeframes[tf] = {
      sl_pct: pctToDecimal(src.sl_pct),
      tp_pct: pctToDecimal(src.tp_pct),
      levels: (src.levels || []).map(lv => {
        const out = {
          trigger_pct: pctToDecimal(lv.trigger_pct),
          action: lv.action,
        };
        if (lv.action === 'move_to_entry') {
          out.buffer_pct = pctToDecimal(lv.buffer_pct);
        } else if (lv.action === 'move_stop_to_profit_pct') {
          out.target_profit_pct = pctToDecimal(lv.target_profit_pct);
        }
        return out;
      }),
    };
  }
  return result;
}

function deepClone(obj) {
  return JSON.parse(JSON.stringify(obj));
}

export function SimulationPage() {
  // Filters
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [timeframes, setTimeframes] = useState([]);
  const [symbols, setSymbols] = useState('');
  const [fStrategies, setFStrategies] = useState([]);
  const [fDirections, setFDirections] = useState([]);
  const [fPatterns, setFPatterns] = useState([]);
  const [fRegimes, setFRegimes] = useState([]);
  const [limit, setLimit] = useState(500);
  const [includeManual, setIncludeManual] = useState(false);

  // Policy Config (display values in %)
  const [policy, setPolicy] = useState(deepClone(DEFAULT_POLICY));
  const [activeTf, setActiveTf] = useState('15m');

  // Job state
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null);
  const [jobProgress, setJobProgress] = useState(0);
  const [jobMessage, setJobMessage] = useState('');
  const [jobError, setJobError] = useState('');

  // Results
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState([]);
  const [totalRows, setTotalRows] = useState(0);
  const [selectedTrade, setSelectedTrade] = useState(null);
  const [tradeDetail, setTradeDetail] = useState(null);

  // Options
  const [allStrategies, setAllStrategies] = useState([]);
  const [allPatterns, setAllPatterns] = useState([]);
  const pollRef = useRef(null);

  useEffect(() => {
    fetch(`${API}/signals?limit=10000`)
      .then(r => r.json())
      .then(d => {
        const s = d.data || [];
        setAllStrategies(Array.from(new Set(s.map(x => x.strategy_name).filter(Boolean))).sort());
        setAllPatterns(Array.from(new Set(s.map(x => x.pattern).filter(Boolean))).sort());
      })
      .catch(() => {});
  }, []);

  // Policy helpers
  const getTfPolicy = (tf) => policy.timeframes[tf] || { sl_pct: 2.0, tp_pct: 4.0, levels: [] };

  const updateTfField = (tf, key, val) => {
    setPolicy(prev => ({
      ...prev,
      timeframes: {
        ...prev.timeframes,
        [tf]: { ...getTfPolicy(tf), [key]: parseFloat(val) || 0 },
      },
    }));
  };

  const updateLevel = (tf, idx, key, val) => {
    setPolicy(prev => {
      const tfp = { ...getTfPolicy(tf) };
      const levels = [...(tfp.levels || [])];
      levels[idx] = { ...levels[idx], [key]: key === 'action' ? val : (parseFloat(val) || 0) };
      return { ...prev, timeframes: { ...prev.timeframes, [tf]: { ...tfp, levels } } };
    });
  };

  const removeLevel = (tf, idx) => {
    setPolicy(prev => {
      const tfp = { ...getTfPolicy(tf) };
      const levels = (tfp.levels || []).filter((_, i) => i !== idx);
      return { ...prev, timeframes: { ...prev.timeframes, [tf]: { ...tfp, levels } } };
    });
  };

  const addLevel = (tf) => {
    setPolicy(prev => {
      const tfp = { ...getTfPolicy(tf) };
      const levels = [...(tfp.levels || []), { trigger_pct: 3.0, action: 'move_stop_to_profit_pct', target_profit_pct: 1.0 }];
      return { ...prev, timeframes: { ...prev.timeframes, [tf]: { ...tfp, levels } } };
    });
  };

  const resetPolicy = () => setPolicy(deepClone(DEFAULT_POLICY));

  // Poll
  useEffect(() => {
    if (!jobId || jobStatus === 'DONE' || jobStatus === 'FAILED') {
      if (pollRef.current) clearInterval(pollRef.current);
      return;
    }
    const poll = async () => {
      try {
        const res = await fetch(`${API}/backtest/replay/jobs/${jobId}`);
        const data = await res.json();
        setJobStatus(data.status);
        setJobProgress(data.progress_pct || 0);
        setJobMessage(data.message || '');
        if (data.status === 'DONE') loadResults(jobId);
        else if (data.status === 'FAILED') setJobError(data.error || data.message || 'Job failed');
      } catch (e) { console.error(e); }
    };
    pollRef.current = setInterval(poll, 3000);
    poll();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [jobId, jobStatus]);

  const loadResults = async (id) => {
    try {
      const [sumRes, rowsRes] = await Promise.all([
        fetch(`${API}/backtest/replay/jobs/${id}/summary`).then(r => r.json()),
        fetch(`${API}/backtest/replay/jobs/${id}/rows?page=1&page_size=500`).then(r => r.json()),
      ]);
      setSummary(sumRes);
      setRows(rowsRes.items || []);
      setTotalRows(rowsRes.total_rows || 0);
      toast.success(`Backtest complete: ${sumRes.sample_size} trades`);
    } catch { toast.error('Failed to load results'); }
  };

  const runBacktest = async () => {
    setJobError(''); setSummary(null); setRows([]); setSelectedTrade(null); setTradeDetail(null);
    try {
      const body = { limit };
      if (dateFrom) body.date_from = dateFrom;
      if (dateTo) body.date_to = dateTo;
      if (timeframes.length) body.timeframes = timeframes;
      if (symbols.trim()) body.symbols = symbols.split(/[\s,]+/).map(s => s.trim().toUpperCase()).filter(Boolean);
      if (fStrategies.length) body.strategies = fStrategies;
      if (fDirections.length) body.directions = fDirections;
      if (fPatterns.length) body.patterns = fPatterns;
      if (fRegimes.length) body.regimes = fRegimes;
      if (includeManual) body.include_manual = true;

      body.policy = buildApiPolicy(policy);

      console.log('[BACKTEST] Request body:', JSON.stringify(body, null, 2));

      const res = await fetch(`${API}/backtest/replay/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      const data = await res.json();
      setJobId(data.job_id); setJobStatus('QUEUED'); setJobProgress(0); setJobMessage('Job queued...');
    } catch (e) { toast.error(e.message); setJobError(e.message); }
  };

  const loadDetail = async (signalId) => {
    try {
      const res = await fetch(`${API}/backtest/replay/jobs/${jobId}/rows/${signalId}`);
      setTradeDetail(await res.json());
    } catch { toast.error('Failed to load detail'); }
  };

  const toggleArr = (setter, val) => setter(prev => prev.includes(val) ? prev.filter(x => x !== val) : [...prev, val]);
  const $n = (v, d = 2) => Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: d, maximumFractionDigits: d });
  const pnlClr = v => Number(v) >= 0 ? 'text-emerald-400' : 'text-red-400';
  const diffClr = v => Number(v) > 0 ? 'text-emerald-400' : Number(v) < 0 ? 'text-red-400' : 'text-slate-400';
  const isRunning = jobStatus === 'QUEUED' || jobStatus === 'RUNNING';

  const columns = [
    { key: 'signal_id', header: 'ID', sortable: true, width: '60px' },
    { key: 'symbol', header: 'Symbol', sortable: true },
    { key: 'timeframe', header: 'TF', sortable: true, width: '50px' },
    { key: 'strategy_name', header: 'Strategy', sortable: true, render: v => <span className="text-xs">{v}</span> },
    { key: 'direction', header: 'Dir', render: v => <DirectionBadge direction={v} /> },
    { key: 'entry_price', header: 'Entry', align: 'right', render: v => v?.toFixed(v > 100 ? 2 : 4) || '-' },
    { key: 'actual', header: 'Actual RR', sortable: true, align: 'right', render: v => <span className={pnlClr(v?.rr_realized)}>{$n(v?.rr_realized, 3)}</span> },
    { key: 'actual', header: 'A.Exit', render: v => <span className={`text-xs ${EXIT_COLORS[v?.exit_reason] || ''}`}>{v?.exit_reason || '-'}</span> },
    { key: 'simulated', header: 'Sim RR', sortable: true, align: 'right', render: v => <span className={pnlClr(v?.rr_realized)}>{$n(v?.rr_realized, 3)}</span> },
    { key: 'simulated', header: 'S.Exit', render: v => <span className={`text-xs ${EXIT_COLORS[v?.exit_reason] || ''}`}>{v?.exit_reason || '-'}</span> },
    { key: 'delta', header: 'Δ RR', sortable: true, align: 'right', render: v => <span className={diffClr(v?.rr_realized_diff)}>{v?.rr_realized_diff >= 0 ? '+' : ''}{$n(v?.rr_realized_diff, 3)}</span> },
    { key: 'simulated', header: 'L1', align: 'center', render: v => v?.level_1_hit ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span> },
    { key: 'simulated', header: 'L2', align: 'center', render: v => v?.level_2_hit ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span> },
  ];

  const currentTfPolicy = getTfPolicy(activeTf);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <FlaskConical className="w-7 h-7 text-purple-400" />
        <div>
          <h2 className="text-2xl font-bold text-white">Signal Replay Backtest</h2>
          <p className="text-slate-400 mt-0.5">Replay tín hiệu thật theo policy % — so sánh Actual vs Simulated</p>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* LEFT: Filters */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader title="Filters" subtitle="Sample selection" />
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              <Input type="date" label="From" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
              <Input type="date" label="To" value={dateTo} onChange={e => setDateTo(e.target.value)} />
              <Input type="text" label="Symbols" value={symbols} onChange={e => setSymbols(e.target.value)} placeholder="BTC ETH..." />
              <Input type="number" label="Limit" value={limit} onChange={e => setLimit(Number(e.target.value) || 500)} />
            </div>
            <div className="grid grid-cols-12 gap-4 pt-3 border-t border-slate-700">
              <div className="col-span-2">
                <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">TF</p>
                <div className="flex gap-1">
                  {TIMEFRAMES.map(tf => (
                    <button key={tf} onClick={() => toggleArr(setTimeframes, tf)} className={`px-2.5 py-1.5 rounded text-xs ${timeframes.includes(tf) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{tf}</button>
                  ))}
                </div>
              </div>
              <div className="col-span-2">
                <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Direction</p>
                <div className="flex gap-1">
                  {['LONG', 'SHORT'].map(d => (
                    <button key={d} onClick={() => toggleArr(setFDirections, d)} className={`px-2 py-1 rounded text-xs ${fDirections.includes(d) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{d}</button>
                  ))}
                </div>
              </div>
              <div className="col-span-2">
                <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Regime</p>
                <div className="flex gap-1">
                  {['BULL', 'BEAR', 'SIDEWAYS'].map(r => (
                    <button key={r} onClick={() => toggleArr(setFRegimes, r)} className={`px-2 py-1 rounded text-xs ${fRegimes.includes(r) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{r}</button>
                  ))}
                </div>
              </div>
              <div className="col-span-3">
                <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Strategy</p>
                <div className="flex gap-1 flex-wrap">
                  {allStrategies.map(s => (
                    <button key={s} onClick={() => toggleArr(setFStrategies, s)} className={`px-2 py-1 rounded text-xs ${fStrategies.includes(s) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{s}</button>
                  ))}
                </div>
              </div>
              <div className="col-span-3">
                <p className="text-[10px] text-slate-500 uppercase font-semibold mb-1.5">Pattern</p>
                <div className="flex gap-1 flex-wrap">
                  {allPatterns.map(p => (
                    <button key={p} onClick={() => toggleArr(setFPatterns, p)} className={`px-2 py-1 rounded text-xs ${fPatterns.includes(p) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{p}</button>
                  ))}
                </div>
              </div>
            </div>
            <div className="flex items-center gap-3 mt-4 pt-3 border-t border-slate-700">
              <button onClick={() => setIncludeManual(!includeManual)} className={`px-3 py-1.5 rounded text-xs font-medium border ${includeManual ? 'bg-orange-600/20 border-orange-500 text-orange-300' : 'bg-slate-700 border-slate-600 text-slate-400'}`}>
                {includeManual ? 'WL + MANUAL' : 'WL Only'}
              </button>
              <Button variant="primary" loading={isRunning} icon={isRunning ? undefined : <Play className="w-4 h-4" />} onClick={runBacktest} disabled={isRunning}>
                {isRunning ? 'Running...' : 'Run Backtest'}
              </Button>
            </div>
          </Card>
        </div>

        {/* RIGHT: Policy Config (percent-based, per timeframe) */}
        <Card>
          <CardHeader
            title="Policy Config (%)"
            subtitle={`${activeTf} · ${currentTfPolicy.levels?.length || 0} levels`}
            action={
              <button onClick={resetPolicy} className="text-xs text-slate-400 hover:text-white flex items-center gap-1">
                <RotateCcw className="w-3 h-3" />Reset
              </button>
            }
          />
          <div className="space-y-4">
            {/* TF selector */}
            <div className="flex gap-1">
              {TIMEFRAMES.map(tf => (
                <button key={tf} onClick={() => setActiveTf(tf)} className={`px-3 py-1.5 rounded text-xs font-medium ${activeTf === tf ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{tf}</button>
              ))}
            </div>

            {/* SL / TP */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">SL %</label>
                <input type="number" step="0.1" value={currentTfPolicy.sl_pct || ''} onChange={e => updateTfField(activeTf, 'sl_pct', e.target.value)} className="w-full px-2 py-1.5 bg-slate-900 border border-slate-600 rounded text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">TP %</label>
                <input type="number" step="0.1" value={currentTfPolicy.tp_pct || ''} onChange={e => updateTfField(activeTf, 'tp_pct', e.target.value)} className="w-full px-2 py-1.5 bg-slate-900 border border-slate-600 rounded text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500" />
              </div>
            </div>

            {/* Protection Levels */}
            <div>
              <p className="text-xs text-slate-400 mb-2">Protection Levels ({activeTf})</p>
              {(currentTfPolicy.levels || []).map((lv, i) => (
                <div key={i} className="p-3 bg-slate-900/50 rounded-lg border border-slate-700/50 mb-2">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-xs text-slate-300 font-medium">Level {i + 1}</span>
                    <button onClick={() => removeLevel(activeTf, i)} className="text-xs text-red-400 hover:text-red-300">Remove</button>
                  </div>
                  <div className="grid grid-cols-2 gap-2 mb-2">
                    <div>
                      <label className="block text-[10px] text-slate-500 mb-0.5">Trigger %</label>
                      <input type="number" step="0.1" value={lv.trigger_pct || ''} onChange={e => updateLevel(activeTf, i, 'trigger_pct', e.target.value)} className="w-full px-2 py-1 bg-slate-900 border border-slate-600 rounded text-xs text-white font-mono" />
                    </div>
                    <div>
                      <label className="block text-[10px] text-slate-500 mb-0.5">Action</label>
                      <select value={lv.action} onChange={e => updateLevel(activeTf, i, 'action', e.target.value)} className="w-full px-2 py-1 bg-slate-900 border border-slate-600 rounded text-xs text-white">
                        {ACTIONS.map(a => <option key={a.value} value={a.value}>{a.label}</option>)}
                      </select>
                    </div>
                  </div>
                  {lv.action === 'move_to_entry' && (
                    <div>
                      <label className="block text-[10px] text-slate-500 mb-0.5">Buffer %</label>
                      <input type="number" step="0.01" value={lv.buffer_pct || ''} onChange={e => updateLevel(activeTf, i, 'buffer_pct', e.target.value)} className="w-full px-2 py-1 bg-slate-900 border border-slate-600 rounded text-xs text-white font-mono" />
                    </div>
                  )}
                  {lv.action === 'move_stop_to_profit_pct' && (
                    <div>
                      <label className="block text-[10px] text-slate-500 mb-0.5">Target Profit %</label>
                      <input type="number" step="0.1" value={lv.target_profit_pct || ''} onChange={e => updateLevel(activeTf, i, 'target_profit_pct', e.target.value)} className="w-full px-2 py-1 bg-slate-900 border border-slate-600 rounded text-xs text-white font-mono" />
                    </div>
                  )}
                </div>
              ))}
              <button onClick={() => addLevel(activeTf)} className="w-full py-2 border border-dashed border-slate-600 rounded-lg text-xs text-slate-400 hover:border-slate-500 hover:text-slate-300 flex items-center justify-center gap-1">
                <Plus className="w-3 h-3" />Add Level
              </button>
            </div>

            {/* Info */}
            <div className="text-[10px] text-slate-600">
              Tất cả giá trị nhập theo %. VD: SL=2 nghĩa là 2%.
              <br />Intrabar = Conservative | Horizon: 15m=24h, 1h=72h, 4h=7d
            </div>

            {/* Quick summary */}
            <div className="p-2 bg-slate-900/70 rounded text-[10px] text-slate-400 font-mono space-y-0.5">
              {TIMEFRAMES.map(tf => {
                const p = policy.timeframes[tf] || {};
                return (
                  <div key={tf}>
                    <span className="text-slate-300">{tf}:</span> SL={p.sl_pct || 0}% TP={p.tp_pct || 0}% Levels={p.levels?.length || 0}
                  </div>
                );
              })}
            </div>
          </div>
        </Card>
      </div>

      {/* Job Status */}
      {jobId && (
        <Card>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              {isRunning && <Loader2 className="w-4 h-4 animate-spin text-indigo-400" />}
              {jobStatus === 'DONE' && <CheckCircle className="w-4 h-4 text-emerald-400" />}
              {jobStatus === 'FAILED' && <AlertCircle className="w-4 h-4 text-red-400" />}
              <span className="text-sm text-white font-medium">Job: {jobId}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${jobStatus === 'DONE' ? 'bg-emerald-900/30 text-emerald-400' : jobStatus === 'FAILED' ? 'bg-red-900/30 text-red-400' : 'bg-indigo-900/30 text-indigo-400'}`}>{jobStatus}</span>
            </div>
            <span className="text-xs text-slate-500">{jobMessage}</span>
          </div>
          {isRunning && (
            <div className="w-full bg-slate-800 rounded-full h-2.5 overflow-hidden">
              <div className="h-full bg-gradient-to-r from-indigo-500 to-purple-500 rounded-full transition-all duration-500" style={{ width: `${jobProgress}%` }} />
            </div>
          )}
          {jobError && <div className="mt-2 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-red-400 text-sm">{jobError}</div>}
        </Card>
      )}

      {/* Summary */}
      {summary && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <Card>
            <CardHeader title="Actual" subtitle="Real results" />
            <div className="space-y-2">
              {[
                ['Win Rate', `${((summary.actual?.winrate || 0) * 100).toFixed(1)}%`, pnlClr(summary.actual?.winrate - 0.5)],
                ['Avg Return', `${$n(summary.actual?.avg_return_pct)}%`, pnlClr(summary.actual?.avg_return_pct)],
                ['Avg RR', $n(summary.actual?.avg_rr_realized, 3), pnlClr(summary.actual?.avg_rr_realized)],
                ['Total RR', $n(summary.actual?.total_rr_realized, 2), pnlClr(summary.actual?.total_rr_realized)],
              ].map(([l, v, c]) => (
                <div key={l} className="flex justify-between py-1.5 border-b border-slate-700/50 last:border-0">
                  <span className="text-slate-400 text-sm">{l}</span>
                  <span className={`font-bold font-mono ${c}`}>{v}</span>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title="Simulated" subtitle="Policy replay" />
            <div className="space-y-2">
              {[
                ['Win Rate', `${((summary.simulated?.winrate || 0) * 100).toFixed(1)}%`, pnlClr(summary.simulated?.winrate - 0.5)],
                ['Avg Return', `${$n(summary.simulated?.avg_return_pct)}%`, pnlClr(summary.simulated?.avg_return_pct)],
                ['Avg RR', $n(summary.simulated?.avg_rr_realized, 3), pnlClr(summary.simulated?.avg_rr_realized)],
                ['Total RR', $n(summary.simulated?.total_rr_realized, 2), pnlClr(summary.simulated?.total_rr_realized)],
              ].map(([l, v, c]) => (
                <div key={l} className="flex justify-between py-1.5 border-b border-slate-700/50 last:border-0">
                  <span className="text-slate-400 text-sm">{l}</span>
                  <span className={`font-bold font-mono ${c}`}>{v}</span>
                </div>
              ))}
            </div>
          </Card>
          <Card>
            <CardHeader title="Delta & Breakdown" subtitle={`${summary.sample_size} trades`} />
            <div className="space-y-2 mb-4">
              {[
                ['Δ Win Rate', `${summary.delta?.winrate_diff >= 0 ? '+' : ''}${((summary.delta?.winrate_diff || 0) * 100).toFixed(1)}%`],
                ['Δ Avg RR', `${summary.delta?.avg_rr_realized_diff >= 0 ? '+' : ''}${$n(summary.delta?.avg_rr_realized_diff, 3)}`],
                ['Δ Total RR', `${summary.delta?.total_rr_realized_diff >= 0 ? '+' : ''}${$n(summary.delta?.total_rr_realized_diff, 2)}`],
              ].map(([l, v]) => (
                <div key={l} className="flex justify-between py-1.5 border-b border-slate-700/50 last:border-0">
                  <span className="text-slate-400 text-sm">{l}</span>
                  <span className={`font-bold font-mono ${diffClr(parseFloat(v))}`}>{v}</span>
                </div>
              ))}
            </div>
            {summary.sim_exit_breakdown && (
              <div className="space-y-1.5">
                <p className="text-xs text-slate-500 font-medium uppercase">Exit Breakdown</p>
                {Object.entries(summary.sim_exit_breakdown).map(([r, c]) => (
                  <div key={r} className="flex justify-between">
                    <span className={`text-xs ${EXIT_COLORS[r] || 'text-slate-400'}`}>{r}</span>
                    <span className="text-xs text-white font-mono">{c}</span>
                  </div>
                ))}
                {summary.ambiguous_bars > 0 && (
                  <div className="flex justify-between pt-1 border-t border-slate-700/50">
                    <span className="text-xs text-orange-400">Ambiguous</span>
                    <span className="text-xs text-white font-mono">{summary.ambiguous_bars}</span>
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>
      )}

      {/* Trades Table */}
      {rows.length > 0 && (
        <Card>
          <CardHeader title="Replay Trades" subtitle={`${totalRows} trades — click for detail`} />
          <DataTable columns={columns} data={rows} pageSize={20} onRowClick={row => { setSelectedTrade(row); loadDetail(row.signal_id); }} emptyMessage="No trades" />
        </Card>
      )}

      {/* Empty state */}
      {!jobId && !summary && (
        <Card className="flex items-center justify-center h-64">
          <div className="text-center">
            <FlaskConical className="w-12 h-12 text-slate-700 mx-auto mb-3" />
            <p className="text-slate-500">Chưa có kết quả backtest</p>
            <p className="text-xs text-slate-600 mt-1">Cấu hình bộ lọc và policy, nhấn Run Backtest</p>
          </div>
        </Card>
      )}

      {/* Detail Modal */}
      {selectedTrade && tradeDetail && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4" onClick={() => { setSelectedTrade(null); setTradeDetail(null); }}>
          <div className="bg-slate-800 border border-slate-700 rounded-xl p-6 max-w-3xl w-full max-h-[85vh] overflow-auto shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <div className="flex items-center gap-3">
                <h3 className="text-lg font-bold text-white">{tradeDetail.symbol}</h3>
                <DirectionBadge direction={tradeDetail.direction} />
                <span className="text-xs text-slate-400">{tradeDetail.timeframe} · {tradeDetail.strategy_name}</span>
                {tradeDetail.pattern && <span className="text-xs text-yellow-400">{tradeDetail.pattern}</span>}
              </div>
              <button onClick={() => { setSelectedTrade(null); setTradeDetail(null); }} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div className="p-4 bg-slate-900/50 rounded-lg">
                <h4 className="text-sm font-semibold text-slate-300 mb-3">Trade Info</h4>
                <div className="space-y-2 text-sm">
                  {[['Entry', tradeDetail.entry_price], ['Initial SL', tradeDetail.initial_stop_loss], ['TP', tradeDetail.tp_2r_price], ['R Value', tradeDetail.r_value_abs]].map(([l, v]) => (
                    <div key={l} className="flex justify-between">
                      <span className="text-slate-400">{l}</span>
                      <span className="text-white font-mono">{v?.toFixed(v > 100 ? 2 : 6)}</span>
                    </div>
                  ))}
                  <div className="flex justify-between"><span className="text-slate-400">Entry Time</span><span className="text-slate-300">{utcToVN(tradeDetail.entry_time)}</span></div>
                </div>
              </div>
              <div className="space-y-4">
                <div className="p-4 bg-slate-900/50 rounded-lg">
                  <h4 className="text-sm font-semibold text-slate-300 mb-3">Actual</h4>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between"><span className="text-slate-400">Exit</span><span className={EXIT_COLORS[tradeDetail.actual?.exit_reason] || ''}>{tradeDetail.actual?.exit_reason}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">RR</span><span className={`font-bold ${pnlClr(tradeDetail.actual?.rr_realized)}`}>{$n(tradeDetail.actual?.rr_realized, 3)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Return</span><span className={pnlClr(tradeDetail.actual?.result_pct)}>{$n(tradeDetail.actual?.result_pct)}%</span></div>
                  </div>
                </div>
                <div className="p-4 bg-slate-900/50 rounded-lg">
                  <h4 className="text-sm font-semibold text-slate-300 mb-3">Simulated</h4>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between"><span className="text-slate-400">Exit</span><span className={EXIT_COLORS[tradeDetail.simulated?.exit_reason] || ''}>{tradeDetail.simulated?.exit_reason}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">RR</span><span className={`font-bold ${pnlClr(tradeDetail.simulated?.rr_realized)}`}>{$n(tradeDetail.simulated?.rr_realized, 3)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Max RR</span><span className="text-white">{$n(tradeDetail.simulated?.max_rr_seen, 3)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">L1/L2</span><span>{tradeDetail.simulated?.level_1_hit ? '✅' : '—'} / {tradeDetail.simulated?.level_2_hit ? '✅' : '—'}</span></div>
                    {tradeDetail.simulated?.ambiguous_bar && <div className="text-xs text-orange-400 mt-2">⚠️ Ambiguous bar — conservative</div>}
                  </div>
                </div>
              </div>
            </div>
            {tradeDetail.policy_levels?.length > 0 && (
              <div className="mt-6 p-4 bg-slate-900/50 rounded-lg">
                <h4 className="text-sm font-semibold text-slate-300 mb-3">Policy Levels</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {tradeDetail.policy_levels.map((lv, i) => (
                    <div key={i} className="bg-slate-800/50 rounded-lg p-3 text-center">
                      <p className="text-xs text-slate-400">{lv.name} ({lv.trigger_r}R)</p>
                      <p className="text-sm text-white font-mono mt-1">→ {lv.trigger_price?.toFixed(4)}</p>
                      <p className="text-xs text-yellow-400 mt-0.5">Stop: {lv.stop_after_trigger?.toFixed(4)}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {tradeDetail.timeline?.length > 0 && (
              <div className="mt-6 p-4 bg-slate-900/50 rounded-lg">
                <h4 className="text-sm font-semibold text-slate-300 mb-3">Timeline</h4>
                <div className="space-y-2">
                  {tradeDetail.timeline.filter(e => e.event !== 'BAR').map((ev, i) => (
                    <div key={i} className="flex items-center gap-3 text-sm">
                      <span className="text-xs text-slate-500 font-mono w-28">{utcToVN(ev.time)}</span>
                      <span className={`text-xs font-medium ${ev.event.includes('EXIT') ? 'text-emerald-400' : ev.event.includes('TRIGGERED') ? 'text-yellow-400' : 'text-slate-400'}`}>{ev.event}</span>
                      {ev.new_stop && <span className="text-xs text-slate-400">→ Stop: {ev.new_stop.toFixed(4)}</span>}
                      {ev.exit_price && <span className="text-xs text-white">@ {ev.exit_price.toFixed(4)}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}