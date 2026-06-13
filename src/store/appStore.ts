import { create } from "zustand";
import { persist } from "zustand/middleware";

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
    }),
    {
      name: "quant-lab-v2",
      partialize: (s) => ({
        sidebarCollapsed: s.sidebarCollapsed,
        darkMode: s.darkMode,
        activeStrategies: s.activeStrategies,
      }),
    }
  )
);
