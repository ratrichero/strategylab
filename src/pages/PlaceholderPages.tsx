// @ts-nocheck
/* eslint-disable */
import { useState, useMemo, useEffect } from "react";
import { Card, CardHeader } from "../components/ui/Card";
import { Select } from "../components/ui/Select";
import { Button } from "../components/ui/Button";
import { DataTable } from "../components/ui/Table";
import { PercentChangeBadge, DirectionBadge, StatusBadge } from "../components/ui/Badge";
import { utcToVN } from "../utils/time";
import { TrendingUp, TrendingDown, Minus, Loader2, RefreshCw, Cpu, Ban, FlaskConical } from "lucide-react";
import { engine } from "../services/api";

const API = "/api";

// ============================================
// MARKET PAGE
// ============================================
export function MarketPage() {
  const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
  const [loading, setLoading] = useState(true);
  const [signals, setSignals] = useState([]);
  const [symbolList, setSymbolList] = useState([]);

  const load = async (symbol) => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/signals?symbol=${symbol}&limit=200`).then(r => r.json());
      const all = await fetch(`${API}/signals?limit=10000`).then(r => r.json());
      setSignals(res.data || []);
      const syms = Array.from(new Set((all.data || []).map(s => s.symbol).filter(Boolean))).sort();
      setSymbolList(syms);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(selectedSymbol); }, [selectedSymbol]);

  const allSigs = useMemo(() => signals.filter(s => s.status === "WIN" || s.status === "LOSS"), [signals]);
  const wr = allSigs.length ? (allSigs.filter(s => s.status === "WIN").length / allSigs.length * 100) : 0;
  const avgRet = allSigs.length ? allSigs.reduce((a, s) => a + (s.result_percent || 0), 0) / allSigs.length : 0;
  const regime = signals[0]?.regime || "N/A";

  const regimeDist = useMemo(() => {
    const c = {};
    allSigs.forEach(s => { c[s.regime || "?"] = (c[s.regime || "?"] || 0) + 1; });
    return Object.entries(c).map(([name, value]) => ({ name, value }));
  }, [allSigs]);

  const cols = [
    { key: "symbol", header: "Symbol", sortable: true },
    { key: "direction", header: "Dir", render: v => <DirectionBadge direction={v} /> },
    { key: "timeframe", header: "TF", sortable: true },
    { key: "pattern", header: "Pattern", sortable: true },
    { key: "result_percent", header: "P&L", sortable: true, render: v => <PercentChangeBadge value={v || 0} /> },
    { key: "status", header: "Status", sortable: true, render: v => <StatusBadge status={v} /> },
    { key: "regime", header: "Regime", sortable: true },
    { key: "score", header: "Score", sortable: true, render: v => (Number(v)||0).toFixed(2) },
    { key: "exit_time", header: "Closed", sortable: true, render: v => <span className="text-xs text-slate-400">{utcToVN(v)}</span> },
  ];

  if (loading) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin text-indigo-500" /></div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h2 className="text-2xl font-bold text-white">Market Overview</h2><p className="text-slate-400 mt-1">Signal history by symbol</p></div>
        <div className="flex items-center gap-3">
          <Select value={selectedSymbol} onChange={v => setSelectedSymbol(v)} options={symbolList.length ? symbolList.map(s => ({value:s,label:s})) : [{value:"BTCUSDT",label:"BTCUSDT"}]} />
          <Button variant="ghost" icon={<RefreshCw className="w-4 h-4" />} onClick={() => load(selectedSymbol)}>Refresh</Button>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card className="flex items-center gap-4">
          <div className="p-3 bg-indigo-500/20 rounded-xl">
            {regime === "BULL" ? <TrendingUp className="w-6 h-6 text-emerald-400" /> : regime === "BEAR" ? <TrendingDown className="w-6 h-6 text-red-400" /> : <Minus className="w-6 h-6 text-yellow-400" />}
          </div>
          <div><p className="text-sm text-slate-400">Regime</p><p className="text-xl font-bold text-white">{regime}</p></div>
        </Card>
        <Card className="p-4"><p className="text-sm text-slate-400">Total Signals</p><p className="text-2xl font-bold text-white">{allSigs.length}</p></Card>
        <Card className="p-4"><p className="text-sm text-slate-400">Win Rate</p><p className={`text-2xl font-bold ${wr>=50?"text-emerald-400":"text-red-400"}`}>{wr.toFixed(1)}%</p></Card>
        <Card className="p-4"><p className="text-sm text-slate-400">Avg Return</p><p className={`text-2xl font-bold ${avgRet>=0?"text-emerald-400":"text-red-400"}`}>{avgRet>=0?"+":""}{avgRet.toFixed(2)}%</p></Card>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader title="Regime Breakdown" />
          <div className="space-y-2">
            {regimeDist.map(r => (
              <div key={r.name} className="flex items-center gap-3">
                <span className="w-20 text-sm text-slate-400">{r.name}</span>
                <div className="flex-1 bg-slate-800 rounded-full h-5 overflow-hidden">
                  <div className="h-full bg-indigo-500/70 rounded-full flex items-center px-2" style={{ width: `${(r.value / (allSigs.length||1) * 100)}%` }}>
                    <span className="text-xs text-white">{r.value}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader title="Summary" />
          <div className="space-y-3">
            {[["Total", allSigs.length], ["Wins", allSigs.filter(s=>s.status==="WIN").length], ["Losses", allSigs.filter(s=>s.status==="LOSS").length], ["Win Rate", `${wr.toFixed(1)}%`], ["Avg Return", `${avgRet>=0?"+":""}${avgRet.toFixed(2)}%`]].map(([l, v]) => (
              <div key={String(l)} className="flex justify-between py-2 border-b border-slate-700 last:border-0">
                <span className="text-slate-400">{l}</span><span className="font-medium text-white">{v}</span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Card>
        <CardHeader title={`${selectedSymbol} — Signal History`} subtitle={`${allSigs.length} trades`} />
        <DataTable columns={cols} data={allSigs} pageSize={20} />
      </Card>
    </div>
  );
}

// ============================================
// ENGINE PAGE
// ============================================
export function EnginePage() {
  const [versions, setVersions] = useState([]);
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [v, s] = await Promise.all([engine.versions().catch(() => []), engine.status().catch(() => null)]);
      setVersions(v);
      setStatus(s);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const cols = [
    { key: "engine_version", header: "Version", sortable: true },
    { key: "total_trades", header: "Trades", sortable: true, align: "right" },
    { key: "wins", header: "Wins", sortable: true, align: "right" },
    { key: "winrate", header: "Win Rate", sortable: true, align: "right", render: v => <span className={v>=50?"text-emerald-400":"text-red-400"}>{Number(v).toFixed(1)}%</span> },
    { key: "avg_return", header: "Avg Return", sortable: true, render: v => <PercentChangeBadge value={Number(v)||0} /> },
  ];

  if (loading) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin text-indigo-500" /></div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Cpu className="w-7 h-7 text-indigo-400" />
          <div><h2 className="text-2xl font-bold text-white">Engine Analytics</h2><p className="text-slate-400 mt-0.5">Engine version performance</p></div>
        </div>
        <Button variant="ghost" icon={<RefreshCw className="w-4 h-4" />} onClick={load}>Refresh</Button>
      </div>
      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "Active Strategies", value: status.active_strategies },
            { label: "Top Limit", value: status.top_limit },
            { label: "Scheduler", value: status.scheduler_on ? "🟢 ON" : "🔴 OFF" },
            { label: "Trading Mode", value: status.trading_mode?.mode || "—" },
          ].map((item, i) => (
            <Card key={i} className="text-center p-4">
              <p className="text-xs text-slate-400 mb-1">{item.label}</p>
              <p className="text-lg font-bold text-white">{item.value}</p>
            </Card>
          ))}
        </div>
      )}
      <Card>
        <CardHeader title="Engine Version Performance" subtitle="All time" />
        {versions.length ? <DataTable columns={cols} data={versions} pageSize={20} /> : <div className="h-48 flex items-center justify-center text-slate-500">No engine version data</div>}
      </Card>
    </div>
  );
}

// ============================================
// BLOCKED PAGE
// ============================================
export function BlockedPage() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState([]);
  const [reasons, setReasons] = useState([]);
  const [selectedReason, setSelectedReason] = useState("all");
  const today = new Date(Date.now() + 7*3600*1000).toISOString().slice(0,10);
  const [pendingStartDate, setPendingStartDate] = useState(today);
  const [pendingEndDate, setPendingEndDate] = useState(today);
  const [appliedStartDate, setAppliedStartDate] = useState(today);
  const [appliedEndDate, setAppliedEndDate] = useState(today);

  const loadData = async () => {
    setLoading(true);
    try {
      const [debugRes, reasonRes] = await Promise.all([
        fetch(`${API}/scan-debug?limit=1000`).then(r => r.json()).catch(() => ({ data: [] })),
        fetch(`${API}/scan-debug/block-reasons`).then(r => r.json()).catch(() => []),
      ]);
      setData(debugRes.data || []);
      setReasons(Array.isArray(reasonRes) ? reasonRes : []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { loadData(); }, []);

  // Group block reasons: "HTF::abc" → "HTF", "OTF::xyz" → "OTF", else unique
  const getReasonGroup = (reason) => {
    if (!reason) return '';
    return reason.includes('::') ? reason.split('::')[0] : reason;
  };

  const filtered = useMemo(() => {
    const VN_MS = 7 * 3600 * 1000;
    return data.filter(d => {
      if (selectedReason !== "all" && getReasonGroup(d.block_reason) !== selectedReason) return false;
      if (appliedStartDate || appliedEndDate) {
        const ts = d.created_at ? new Date(d.created_at).getTime() : 0;
        if (!ts) return false;
        const vn = new Date(ts + VN_MS);
        const vnStr = `${vn.getUTCFullYear()}-${String(vn.getUTCMonth()+1).padStart(2,'0')}-${String(vn.getUTCDate()).padStart(2,'0')}`;
        if (appliedStartDate && vnStr < appliedStartDate) return false;
        if (appliedEndDate && vnStr > appliedEndDate) return false;
      }
      return true;
    });
  }, [data, selectedReason, appliedStartDate, appliedEndDate]);

  const reasonList = useMemo(() => {
    return Array.from(new Set(data.map(d => getReasonGroup(d.block_reason)).filter(Boolean))).sort();
  }, [data]);

  const cols = [
    { key: "symbol", header: "Symbol", sortable: true },
    { key: "timeframe", header: "TF", sortable: true },
    { key: "block_reason", header: "Block Reason", sortable: true, render: v => <span className="text-xs text-red-400">{v || '-'}</span> },
    { key: "total_score", header: "Score", sortable: true, align: "right", render: v => <span className={`font-mono text-sm ${Number(v)>=8?'text-emerald-400':Number(v)>=6?'text-yellow-400':'text-red-400'}`}>{Number(v||0).toFixed(2)}</span> },
    { key: "ml_prob", header: "ML Prob", sortable: true, align: "right", render: v => v != null ? Number(v).toFixed(3) : '-' },
    { key: "trend_score", header: "Trend", align: "right", render: v => v != null ? Number(v).toFixed(2) : '-' },
    { key: "momentum_score", header: "Mom", align: "right", render: v => v != null ? Number(v).toFixed(2) : '-' },
    { key: "volume_score", header: "Vol", align: "right", render: v => v != null ? Number(v).toFixed(2) : '-' },
    { key: "created_at", header: "Time", sortable: true, render: v => <span className="text-xs text-slate-400">{utcToVN(v)}</span> },
  ];

  if (loading) return <div className="flex items-center justify-center h-96"><Loader2 className="w-8 h-8 animate-spin text-indigo-500" /></div>;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Ban className="w-7 h-7 text-red-400" />
          <div><h2 className="text-2xl font-bold text-white">Blocked Signals</h2><p className="text-slate-400 mt-0.5">Signals blocked by filter pipeline</p></div>
        </div>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Total Blocked</p><p className="text-2xl font-bold text-white">{filtered.length}</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Unique Reasons</p><p className="text-2xl font-bold text-white">{Array.from(new Set(filtered.map(d=>getReasonGroup(d.block_reason)).filter(Boolean))).length}</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">Avg Score</p><p className="text-2xl font-bold text-yellow-400">{filtered.length ? (filtered.reduce((s,d) => s + Number(d.total_score||0), 0) / filtered.length).toFixed(2) : '0'}</p></Card>
        <Card className="p-3 text-center"><p className="text-xs text-slate-400">All Time</p><p className="text-2xl font-bold text-slate-400">{data.length}</p></Card>
      </div>
      <Card>
        <div className="flex items-center gap-3 mb-4 flex-wrap">
          <Select label="Block Reason" value={selectedReason} onChange={setSelectedReason} options={[{ value: "all", label: "All Reasons" }, ...reasonList.map(r => ({ value: r, label: r }))]} className="w-64" />
          <div><label className="block text-sm font-medium text-slate-400 mb-1.5">From</label><input type="date" value={pendingStartDate} onChange={e => setPendingStartDate(e.target.value)} className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm" /></div>
          <div><label className="block text-sm font-medium text-slate-400 mb-1.5">To</label><input type="date" value={pendingEndDate} onChange={e => setPendingEndDate(e.target.value)} className="bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm" /></div>
          <div className="flex items-center"><Button onClick={() => { setAppliedStartDate(pendingStartDate); setAppliedEndDate(pendingEndDate); }}>Apply</Button></div>
        </div>
        <DataTable columns={cols} data={filtered} pageSize={20} emptyMessage="No blocked signals" />
      </Card>
    </div>
  );
}

// ============================================
// SIMULATION PAGE
// ============================================
export function SimulationPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <FlaskConical className="w-7 h-7 text-purple-400" />
        <div><h2 className="text-2xl font-bold text-white">Simulation</h2><p className="text-slate-400 mt-0.5">Backtesting and simulation</p></div>
      </div>
      <Card className="flex items-center justify-center h-96">
        <div className="text-center">
          <FlaskConical className="w-16 h-16 text-slate-700 mx-auto mb-4" />
          <p className="text-slate-500 text-lg mb-2">🚧 Coming Soon</p>
          <p className="text-slate-600 text-sm">Strategy backtesting with historical data</p>
        </div>
      </Card>
    </div>
  );
}
