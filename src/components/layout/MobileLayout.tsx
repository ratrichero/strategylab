// @ts-nocheck
import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "../../utils/cn";
import { useAppStore } from "../../store/appStore";
import { KillSwitch } from "../KillSwitch";
import {
  LayoutDashboard, Wallet, Clock, Zap, Settings, Menu, X,
  ShieldOff, TrendingUp, BarChart3, Microscope, Cpu, Ban, FlaskConical, Code2,
} from "lucide-react";

const mainTabs = [
  { name: "Home", href: "/", icon: LayoutDashboard },
  { name: "Account", href: "/account", icon: Wallet },
  { name: "Pending", href: "/pending-signals", icon: Clock },
  { name: "Signals", href: "/signals", icon: Zap },
  { name: "More", href: "#more", icon: Menu },
];

const allPages = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Account", href: "/account", icon: Wallet },
  { name: "Pending", href: "/pending-signals", icon: Clock },
  { name: "Strategy", href: "/research", icon: Microscope },
  { name: "Signals", href: "/signals", icon: Zap },
  { name: "Edge Discovery", href: "/edge-discovery", icon: TrendingUp },
  { name: "Indicators", href: "/indicators", icon: BarChart3 },
  { name: "Blocked", href: "/blocked", icon: Ban },
  { name: "Market", href: "/market", icon: TrendingUp },
  { name: "Simulation", href: "/simulation", icon: FlaskConical },
  { name: "Query Lab", href: "/query-lab", icon: Code2 },
  { name: "Engine", href: "/engine", icon: Cpu },
  { name: "Settings", href: "/settings", icon: Settings },
];

export function MobileLayout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { tradingMode } = useAppStore();
  const [menuOpen, setMenuOpen] = useState(false);

  const mode = tradingMode?.mode || "";
  const modeColor = { PAPER: "text-blue-400", TESTNET: "text-yellow-400", LIVE: "text-red-400" };
  const modeIcon = { PAPER: "📋", TESTNET: "🧪", LIVE: "💰" };

  const pageTitle = allPages.find(
    n => n.href === location.pathname || (n.href !== "/" && location.pathname.startsWith(n.href))
  )?.name || "Dashboard";

  return (
    <div className="min-h-screen bg-slate-900 flex flex-col">
      {/* Top bar */}
      <header className="sticky top-0 z-40 flex items-center justify-between px-4 py-3 bg-slate-900/95 backdrop-blur-sm border-b border-slate-800">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg flex items-center justify-center">
            <FlaskConical className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-white text-sm">{pageTitle}</span>
        </div>
        <div className="flex items-center gap-2">
          {mode && (
            <span className={`text-xs font-medium ${modeColor[mode] || "text-slate-400"}`}>
              {modeIcon[mode]} {mode}
            </span>
          )}
          <KillSwitch />
        </div>
      </header>

      {/* Content */}
      <main className="flex-1 overflow-auto p-3 pb-20">
        {children}
      </main>

      {/* Bottom tab bar */}
      <nav className="fixed bottom-0 left-0 right-0 z-50 bg-slate-900/95 backdrop-blur-sm border-t border-slate-800 safe-area-pb">
        <div className="flex items-center justify-around py-2">
          {mainTabs.map(tab => {
            if (tab.href === "#more") {
              return (
                <button
                  key="more"
                  onClick={() => setMenuOpen(true)}
                  className="flex flex-col items-center gap-0.5 px-2 py-1 text-slate-500"
                >
                  <Menu className="w-5 h-5" />
                  <span className="text-[10px]">More</span>
                </button>
              );
            }
            const active = location.pathname === tab.href;
            return (
              <Link
                key={tab.href}
                to={tab.href}
                className={cn(
                  "flex flex-col items-center gap-0.5 px-2 py-1 rounded-lg transition-colors",
                  active ? "text-indigo-400" : "text-slate-500"
                )}
              >
                <tab.icon className="w-5 h-5" />
                <span className="text-[10px] font-medium">{tab.name}</span>
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Full menu drawer */}
      {menuOpen && (
        <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" onClick={() => setMenuOpen(false)}>
          <div
            className="absolute right-0 top-0 bottom-0 w-72 bg-slate-900 border-l border-slate-800 p-4 overflow-auto"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-6">
              <span className="font-bold text-white">All Pages</span>
              <button onClick={() => setMenuOpen(false)} className="p-1 text-slate-400">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="space-y-1">
              {allPages.map(page => {
                const active = location.pathname === page.href;
                return (
                  <Link
                    key={page.href}
                    to={page.href}
                    onClick={() => setMenuOpen(false)}
                    className={cn(
                      "flex items-center gap-3 px-3 py-3 rounded-lg transition-colors",
                      active
                        ? "bg-indigo-600/20 text-indigo-400"
                        : "text-slate-400 hover:bg-slate-800"
                    )}
                  >
                    <page.icon className="w-5 h-5" />
                    <span className="font-medium">{page.name}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
