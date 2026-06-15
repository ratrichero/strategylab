import { create } from "zustand";
import { persist } from "zustand/middleware";

export interface ResearchQuery {
  id: string;
  name: string;
  folder_path: string;
  description: string;
  sql_text: string;
  parameters: Record<string, any>;
  chart_config: any;
  created_at: string;
  last_used_at: string;
  is_pinned: boolean;
}

interface AppState {
  sidebarCollapsed: boolean;
  toggleSidebar: () => void;
  darkMode: boolean;
  toggleDarkMode: () => void;
  tradingMode: any;
  setTradingMode: (m: any) => void;
  priceFeedHealthy: boolean;
  priceFeedMode: string;
  priceFeedSymbols: number;
  setPriceFeed: (h: boolean, m: string, s: number) => void;
  activeStrategies: string[];
  setActiveStrategies: (s: string[]) => void;
  killSwitchActive: boolean;
  setKillSwitchActive: (v: boolean) => void;
  researchQueries: ResearchQuery[];
  addResearchQuery: (q: ResearchQuery) => void;
  updateResearchQuery: (id: string, updates: Partial<ResearchQuery>) => void;
  deleteResearchQuery: (id: string) => void;
  toggleQueryPin: (id: string) => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      darkMode: true,
      toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),
      tradingMode: null,
      setTradingMode: (m) => set({ tradingMode: m }),
      priceFeedHealthy: false,
      priceFeedMode: "stopped",
      priceFeedSymbols: 0,
      setPriceFeed: (h, m, s) => set({ priceFeedHealthy: h, priceFeedMode: m, priceFeedSymbols: s }),
      activeStrategies: ["candlestick"],
      setActiveStrategies: (s) => set({ activeStrategies: s }),
      killSwitchActive: false,
      setKillSwitchActive: (v) => set({ killSwitchActive: v }),
      researchQueries: [],
      addResearchQuery: (q) => set((s) => ({ researchQueries: [...s.researchQueries, q] })),
      updateResearchQuery: (id, updates) => set((s) => ({
        researchQueries: s.researchQueries.map((q) => q.id === id ? { ...q, ...updates } : q),
      })),
      deleteResearchQuery: (id) => set((s) => ({
        researchQueries: s.researchQueries.filter((q) => q.id !== id),
      })),
      toggleQueryPin: (id) => set((s) => ({
        researchQueries: s.researchQueries.map((q) => q.id === id ? { ...q, is_pinned: !q.is_pinned } : q),
      })),
    }),
    {
      name: "quant-lab-v2",
      partialize: (s) => ({
        sidebarCollapsed: s.sidebarCollapsed,
        darkMode: s.darkMode,
        activeStrategies: s.activeStrategies,
        researchQueries: s.researchQueries,
      }),
    }
  )
);
