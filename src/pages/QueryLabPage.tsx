// @ts-nocheck
import { useState, useMemo } from "react";
import { Card } from "../components/ui/Card";
import { Button } from "../components/ui/Button";
import { DataTable } from "../components/ui/Table";
import { Code2, Play, Download, Database, Loader2 } from "lucide-react";
import { queryLab } from "../services/api";
import toast from "react-hot-toast";

const SAMPLE_QUERIES = [
  { label: "Win Rate by Pattern", sql: `SELECT pattern, COUNT(*) total, ROUND(100.0*SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate, ROUND(AVG(result_percent)::numeric,2) avg_return FROM signals WHERE status IN ('WIN','LOSS') AND pattern IS NOT NULL GROUP BY pattern ORDER BY win_rate DESC` },
  { label: "Performance by Regime", sql: `SELECT regime, COUNT(*) total, ROUND(100.0*SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate, ROUND(AVG(result_percent)::numeric,2) avg_return FROM signals WHERE status IN ('WIN','LOSS') GROUP BY regime ORDER BY avg_return DESC` },
  { label: "Engine Version Compare", sql: `SELECT engine_version, COUNT(*) total, ROUND(100.0*SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate, ROUND(AVG(result_percent)::numeric,2) avg_return FROM signals WHERE status IN ('WIN','LOSS') AND engine_version IS NOT NULL GROUP BY engine_version ORDER BY engine_version DESC` },
  { label: "Recent Open Trades", sql: `SELECT symbol, direction, timeframe, strategy_name, score, entry_price, stop_loss, take_profit, candle_time FROM signals WHERE status = 'OPEN' ORDER BY candle_time DESC LIMIT 20` },
  { label: "Block Reason Analysis", sql: `SELECT block_reason, COUNT(*) n, ROUND(AVG(total_score)::numeric,3) avg_score, ROUND(AVG(ml_prob)::numeric,3) avg_ml FROM scan_debug WHERE block_reason IS NOT NULL GROUP BY block_reason ORDER BY n DESC` },
  { label: "Pending Signals", sql: `SELECT symbol, direction, timeframe, strategy_name, trigger_price, stop_loss, take_profit, signal_score, status, expire_at, created_at FROM pending_signals ORDER BY created_at DESC LIMIT 30` },
  { label: "Daily PnL Last 30 Days", sql: `SELECT DATE(exit_time) day, COUNT(*) trades, SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END) wins, ROUND(SUM(result_percent)::numeric,2) total_pnl FROM signals WHERE status IN ('WIN','LOSS') AND exit_time >= NOW()-INTERVAL '30 days' GROUP BY day ORDER BY day DESC` },
  { label: "Strategy Performance", sql: `SELECT strategy_name, timeframe, COUNT(*) total, ROUND(100.0*SUM(CASE WHEN status='WIN' THEN 1 ELSE 0 END)/NULLIF(COUNT(*),0),1) win_rate, ROUND(AVG(result_percent)::numeric,2) avg_return FROM signals WHERE status IN ('WIN','LOSS') GROUP BY strategy_name, timeframe ORDER BY win_rate DESC` },
];

export function QueryLab() {
  const [sql, setSql]         = useState(SAMPLE_QUERIES[0].sql);
  const [data, setData]       = useState([]);
  const [loading, setLoading] = useState(false);
  const [execTime, setExecTime] = useState(0);
  const [error, setError]     = useState("");

  const run = async () => {
    setLoading(true); setError(""); setData([]);
    const t0 = performance.now();
    try {
      const res = await queryLab.execute(sql);
      setData(res.data || []);
      setExecTime(performance.now() - t0);
      toast.success(`${res.row_count} rows in ${(performance.now() - t0).toFixed(0)}ms`);
    } catch (e) {
      setError(e.message);
      toast.error(e.message);
    } finally { setLoading(false); }
  };

  const exportCSV = () => {
    if (!data.length) return;
    const keys = Object.keys(data[0]);
    const csv = [keys.join(","), ...data.map(row => keys.map(k => JSON.stringify(row[k] ?? "")).join(","))].join("\n");
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    a.download = `query_${Date.now()}.csv`;
    a.click();
  };

  const columns = useMemo(() => {
    if (!data.length) return [];
    return Object.keys(data[0]).map(k => ({
      key: k, header: k, sortable: true,
      render: (v) => {
        if (v == null) return <span className="text-slate-500">NULL</span>;
        if (typeof v === "object") return <span className="text-xs font-mono">{JSON.stringify(v).slice(0, 60)}</span>;
        return String(v).slice(0, 100);
      }
    }));
  }, [data]);

  return (
    <div className="space-y-4 h-[calc(100vh-100px)] flex flex-col">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Code2 className="w-6 h-6 text-indigo-400" />
          <h2 className="text-2xl font-bold text-white">Query Lab</h2>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={exportCSV} disabled={!data.length} icon={<Download className="w-4 h-4" />}>Export CSV</Button>
          <Button variant="primary" onClick={run} loading={loading} icon={<Play className="w-4 h-4" />}>Run (Ctrl+Enter)</Button>
        </div>
      </div>

      {/* Sample queries */}
      <div className="flex gap-2 flex-wrap">
        {SAMPLE_QUERIES.map(q => (
          <button key={q.label} onClick={() => setSql(q.sql)}
            className="px-3 py-1 bg-slate-700 hover:bg-slate-600 text-slate-300 rounded text-xs transition">
            {q.label}
          </button>
        ))}
      </div>

      {/* Editor */}
      <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 overflow-hidden flex-shrink-0">
        <div className="flex items-center justify-between px-4 py-2 border-b border-slate-700 bg-slate-900/30">
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <Database className="w-4 h-4" />
            <span>PostgreSQL — Read Only</span>
          </div>
          <div className="flex items-center gap-3 text-xs text-slate-500">
            {data.length > 0 && <span className="text-emerald-400">{data.length} rows · {execTime.toFixed(0)}ms</span>}
            {error && <span className="text-red-400">Error</span>}
          </div>
        </div>
        <textarea value={sql} onChange={e => setSql(e.target.value)}
          onKeyDown={e => { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); run(); } }}
          rows={8}
          className="w-full bg-slate-900 text-white font-mono text-sm p-4 resize-none focus:outline-none"
          spellCheck={false}
          placeholder="SELECT * FROM signals LIMIT 10;"
        />
      </div>

      {/* Results */}
      <div className="flex-1 overflow-auto">
        {error && (
          <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-xl text-red-400 text-sm mb-4">
            {error}
          </div>
        )}
        {loading && (
          <div className="flex items-center justify-center h-32">
            <Loader2 className="animate-spin text-indigo-500 w-8 h-8" />
          </div>
        )}
        {!loading && data.length > 0 && (
          <div className="bg-slate-800/50 rounded-xl border border-slate-700/50 p-4">
            <DataTable columns={columns} data={data} pageSize={50} />
          </div>
        )}
        {!loading && !data.length && !error && (
          <div className="flex items-center justify-center h-32 text-slate-500">
            <div className="text-center">
              <Database className="w-10 h-10 mx-auto mb-2 opacity-30" />
              <p>Run a query to see results</p>
              <p className="text-xs mt-1">Ctrl+Enter to execute</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
