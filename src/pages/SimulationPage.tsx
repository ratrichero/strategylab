// @ts-nocheck
/* eslint-disable */
import { useState, useMemo, useEffect, useRef } from 'react';
import { Card, CardHeader } from '../components/ui/Card';
import { Button } from '../components/ui/Button';
import { Input } from '../components/ui/Input';
import { Select } from '../components/ui/Select';
import { DataTable } from '../components/ui/Table';
import { DirectionBadge, StatusBadge, PercentChangeBadge } from '../components/ui/Badge';
import { Loader2, Play, FlaskConical, RefreshCw, AlertCircle, CheckCircle, Clock, X } from 'lucide-react';
import { utcToVN } from '../utils/time';
import toast from 'react-hot-toast';

const API = '/api';

const EXIT_COLORS = {
  TP: 'text-emerald-400', SL_INITIAL: 'text-red-400', SL_BE: 'text-yellow-400',
  SL_LOCK_0_5R: 'text-orange-400', HORIZON: 'text-slate-400', AMBIGUOUS_SL: 'text-red-300',
};

export function SimulationPage() {
  // Config
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [timeframes, setTimeframes] = useState([]);
  const [symbols, setSymbols] = useState('');
  const [strategies, setStrategies] = useState([]);
  const [limit, setLimit] = useState(500);
  const [includeManual, setIncludeManual] = useState(false);

  // Job state
  const [jobId, setJobId] = useState(null);
  const [jobStatus, setJobStatus] = useState(null); // QUEUED|RUNNING|DONE|FAILED
  const [jobProgress, setJobProgress] = useState(0);
  const [jobMessage, setJobMessage] = useState('');
  const [jobError, setJobError] = useState('');

  // Results
  const [summary, setSummary] = useState(null);
  const [rows, setRows] = useState([]);
  const [totalRows, setTotalRows] = useState(0);
  const [selectedTrade, setSelectedTrade] = useState(null);
  const [tradeDetail, setTradeDetail] = useState(null);

  // Filter options
  const [allStrategies, setAllStrategies] = useState([]);
  const pollRef = useRef(null);

  // Load strategy list
  useEffect(() => {
    fetch(`${API}/signals?limit=1`).then(r => r.json()).then(d => {
      // Just to get strategies, use engine/versions or signals
    }).catch(() => {});
    fetch(`${API}/engine/versions`).then(r => r.json()).catch(() => []);
    // Get strategies from a quick signal fetch
    fetch(`${API}/signals?limit=5000`).then(r => r.json()).then(d => {
      const sigs = d.data || [];
      setAllStrategies(Array.from(new Set(sigs.map(s => s.strategy_name).filter(Boolean))).sort());
    }).catch(() => {});
  }, []);

  // Poll job status
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
        if (data.status === 'DONE') {
          loadResults(jobId);
        } else if (data.status === 'FAILED') {
          setJobError(data.error || data.message || 'Job failed');
        }
      } catch (e) { console.error(e); }
    };
    pollRef.current = setInterval(poll, 3000);
    poll();
    return () => { if (pollRef.current) clearInterval(pollRef.current); };
  }, [jobId, jobStatus]);

  // Load results
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
    } catch (e) {
      toast.error('Failed to load results');
    }
  };

  // Run backtest
  const runBacktest = async () => {
    setJobError(''); setSummary(null); setRows([]); setSelectedTrade(null); setTradeDetail(null);
    try {
      const body = { limit };
      if (dateFrom) body.date_from = dateFrom;
      if (dateTo) body.date_to = dateTo;
      if (timeframes.length) body.timeframes = timeframes;
      if (symbols.trim()) body.symbols = symbols.split(/[\s,]+/).map(s => s.trim().toUpperCase()).filter(Boolean);
      if (strategies.length) body.strategies = strategies;
      if (includeManual) body.include_manual = true;

      const res = await fetch(`${API}/backtest/replay/run`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body)
      });
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'Failed'); }
      const data = await res.json();
      setJobId(data.job_id);
      setJobStatus('QUEUED');
      setJobProgress(0);
      setJobMessage('Job queued...');
    } catch (e) {
      toast.error(e.message);
      setJobError(e.message);
    }
  };

  // Load trade detail
  const loadDetail = async (signalId) => {
    try {
      const res = await fetch(`${API}/backtest/replay/jobs/${jobId}/rows/${signalId}`);
      const data = await res.json();
      setTradeDetail(data);
    } catch { toast.error('Failed to load detail'); }
  };

  const toggleTF = (tf) => setTimeframes(prev => prev.includes(tf) ? prev.filter(x => x !== tf) : [...prev, tf]);
  const toggleStrat = (s) => setStrategies(prev => prev.includes(s) ? prev.filter(x => x !== s) : [...prev, s]);

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
    { key: 'actual', header: 'Actual RR', sortable: true, align: 'right', render: (v) => <span className={pnlClr(v?.rr_realized)}>{$n(v?.rr_realized, 3)}</span> },
    { key: 'actual', header: 'A.Exit', render: v => <span className={`text-xs ${EXIT_COLORS[v?.exit_reason] || ''}`}>{v?.exit_reason || '-'}</span> },
    { key: 'simulated', header: 'Sim RR', sortable: true, align: 'right', render: v => <span className={pnlClr(v?.rr_realized)}>{$n(v?.rr_realized, 3)}</span> },
    { key: 'simulated', header: 'S.Exit', render: v => <span className={`text-xs ${EXIT_COLORS[v?.exit_reason] || ''}`}>{v?.exit_reason || '-'}</span> },
    { key: 'delta', header: 'Δ RR', sortable: true, align: 'right', render: v => <span className={diffClr(v?.rr_realized_diff)}>{v?.rr_realized_diff >= 0 ? '+' : ''}{$n(v?.rr_realized_diff, 3)}</span> },
    { key: 'simulated', header: 'L1', align: 'center', render: v => v?.level_1_hit ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span> },
    { key: 'simulated', header: 'L2', align: 'center', render: v => v?.level_2_hit ? <span className="text-emerald-400">✓</span> : <span className="text-slate-600">–</span> },
  ];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <FlaskConical className="w-7 h-7 text-purple-400" />
        <div>
          <h2 className="text-2xl font-bold text-white">Signal Replay Backtest</h2>
          <p className="text-slate-400 mt-0.5">Replay tín hiệu thật bằng Binance Mark Price 1m theo policy hiện tại</p>
        </div>
      </div>

      {/* Block A — Control Panel */}
      <Card>
        <CardHeader title="Control Panel" subtitle="Configure & run backtest" />
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-3 mb-4">
          <Input type="date" label="From" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
          <Input type="date" label="To" value={dateTo} onChange={e => setDateTo(e.target.value)} />
          <Input type="text" label="Symbols" value={symbols} onChange={e => setSymbols(e.target.value)} placeholder="BTC ETH..." />
          <Input type="number" label="Limit" value={limit} onChange={e => setLimit(Number(e.target.value) || 500)} />
          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1.5">Timeframe</label>
            <div className="flex gap-1">{['15m', '1h', '4h'].map(tf => (
              <button key={tf} onClick={() => toggleTF(tf)} className={`px-2.5 py-1.5 rounded text-xs font-medium ${timeframes.includes(tf) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{tf}</button>
            ))}</div>
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-400 mb-1.5">Include</label>
            <button onClick={() => setIncludeManual(!includeManual)} className={`px-3 py-1.5 rounded text-xs font-medium border transition-colors ${includeManual ? 'bg-orange-600/20 border-orange-500 text-orange-300' : 'bg-slate-700 border-slate-600 text-slate-400'}`}>
              {includeManual ? 'WL + MANUAL' : 'WL Only'}
            </button>
          </div>
          <div className="flex items-end">
            <Button variant="primary" className="w-full" loading={isRunning} icon={isRunning ? undefined : <Play className="w-4 h-4" />} onClick={runBacktest} disabled={isRunning}>
              {isRunning ? 'Running...' : 'Run Backtest'}
            </Button>
          </div>
        </div>
        {/* Strategy filter */}
        {allStrategies.length > 0 && (
          <div className="flex gap-1 flex-wrap pt-3 border-t border-slate-700">
            <span className="text-xs text-slate-500 mr-2 py-1">Strategy:</span>
            {allStrategies.map(s => (
              <button key={s} onClick={() => toggleStrat(s)} className={`px-2 py-1 rounded text-xs ${strategies.includes(s) ? 'bg-indigo-600 text-white' : 'bg-slate-700 text-slate-400'}`}>{s}</button>
            ))}
          </div>
        )}
        {/* Policy info */}
        <div className="mt-4 p-3 bg-slate-900/50 rounded-lg border border-slate-700/50 text-xs text-slate-500">
          <span className="text-slate-300 font-medium">Policy:</span> TP = 2R | 1.0R → BE + buffer | 1.5R → Lock 0.5R | Intrabar = Conservative | Horizon: 15m=24h, 1h=72h, 4h=7d
        </div>
      </Card>

      {/* Block B — Job Status */}
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

      {/* Block C — Summary */}
      {summary && (
        <div className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Actual */}
            <Card>
              <CardHeader title="Actual" subtitle="Real trade results" />
              <div className="space-y-2">
                {[
                  ['Win Rate', `${((summary.actual?.winrate || 0) * 100).toFixed(1)}%`, pnlClr(summary.actual?.winrate - 0.5)],
                  ['Avg Return', `${$n(summary.actual?.avg_return_pct)}%`, pnlClr(summary.actual?.avg_return_pct)],
                  ['Avg RR', $n(summary.actual?.avg_rr_realized, 3), pnlClr(summary.actual?.avg_rr_realized)],
                  ['Total RR', $n(summary.actual?.total_rr_realized, 2), pnlClr(summary.actual?.total_rr_realized)],
                ].map(([l, v, c]) => (
                  <div key={l} className="flex justify-between py-1.5 border-b border-slate-700/50 last:border-0">
                    <span className="text-slate-400 text-sm">{l}</span><span className={`font-bold font-mono ${c}`}>{v}</span>
                  </div>
                ))}
              </div>
            </Card>
            {/* Simulated */}
            <Card>
              <CardHeader title="Simulated" subtitle="Policy replay results" />
              <div className="space-y-2">
                {[
                  ['Win Rate', `${((summary.simulated?.winrate || 0) * 100).toFixed(1)}%`, pnlClr(summary.simulated?.winrate - 0.5)],
                  ['Avg Return', `${$n(summary.simulated?.avg_return_pct)}%`, pnlClr(summary.simulated?.avg_return_pct)],
                  ['Avg RR', $n(summary.simulated?.avg_rr_realized, 3), pnlClr(summary.simulated?.avg_rr_realized)],
                  ['Total RR', $n(summary.simulated?.total_rr_realized, 2), pnlClr(summary.simulated?.total_rr_realized)],
                ].map(([l, v, c]) => (
                  <div key={l} className="flex justify-between py-1.5 border-b border-slate-700/50 last:border-0">
                    <span className="text-slate-400 text-sm">{l}</span><span className={`font-bold font-mono ${c}`}>{v}</span>
                  </div>
                ))}
              </div>
            </Card>
            {/* Delta + Breakdown */}
            <Card>
              <CardHeader title="Delta & Breakdown" subtitle={`${summary.sample_size} trades`} />
              <div className="space-y-2 mb-4">
                {[
                  ['Δ Win Rate', `${summary.delta?.winrate_diff >= 0 ? '+' : ''}${((summary.delta?.winrate_diff || 0) * 100).toFixed(1)}%`],
                  ['Δ Avg RR', `${summary.delta?.avg_rr_realized_diff >= 0 ? '+' : ''}${$n(summary.delta?.avg_rr_realized_diff, 3)}`],
                  ['Δ Total RR', `${summary.delta?.total_rr_realized_diff >= 0 ? '+' : ''}${$n(summary.delta?.total_rr_realized_diff, 2)}`],
                ].map(([l, v]) => (
                  <div key={l} className="flex justify-between py-1.5 border-b border-slate-700/50 last:border-0">
                    <span className="text-slate-400 text-sm">{l}</span><span className={`font-bold font-mono ${diffClr(parseFloat(v))}`}>{v}</span>
                  </div>
                ))}
              </div>
              {summary.sim_exit_breakdown && (
                <div className="space-y-1.5">
                  <p className="text-xs text-slate-500 font-medium uppercase">Exit Breakdown</p>
                  {Object.entries(summary.sim_exit_breakdown).map(([reason, count]) => (
                    <div key={reason} className="flex justify-between">
                      <span className={`text-xs ${EXIT_COLORS[reason] || 'text-slate-400'}`}>{reason}</span>
                      <span className="text-xs text-white font-mono">{count}</span>
                    </div>
                  ))}
                  {summary.ambiguous_bars > 0 && (
                    <div className="flex justify-between pt-1 border-t border-slate-700/50">
                      <span className="text-xs text-orange-400">Ambiguous bars</span>
                      <span className="text-xs text-white font-mono">{summary.ambiguous_bars}</span>
                    </div>
                  )}
                </div>
              )}
            </Card>
          </div>
        </div>
      )}

      {/* Block D — Trades Table */}
      {rows.length > 0 && (
        <Card>
          <CardHeader title="Replay Trades" subtitle={`${totalRows} trades — click row for detail`} />
          <DataTable
            columns={columns}
            data={rows}
            pageSize={20}
            onRowClick={(row) => { setSelectedTrade(row); loadDetail(row.signal_id); }}
            emptyMessage="No trades"
          />
        </Card>
      )}

      {/* Empty state */}
      {!jobId && !summary && (
        <Card className="flex items-center justify-center h-64">
          <div className="text-center">
            <FlaskConical className="w-12 h-12 text-slate-700 mx-auto mb-3" />
            <p className="text-slate-500">Chưa có kết quả backtest</p>
            <p className="text-xs text-slate-600 mt-1">Cấu hình bộ lọc và nhấn Run Backtest</p>
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
              {/* Trade info */}
              <div className="p-4 bg-slate-900/50 rounded-lg">
                <h4 className="text-sm font-semibold text-slate-300 mb-3">Trade Info</h4>
                <div className="space-y-2 text-sm">
                  <div className="flex justify-between"><span className="text-slate-400">Entry Price</span><span className="text-white font-mono">{tradeDetail.entry_price?.toFixed(tradeDetail.entry_price > 100 ? 2 : 4)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">Initial SL</span><span className="text-red-400 font-mono">{tradeDetail.initial_stop_loss?.toFixed(tradeDetail.initial_stop_loss > 100 ? 2 : 4)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">TP (2R)</span><span className="text-emerald-400 font-mono">{tradeDetail.tp_2r_price?.toFixed(tradeDetail.tp_2r_price > 100 ? 2 : 4)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">R Value</span><span className="text-white font-mono">{$n(tradeDetail.r_value_abs, 4)}</span></div>
                  <div className="flex justify-between"><span className="text-slate-400">Entry Time</span><span className="text-slate-300">{utcToVN(tradeDetail.entry_time)}</span></div>
                </div>
              </div>

              {/* Actual vs Simulated */}
              <div className="space-y-4">
                <div className="p-4 bg-slate-900/50 rounded-lg">
                  <h4 className="text-sm font-semibold text-slate-300 mb-3">Actual</h4>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between"><span className="text-slate-400">Exit Reason</span><span className={EXIT_COLORS[tradeDetail.actual?.exit_reason] || ''}>{tradeDetail.actual?.exit_reason}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">RR Realized</span><span className={`font-bold ${pnlClr(tradeDetail.actual?.rr_realized)}`}>{$n(tradeDetail.actual?.rr_realized, 3)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Return %</span><span className={pnlClr(tradeDetail.actual?.result_pct)}>{$n(tradeDetail.actual?.result_pct)}%</span></div>
                  </div>
                </div>
                <div className="p-4 bg-slate-900/50 rounded-lg">
                  <h4 className="text-sm font-semibold text-slate-300 mb-3">Simulated</h4>
                  <div className="space-y-2 text-sm">
                    <div className="flex justify-between"><span className="text-slate-400">Exit Reason</span><span className={EXIT_COLORS[tradeDetail.simulated?.exit_reason] || ''}>{tradeDetail.simulated?.exit_reason}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">RR Realized</span><span className={`font-bold ${pnlClr(tradeDetail.simulated?.rr_realized)}`}>{$n(tradeDetail.simulated?.rr_realized, 3)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Max RR Seen</span><span className="text-white">{$n(tradeDetail.simulated?.max_rr_seen, 3)}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Level 1 Hit</span><span>{tradeDetail.simulated?.level_1_hit ? '✅' : '—'}</span></div>
                    <div className="flex justify-between"><span className="text-slate-400">Level 2 Hit</span><span>{tradeDetail.simulated?.level_2_hit ? '✅' : '—'}</span></div>
                    {tradeDetail.simulated?.ambiguous_bar && <div className="text-xs text-orange-400 mt-2">⚠️ Ambiguous bar detected — conservative mode applied</div>}
                  </div>
                </div>
              </div>
            </div>

            {/* Policy Levels */}
            {tradeDetail.policy_levels?.length > 0 && (
              <div className="mt-6 p-4 bg-slate-900/50 rounded-lg">
                <h4 className="text-sm font-semibold text-slate-300 mb-3">Policy Levels</h4>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                  {tradeDetail.policy_levels.map((lv, i) => (
                    <div key={i} className="bg-slate-800/50 rounded-lg p-3 text-center">
                      <p className="text-xs text-slate-400">{lv.name} ({lv.trigger_r}R)</p>
                      <p className="text-sm text-white font-mono mt-1">Trigger: {lv.trigger_price?.toFixed(lv.trigger_price > 100 ? 2 : 4)}</p>
                      <p className="text-xs text-yellow-400 mt-0.5">Stop → {lv.stop_after_trigger?.toFixed(lv.stop_after_trigger > 100 ? 2 : 4)}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Timeline */}
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
