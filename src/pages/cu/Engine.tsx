import { useState, useEffect } from "react";
import { Card, CardHeader } from "../components/ui/Card";
import { DataTable } from "../components/ui/Table";
import { PercentChangeBadge } from "../components/ui/Badge";
import { Cpu, Loader2, RefreshCw } from "lucide-react";
import { Button } from "../components/ui/Button";
import { engine } from "../services/api";

export function Engine() {
  const [versions, setVersions] = useState<any[]>([]);
  const [status,   setStatus]   = useState<any>(null);
  const [loading,  setLoading]  = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const [v, s] = await Promise.all([
        engine.versions().catch(() => []),
        engine.status().catch(() => null),
      ]);
      setVersions(v);
      setStatus(s);
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const cols = [
    { key: "engine_version", header: "Version",    sortable: true },
    { key: "total_trades",   header: "Trades",     sortable: true, align: "right" as const },
    { key: "wins",           header: "Wins",       sortable: true, align: "right" as const },
    { key: "winrate",        header: "Win Rate",   sortable: true, align: "right" as const,
      render: (v: number) => <span className={v>=50?"text-emerald-400":"text-red-400"}>{Number(v).toFixed(1)}%</span> },
    { key: "avg_return",     header: "Avg Return", sortable: true,
      render: (v: number) => <PercentChangeBadge value={Number(v)||0} /> },
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

      {/* Status */}
      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[
            { label: "Active Strategies",  value: status.active_strategies },
            { label: "Top Limit",          value: status.top_limit },
            { label: "Scheduler",          value: status.scheduler_on ? "🟢 ON" : "🔴 OFF" },
            { label: "Trading Mode",       value: status.trading_mode?.mode || "—" },
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
        {versions.length
          ? <DataTable columns={cols} data={versions} pageSize={20} />
          : <div className="h-48 flex items-center justify-center text-slate-500">No engine version data</div>
        }
      </Card>
    </div>
  );
}
