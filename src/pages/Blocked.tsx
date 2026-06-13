import { useState, useEffect, useMemo } from "react";
import { Card, CardHeader } from "../components/ui/Card";
import { DataTable } from "../components/ui/Table";
import { Select } from "../components/ui/Select";
import { Button } from "../components/ui/Button";
import { DirectionBadge, ScoreBadge } from "../components/ui/Badge";
import { Ban, Loader2, RefreshCw } from "lucide-react";
import { utcToLocal } from "../utils/format";

const API = "/api";

export function Blocked() {
  const [data, setData]     = useState<any[]>([]);
  const [stats, setStats]   = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [page, setPage]     = useState(1);
  const [reasonFilter, setReasonFilter] = useState("all");

  const load = async () => {
    setLoading(true);
    try {
      const [d, s] = await Promise.all([
        fetch(`${API}/scan-debug?passed_score=false&limit=50&page=${page}${reasonFilter !== "all" ? `&block_reason=${reasonFilter}` : ""}`).then(r => r.json()),
        fetch(`${API}/scan-debug/block-reasons`).then(r => r.json()),
      ]);
      setData(d.data || []);
      setStats(s || []);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [page, reasonFilter]);

  const columns = [
    { key: "symbol",       header: "Symbol",   sortable: true },
    { key: "strategy_name",header: "Strategy", sortable: true, render: (v: string) => <span className="text-xs text-slate-300">{v || "—"}</span> },
    { key: "direction",    header: "Dir",      render: (v: string) => <DirectionBadge direction={v || "LONG"} /> },
    { key: "block_reason", header: "Reason",   sortable: true,
      render: (v: string) => {
        const color = v?.startsWith("OTF") ? "text-orange-400" : v?.startsWith("PREFILL") ? "text-yellow-400" : v?.startsWith("HTF") ? "text-purple-400" : "text-red-400";
        return <span className={`text-xs font-medium ${color}`}>{v || "—"}</span>;
      }
    },
    { key: "total_score",  header: "Score",    sortable: true, render: (v: number) => <ScoreBadge value={v || 0} /> },
    { key: "ml_prob",      header: "ML",       sortable: true, render: (v: number) => v ? <span className={v >= 0.6 ? "text-emerald-400" : "text-slate-400"}>{(v*100).toFixed(0)}%</span> : "—" },
    { key: "regime",       header: "Regime",   sortable: true },
    { key: "candle_time",  header: "Time",     sortable: true, render: (v: string) => <span className="text-xs text-slate-400">{utcToLocal(v)}</span> },
  ];

  const reasonOptions = [
    { value: "all", label: "All Reasons" },
    ...stats.map((s: any) => ({ value: s.block_reason, label: `${s.block_reason} (${s.count})` })),
  ];

  // Group stats by prefix
  const statGroups = useMemo(() => {
    const g: Record<string, number> = {};
    stats.forEach((s: any) => {
      const prefix = s.block_reason?.includes("::") ? s.block_reason.split("::")[0] : s.block_reason || "other";
      g[prefix] = (g[prefix] || 0) + Number(s.count);
    });
    return g;
  }, [stats]);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white flex items-center gap-2">
            <Ban className="w-6 h-6 text-red-400" /> Blocked Signals
          </h2>
          <p className="text-slate-400 mt-1">Tín hiệu bị bộ lọc từ chối (OTF, Pre-fill, HTF, Funding...)</p>
        </div>
        <Button variant="ghost" icon={<RefreshCw className="w-4 h-4" />} onClick={load}>Refresh</Button>
      </div>

      {/* Stats by prefix */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        {Object.entries(statGroups).map(([key, count]) => (
          <div key={key} className="p-3 bg-slate-800/50 rounded-xl border border-slate-700/50 text-center">
            <div className="text-xs text-slate-400 truncate">{key}</div>
            <div className="text-2xl font-bold text-white mt-1">{count}</div>
          </div>
        ))}
      </div>

      {/* Filter + Table */}
      <Card>
        <div className="flex items-center gap-4 mb-4">
          <div className="w-64">
            <Select value={reasonFilter} onChange={(v) => { setReasonFilter(v); setPage(1); }}
              options={reasonOptions} />
          </div>
          <span className="text-sm text-slate-400">{data.length} records</span>
        </div>
        {loading
          ? <div className="h-64 flex justify-center items-center"><Loader2 className="animate-spin text-indigo-500 w-8 h-8" /></div>
          : <DataTable columns={columns} data={data} pageSize={20} emptyMessage="No blocked signals found" />
        }
      </Card>
    </div>
  );
}
