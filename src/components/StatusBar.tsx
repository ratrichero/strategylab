import { useEffect } from "react";
import { useAppStore } from "../store/appStore";
import { tradingMode as tmApi, engine } from "../services/api";

export function StatusBar() {
  const { tradingMode, setTradingMode, priceFeedHealthy, priceFeedMode, priceFeedSymbols, setPriceFeed } = useAppStore();

  useEffect(() => {
    const load = async () => {
      try {
        const [m, f] = await Promise.all([tmApi.get(), engine.priceFeed()]);
        setTradingMode(m);
        setPriceFeed(f.healthy, f.mode, f.symbols_count);
      } catch {}
    };
    load();
    const i = setInterval(load, 15000);
    return () => clearInterval(i);
  }, []);

  const modeColor = {
    PAPER:   "bg-blue-900/50 text-blue-300 border-blue-700/50",
    TESTNET: "bg-yellow-900/50 text-yellow-300 border-yellow-700/50",
    LIVE:    "bg-red-900/50 text-red-300 border-red-700/50 animate-pulse",
  };

  return (
    <div className="flex items-center gap-3 text-xs">
      {tradingMode && (
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium border ${modeColor[tradingMode.mode as keyof typeof modeColor] || "bg-slate-700 text-slate-300 border-slate-600"}`}>
          {tradingMode.mode === "PAPER" ? "📋" : tradingMode.mode === "TESTNET" ? "🧪" : "💰"}
          {tradingMode.mode}
        </span>
      )}
      <span className="flex items-center gap-1 text-slate-400">
        <span className={`w-2 h-2 rounded-full ${priceFeedHealthy ? "bg-emerald-400" : "bg-red-400 animate-pulse"}`} />
        {priceFeedHealthy ? `${priceFeedMode?.toUpperCase()}: ${priceFeedSymbols} sym` : "Feed ⚠️"}
      </span>
    </div>
  );
}
