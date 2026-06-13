const API_BASE = import.meta.env.VITE_API_BASE || "";
const API_KEY  = import.meta.env.VITE_API_KEY  || "";

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  };
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  return fetch(`${API_BASE}${path}`, { ...options, headers });
}

export interface TradingModeInfo {
  mode: "PAPER" | "TESTNET" | "LIVE";
  is_real_money: boolean;
  description: string;
}

export interface StrategyInfo {
  name: string; active: boolean; total: number;
  wins: number; losses: number;
  winrate: number | null; avg_return: number | null; avg_score: number | null;
}

export const getTradingMode = () => apiFetch("/api/trading-mode").then(r => r.json());
export const setTradingMode = (mode: string) =>
  apiFetch("/api/trading-mode", { method: "PUT", body: JSON.stringify({ mode }) }).then(r => r.json());

export async function getStrategies(): Promise<StrategyInfo[]> {
  const data = await apiFetch("/api/strategies").then(r => r.json());
  if (Array.isArray(data)) return data;
  const all: string[] = data.all || [];
  const active: string[] = data.active || [];
  return all.map(name => ({ name, active: active.includes(name),
    total: 0, wins: 0, losses: 0, winrate: null, avg_return: null, avg_score: null }));
}

export const updateActiveStrategies = (strategies: string[]) =>
  apiFetch("/api/strategies/active", { method: "PUT", body: JSON.stringify({ strategies }) }).then(r => r.json());

export const getOpenTradeFilter = () => apiFetch("/api/open-trade-filter").then(r => r.json());
export const saveOpenTradeFilter = (config: any) =>
  apiFetch("/api/open-trade-filter", { method: "PUT", body: JSON.stringify(config) }).then(r => r.json());
export const getFilterStatus = () => apiFetch("/api/open-trade-filter/status").then(r => r.json());

export async function getPrefillConfig() {
  const cfg = await apiFetch("/api/app-config").then(r => r.json());
  try { return JSON.parse(cfg["PREFILL_CONFIG"] || '{"enabled":true}'); }
  catch { return { enabled: true }; }
}
export const savePrefillConfig = (config: any) =>
  apiFetch("/api/app-config", { method: "PUT", body: JSON.stringify({ PREFILL_CONFIG: JSON.stringify(config) }) }).then(r => r.json());

export const getEngineStatus = () => apiFetch("/api/engine/status").then(r => r.json());
export const getPriceFeedStatus = () => apiFetch("/api/price-feed/status").then(r => r.json());
export const getMLEvaluation = (days = 30) => apiFetch(`/api/ml/evaluate?days=${days}`).then(r => r.json());
export const triggerRetrain = (force = false) =>
  apiFetch(`/api/retrain?force=${force}`, { method: "POST" }).then(r => r.json());

export const admin = {
  cancelAllPending: () => apiFetch("/api/admin/cancel-all-pending", { method: "POST" }).then(r => r.json()),
  refreshViews: () => apiFetch("/api/admin/refresh-views", { method: "POST" }).then(r => r.json()),
  closeAllTrades: () => apiFetch("/api/monitor", { method: "POST" }).then(r => r.json()),
};

export const queryLab = {
  execute: (sql: string) => apiFetch("/api/query-lab/execute", {
    method: "POST", body: JSON.stringify({ sql })
  }).then(r => r.json()),
  schema: () => apiFetch("/api/schema").then(r => r.json()),
};
