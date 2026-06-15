// Unified API client — all calls through here
const BASE = import.meta.env.VITE_API_BASE || "";
const KEY  = import.meta.env.VITE_API_KEY  || "";

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  };
  if (KEY) headers["X-API-Key"] = KEY;
  const res = await fetch(`${BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

function qs(p: Record<string, any>): string {
  const u = new URLSearchParams();
  Object.entries(p).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "") u.append(k, String(v));
  });
  const s = u.toString();
  return s ? `?${s}` : "";
}

export const signals = {
  list: (p: Record<string, any> = {}) => req<any>(`/api/signals${qs(p)}`),
  get: (id: number) => req<any>(`/api/signals/${id}`),
};

export const pending = {
  list: (p: Record<string, any> = {}) => req<any>(`/api/pending-signals${qs(p)}`),
};

export const engine = {
  status:   () => req<any>("/api/engine/status"),
  versions: () => req<any[]>("/api/engine/versions"),
  priceFeed:() => req<any>("/api/price-feed/status"),
};

export const config = {
  getAll: () => req<Record<string, string>>("/api/app-config"),
  update: (u: Record<string, string>) =>
    req<any>("/api/app-config", { method: "PUT", body: JSON.stringify(u) }),
};

export const tradingMode = {
  get: () => req<any>("/api/trading-mode"),
  set: (mode: string) =>
    req<any>("/api/trading-mode", { method: "PUT", body: JSON.stringify({ mode }) }),
};

export const strategies = {
  list: () => req<any>("/api/strategies"),
  setActive: (list: string[]) =>
    req<any>("/api/strategies/active", { method: "PUT", body: JSON.stringify({ strategies: list }) }),
};

export const otf = {
  get:    () => req<any>("/api/open-trade-filter"),
  save:   (c: any) => req<any>("/api/open-trade-filter", { method: "PUT", body: JSON.stringify(c) }),
  status: () => req<any>("/api/open-trade-filter/status"),
};

export const prefill = {
  get: async () => {
    const cfg = await config.getAll();
    try { return JSON.parse(cfg["PREFILL_CONFIG"] || "{}"); }
    catch { return { enabled: true }; }
  },
  save: (c: any) => config.update({ PREFILL_CONFIG: JSON.stringify(c) }),
};

export const ml = {
  evaluate: (days = 30) => req<any>(`/api/ml/evaluate?days=${days}`),
  retrain:  (force = false) => req<any>(`/api/retrain?force=${force}`, { method: "POST" }),
  status:   () => req<any>("/api/ml/status"),
};

export const admin = {
  cancelAllPending: () => req<any>("/api/admin/cancel-all-pending", { method: "POST" }),
  refreshViews: () => req<any>("/api/admin/refresh-views", { method: "POST" }),
  closeAllTrades: () => req<any>("/api/monitor", { method: "POST" }),
  killSwitch: async () => {
    await Promise.all([
      req<any>("/api/admin/cancel-all-pending", { method: "POST" }),
      req<any>("/api/monitor", { method: "POST" }),
    ]);
  },
};

export const research = {
  run: (body: any) =>
    req<any>("/api/research/run", { method: "POST", body: JSON.stringify(body) }),
};

export const analysis = {
  run: (query: string, params: Record<string, any> = {}) =>
    req<any>("/api/signal-analysis", { method: "POST", body: JSON.stringify({ query, params }) }),
};

export const edge = {
  run: (query: string, params: Record<string, any> = {}) =>
    req<any>("/api/signal-analysis", { method: "POST", body: JSON.stringify({ query, params }) }),
};

export const queryLab = {
  execute: (sql: string) =>
    req<any>("/api/query-lab/execute", { method: "POST", body: JSON.stringify({ sql }) }),
  schema: () => req<any>("/api/schema"),
};

export const scanDebug = {
  list: (p: Record<string, any> = {}) => req<any>(`/api/scan-debug${qs(p)}`),
  blockReasons: () => req<any[]>("/api/scan-debug/block-reasons"),
};

export async function fetchBinancePrices(): Promise<Record<string, number>> {
  try {
    const r = await fetch("https://fapi.binance.com/fapi/v1/ticker/price");
    const d = await r.json();
    const p: Record<string, number> = {};
    d.forEach((i: any) => { p[i.symbol] = parseFloat(i.price); });
    return p;
  } catch { return {}; }
}
