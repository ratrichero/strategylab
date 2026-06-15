import { useState, useMemo, useEffect } from "react";
import { Card, CardHeader } from "../components/ui/Card";
import { Select } from "../components/ui/Select";
import { Button } from "../components/ui/Button";
import { DataTable } from "../components/ui/Table";
import { PercentChangeBadge, DirectionBadge, StatusBadge } from "../components/ui/Badge";
import { utcToLocal } from "../utils/format";
import { TrendingUp, TrendingDown, Minus, Loader2, RefreshCw } from "lucide-react";

const API = "/api";

export function Market() {
  const [selectedSymbol, setSelectedSymbol] = useState("BTCUSDT");
  const [loading, setLoading]               = useState(true);
  const [signals, setSignals]               = useState<any[]>([]);
  const [symbolList, setSymbolList]         = useState<string[]>([]);

  const load = async (symbol: string) => {
    setLoading(true);
    try {
      const res = await fetch(`${API}/signals?symbol=${symbol}&limit=200&status=WIN&limit=200`).then(r => r.json());
      const all = await fetch(`${API}/signals?limit=500`).then(r => r.json());
      setSignals(res.data || []);
      const syms = Array.from(new Set((all.data || []).map((s: any) => s.symbol).filter(Boolean))).sort() as string[];
      setSymbolList(syms);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(selectedSymbol); }, [selectedSymbol]);

  const allSigs = useMemo(() => signals.filter((s: any) => s.status === "WIN" || s.status === "LOSS"), [signals]);
  const wr = allSigs.length ? (allSigs.filter(s => s.status === "WIN").length / allSigs.length * 100) : 0;
  const avgRet = allSigs.length ? allSigs.reduce((a, s) => a + (s.result_percent || 0), 0) / allSigs.length : 0;
  const regime = signals[0]?.regime || "N/A";

  const regimeDist = useMemo(() => {
    const c: Record<string, number> = {};
    allSigs.forEach(s => { c[s.regime || "?"] = (c[s.regime || "?"] || 0) + 1; });
    return Object.entries(c).map(([name, value]) => ({ name, value }));
  }, [allSigs]);

  const cols = [
    { key: "symbol",         header: "Symbol",    sortable: true },
    { key: "direction",      header: "Dir",        render: (v: string) => <DirectionBadge direction={v} /> },
    { key: "timeframe",      header: "TF",         sortable: true },
    { key: "pattern",        header: "Pattern",    sortable: true },
    { key: "result_percent", header: "P&L",        sortable: true, render: (v: number) => <PercentChangeBadge value={v || 0} /> },
    { key: "status",         header: "Status",     sortable: true, render: (v: string) => <StatusBadge status={v} /> },
    { key: "regime",         header: "Regime",     sortable: true },
    { key: "score",          header: "Score",      sortable: true, render: (v: number) => (Number(v)||0).toFixed(2) },
    { key: "exit_time",      header: "Closed",     sortable: true, render: (v: string) => <span className="text-xs text-slate-400">{utcToLocal(v)}</span> },
  ];

  if (loading) return (
    <div className="flex items-center justify-center h-96">
      <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
    </div>
  );

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div><h2 className="text-2xl font-bold text-white">Market Overview</h2><p className="text-slate-400 mt-1">Signal history by symbol</p></div>
        <div className="flex items-center gap-3">
          <Select value={selectedSymbol} onChange={(v) => setSelectedSymbol(v)}
            options={symbolList.length ? symbolList.map(s => ({value:s,label:s})) : [{value:"BTCUSDT",label:"BTCUSDT"}]} />
          <Button variant="ghost" icon={<RefreshCw className="w-4 h-4" />} onClick={() => load(selectedSymbol)}>Refresh</Button>
        </div>
      </div>

      <div className="grid grid-cols-4 gap-4">
        <Card className="flex items-center gap-4">
          <div className="p-3 bg-indigo-500/20 rounded-xl">
            {regime === "BULL" ? <TrendingUp className="w-6 h-6 text-emerald-400" /> : regime === "BEAR" ? <TrendingDown className="w-6 h-6 text-red-400" /> : <Minus className="w-6 h-6 text-yellow-400" />}
          </div>
          <div><p className="text-sm text-slate-400">Regime</p><p className="text-xl font-bold text-white">{regime}</p></div>
        </Card>
        <Card><p className="text-sm text-slate-400">Total Signals</p><p className="text-2xl font-bold text-white">{allSigs.length}</p></Card>
        <Card><p className="text-sm text-slate-400">Win Rate</p><p className={`text-2xl font-bold ${wr>=50?"text-emerald-400":"text-red-400"}`}>{wr.toFixed(1)}%</p></Card>
        <Card><p className="text-sm text-slate-400">Avg Return</p><p className={`text-2xl font-bold ${avgRet>=0?"text-emerald-400":"text-red-400"}`}>{avgRet>=0?"+":""}{avgRet.toFixed(2)}%</p></Card>
      </div>

      <div className="grid grid-cols-2 gap-6">
        <Card>
          <CardHeader title="Regime Breakdown" />
          <div className="space-y-2">
            {regimeDist.map(r => (
              <div key={r.name} className="flex items-center gap-3">
                <span className="w-20 text-sm text-slate-400">{r.name}</span>
                <div className="flex-1 bg-slate-800 rounded-full h-5 overflow-hidden">
                  <div className="h-full bg-indigo-500/70 rounded-full flex items-center px-2"
                    style={{ width: `${(r.value / allSigs.length * 100)}%` }}>
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
            {[
              ["Total", allSigs.length],
              ["Wins",  allSigs.filter(s=>s.status==="WIN").length],
              ["Losses",allSigs.filter(s=>s.status==="LOSS").length],
              ["Win Rate", `${wr.toFixed(1)}%`],
              ["Avg Return", `${avgRet>=0?"+":""}${avgRet.toFixed(2)}%`],
            ].map(([l, v]) => (
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
