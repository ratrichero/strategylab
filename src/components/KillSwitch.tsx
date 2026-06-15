import { useState } from "react";
import { ShieldOff, AlertTriangle } from "lucide-react";
import { Button } from "./ui/Button";
import { useAppStore } from "../store/appStore";
import toast from "react-hot-toast";

export function KillSwitch() {
  const { tradingMode, setKillSwitchActive } = useAppStore();
  const [loading, setLoading] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const handleKill = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/admin/kill-switch", { method: "POST" });
      const data = await res.json();
      setKillSwitchActive(true);
      toast.success(`🚨 Kill Switch: ${data.pending_cancelled} pending cancelled, ${data.trades_closed} trades closed`);
    } catch (e: any) { toast.error(`Kill Switch failed: ${e.message}`); }
    finally { setLoading(false); setConfirm(false); }
  };
  return (
    <>
      <Button variant="danger" size="sm" icon={<ShieldOff className="w-4 h-4" />} onClick={() => setConfirm(true)}>Kill Switch</Button>
      {confirm && (
        <div className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="bg-slate-800 border border-red-500/50 rounded-xl p-6 max-w-md w-full shadow-2xl">
            <div className="flex items-center gap-3 mb-4"><AlertTriangle className="w-6 h-6 text-red-400" /><div><h3 className="font-bold text-white">Confirm Kill Switch</h3><p className="text-sm text-slate-400">Mode: {tradingMode?.mode || "UNKNOWN"}</p></div></div>
            <ul className="text-sm text-slate-400 mb-6 space-y-1.5 ml-4 list-disc"><li>Cancel ALL pending signals</li><li>Close ALL open signals</li>{tradingMode?.mode === "LIVE" && <li className="text-red-300 font-medium">LIVE: real Binance orders will be closed</li>}</ul>
            <div className="flex gap-3"><Button variant="danger" className="flex-1" loading={loading} onClick={handleKill}>Confirm Kill</Button><Button variant="ghost" className="flex-1" onClick={() => setConfirm(false)}>Cancel</Button></div>
          </div>
        </div>
      )}
    </>
  );
}
