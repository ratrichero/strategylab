import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { cn } from "../../utils/cn";
import { useAppStore } from "../../store/appStore";
import { StatusBar } from "../StatusBar";
import { KillSwitch } from "../KillSwitch";
import { LayoutDashboard, TrendingUp, Zap, BarChart3, Cpu, Ban, FlaskConical, Code2, Settings, Microscope, ChevronLeft, ChevronRight, Bell, Search, Clock } from "lucide-react";

const nav = [
  { name: "Dashboard", href: "/", icon: LayoutDashboard },
  { name: "Strategy Research", href: "/research", icon: Microscope },
  { name: "Market", href: "/market", icon: TrendingUp },
  { name: "Signals", href: "/signals", icon: Zap },
  { name: "Pending Signals", href: "/pending-signals", icon: Clock },
  { name: "Edge Discovery", href: "/edge-discovery", icon: TrendingUp },
  { name: "Indicators", href: "/indicators", icon: BarChart3 },
  { name: "Engine", href: "/engine", icon: Cpu },
  { name: "Blocked", href: "/blocked", icon: Ban },
  { name: "Simulation", href: "/simulation", icon: FlaskConical },
  { name: "Query Lab", href: "/query-lab", icon: Code2 },
];

export function Layout({ children }: { children: React.ReactNode }) {
  const location = useLocation();
  const { sidebarCollapsed, toggleSidebar, theme } = useAppStore();
  const [searchOpen, setSearchOpen] = useState(false);
  const pageTitle = [...nav, { href: "/settings", name: "Settings" }].find(n => n.href === location.pathname || (n.href !== "/" && location.pathname.startsWith(n.href)))?.name || "Dashboard";
  const themeClass = theme === "trading" ? "theme-trading" : theme === "light" ? "theme-light-gold" : "";

  return (
    <div className={cn("min-h-screen bg-slate-900 flex", themeClass)}>
      <aside className={cn("fixed left-0 top-0 h-screen z-50 flex flex-col transition-all duration-300 bg-slate-800/50 backdrop-blur-xl border-r border-slate-700/50", sidebarCollapsed ? "w-16" : "w-64")}>
        <div className="h-16 flex items-center justify-between px-4 border-b border-slate-700/50 flex-shrink-0">
          {!sidebarCollapsed && (<div className="flex items-center gap-2"><div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg flex items-center justify-center"><FlaskConical className="w-5 h-5 text-white" /></div><span className="font-bold text-white">Quant Lab</span></div>)}
          <button onClick={toggleSidebar} className="p-1.5 rounded-lg hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors ml-auto">{sidebarCollapsed ? <ChevronRight className="w-5 h-5" /> : <ChevronLeft className="w-5 h-5" />}</button>
        </div>
        <nav className="flex-1 px-2 py-4 space-y-1 overflow-y-auto">
          {nav.map((item) => {
            const active = location.pathname === item.href || (item.href !== "/" && location.pathname.startsWith(item.href));
            return (<Link key={item.href} to={item.href} title={sidebarCollapsed ? item.name : undefined} className={cn("flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors", active ? "bg-indigo-600/20 text-indigo-400 border border-indigo-500/30" : "text-slate-400 hover:bg-slate-700/50 hover:text-white")}><item.icon className="w-5 h-5 flex-shrink-0" />{!sidebarCollapsed && <span className="font-medium">{item.name}</span>}</Link>);
          })}
        </nav>
        <div className="p-2 border-t border-slate-700/50 flex-shrink-0">
          <Link to="/settings" title={sidebarCollapsed ? "Settings" : undefined} className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-400 hover:bg-slate-700/50 hover:text-white transition-colors"><Settings className="w-5 h-5" />{!sidebarCollapsed && <span className="font-medium">Settings</span>}</Link>
        </div>
      </aside>
      <div className={cn("flex-1 flex flex-col min-h-screen transition-all duration-300", sidebarCollapsed ? "ml-16" : "ml-64")}>
        <header className="h-16 flex-shrink-0 sticky top-0 z-40 flex items-center justify-between px-6 bg-slate-800/30 backdrop-blur-sm border-b border-slate-700/50">
          <h1 className="text-lg font-semibold text-white">{pageTitle}</h1>
          <div className="flex items-center gap-3">
            <StatusBar /><KillSwitch />
            <button onClick={() => setSearchOpen(true)} className="p-2 rounded-lg hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors"><Search className="w-5 h-5" /></button>
            <button className="relative p-2 rounded-lg hover:bg-slate-700/50 text-slate-400 hover:text-white transition-colors"><Bell className="w-5 h-5" /><span className="absolute top-1.5 right-1.5 w-2 h-2 bg-indigo-500 rounded-full" /></button>
            <div className="w-8 h-8 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-full flex items-center justify-center text-white font-medium text-sm ml-1">A</div>
          </div>
        </header>
        {searchOpen && (
          <div className="fixed inset-0 z-50 bg-slate-900/80 backdrop-blur-sm flex items-start justify-center pt-24 px-4" onClick={() => setSearchOpen(false)}>
            <div className="w-full max-w-2xl bg-slate-800 border border-slate-700 rounded-xl shadow-2xl p-4" onClick={(e) => e.stopPropagation()}>
              <input autoFocus type="text" placeholder="Search signals, patterns, queries..." className="w-full bg-transparent text-white text-lg placeholder:text-slate-500 outline-none" onKeyDown={(e) => e.key === "Escape" && setSearchOpen(false)} />
              <div className="mt-4 text-sm text-slate-500">Press <kbd className="px-1.5 py-0.5 bg-slate-700 rounded text-xs text-slate-300">Esc</kbd> to close</div>
            </div>
          </div>
        )}
        <main className="flex-1 p-6 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
