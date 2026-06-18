// @ts-nocheck
import { useEffect, useState } from "react";
import { tradingMode as tmApi, engine } from "../services/api";
import { useAppStore } from "../store/appStore";

export function StatusBar() {
  const {
    tradingMode,
    setTradingMode,
    priceFeedHealthy,
    priceFeedMode,
    priceFeedSymbols,
    setPriceFeed,
  } = useAppStore();

  const [btcOverview, setBtcOverview] = useState(null);

  useEffect(() => {
    const load = async () => {
      try {
        const [m, f, btc] = await Promise.all([
          tmApi.get(),
          engine.priceFeed(),
          fetch("/api/btc-overview").then(r => r.json()).catch(() => null),
        ]);
        if (m) setTradingMode(m);
        if (f) setPriceFeed(f.healthy, f.mode, f.symbols_count);
        if (btc) setBtcOverview(btc);
      } catch (err) {
        console.error("[StatusBar] load failed:", err);
      }
    };

    load();
    const id = setInterval(load, 10000);
    return () => clearInterval(id);
  }, [setTradingMode, setPriceFeed]);

  const mode = (tradingMode?.mode) || "";

  const modeStyle = {
    PAPER:   "bg-blue-900/50 text-blue-300 border-blue-700/50",
    TESTNET: "bg-yellow-900/50 text-yellow-300 border-yellow-700/50",
    LIVE:    "bg-red-900/50 text-red-300 border-red-700/50 animate-pulse",
  };

  const modeIcon = {
    PAPER: "📋", TESTNET: "🧪", LIVE: "💰",
  };

  const feedColor = priceFeedHealthy
    ? "bg-emerald-900/40 text-emerald-300 border-emerald-700/40"
    : "bg-red-900/40 text-red-300 border-red-700/40";

  const regimeDot = (regime) => {
    const colors = {
      BULL:     "bg-green-400",
      BEAR:     "bg-red-400",
      SIDEWAYS: "bg-yellow-400",
    };
    return (
      <span className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${colors[regime] || "bg-slate-500"}`} />
    );
  };

  const btcPrice = btcOverview?.price;

  return (
    <div className="w-full flex items-center justify-between gap-3 px-4 py-2 border-b border-slate-800 bg-slate-950/80 backdrop-blur text-xs">
      <div className="flex items-center gap-2 flex-wrap">

        {/* Trading Mode */}
        {mode ? (
          <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium border ${modeStyle[mode] || "bg-slate-700 text-slate-300 border-slate-600"}`}>
            {modeIcon[mode] || "❔"} {mode}
          </span>
        ) : (
          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium border bg-slate-700 text-slate-400 border-slate-600">
            ⏳ Loading...
          </span>
        )}

        {/* Price Feed */}
        <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium border ${feedColor}`}>
          {priceFeedHealthy ? "🟢" : "🔴"} Feed ({(priceFeedMode || "?").toUpperCase()})
        </span>

        {/* Symbols */}
        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full font-medium border bg-slate-800 text-slate-300 border-slate-700">
          📈 {priceFeedSymbols ?? 0}
        </span>

        {/* BTC Overview */}
        {btcOverview?.timeframes && (
          <span
            className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full font-medium border bg-slate-800 text-slate-300 border-slate-700 cursor-default"
            title={`BTC $${btcPrice?.toLocaleString() || "?"} | Overall: ${btcOverview.summary}`}
          >
            <span className="font-bold text-amber-400">₿</span>
            {btcPrice && (
              <span className="text-white font-mono text-[11px]">
                ${btcPrice.toLocaleString()}
              </span>
            )}
            <span className="text-slate-600 mx-0.5">|</span>
            {["15m", "1h", "4h", "1d"].map(tf => {
              const d = btcOverview.timeframes[tf];
              if (!d || d.regime === "UNKNOWN" || d.regime === "ERROR") return null;
              return (
                <span
                  key={tf}
                  className="inline-flex items-center gap-0.5"
                  title={`${tf}: ${d.regime} | RSI=${d.rsi} | Trend=${d.trend}`}
                >
                  {regimeDot(d.regime)}
                  <span className="text-[10px] opacity-50">{tf}</span>
                </span>
              );
            })}
          </span>
        )}
      </div>

      <div className="text-slate-500 hidden md:block">
        Quant Research Lab
      </div>
    </div>
  );
}
