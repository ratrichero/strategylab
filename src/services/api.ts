// Unified API client — all calls through here
const BASE = import.meta.env.VITE_API_BASE || "";
const KEY  = import.meta.env.VITE_API_KEY  || "";

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> || {}),
  };
  if (KEY) headers["X-API-Key"] = KEY;
  // ← CHANGED: thêm credentials: "include" để gửi cookie auth
  const res = await fetch(`${BASE}${path}`, { ...options, headers, credentials: "include" });
  // ← CHANGED: auto redirect về login nếu 401
  if (res.status === 401) {
    if (window.location.pathname !== "/login") {
      window.location.assign("/login");
    }
    throw new Error("Unauthorized");
  }
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

// ============================================================
// AUTH API (public — không cần auth cookie)
// ============================================================

export const auth = {
  setupStatus: async () => {
    const r = await fetch(`${BASE}/auth/setup-status`, { credentials: "include" });
    return r.json();
  },
  setup: async (username: string, password: string, confirmPassword: string) => {
    const r = await fetch(`${BASE}/auth/setup`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password, confirm_password: confirmPassword }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || "Setup failed");
    }
    return r.json();
  },
  login: async (username: string, password: string) => {
    const r = await fetch(`${BASE}/auth/login`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({ detail: r.statusText }));
      throw new Error(err.detail || "Login failed");
    }
    return r.json();
  },
  logout: async () => {
    await fetch(`${BASE}/auth/logout`, { method: "POST", credentials: "include" });
  },
  changePassword: (currentPassword: string, newPassword: string, confirmPassword: string) =>
    req<any>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      }),
    }),
  me: async () => {
    const r = await fetch(`${BASE}/auth/me`, { credentials: "include" });
    if (!r.ok) return null;
    return r.json();
  },
};

// ============================================================
// APP ROLE & LICENSE API
// ============================================================

export const appRoleApi = {
  get: () => req<any>("/api/app-role"),
  botLicenseInfo: () => req<any>("/api/bot-license-info"),
};

// ============================================================
// ADMIN BOT MANAGEMENT API (cần admin role)
// ============================================================

export const adminBots = {
  dashboard: () => req<any>("/admin/dashboard"),
  list: () => req<any>("/admin/bots"),
  create: (data: any) =>
    req<any>("/admin/bots", { method: "POST", body: JSON.stringify(data) }),
  get: (id: number) => req<any>(`/admin/bots/${id}`),
  update: (id: number, data: any) =>
    req<any>(`/admin/bots/${id}`, { method: "PUT", body: JSON.stringify(data) }),
  delete: (id: number) =>
    req<any>(`/admin/bots/${id}`, { method: "DELETE" }),
  activate: (id: number) =>
    req<any>(`/admin/bots/${id}/activate`, { method: "POST" }),
  disable: (id: number) =>
    req<any>(`/admin/bots/${id}/disable`, { method: "POST" }),
  extendLicense: (id: number, newExpiresAt: string) =>
    req<any>(`/admin/bots/${id}/extend-license`, {
      method: "POST", body: JSON.stringify({ new_expires_at: newExpiresAt }),
    }),
  overrideDbUrl: (id: number, newUrl: string) =>
    req<any>(`/admin/bots/${id}/override-db-url`, {
      method: "POST", body: JSON.stringify({ new_database_url: newUrl }),
    }),
  rotateSecret: (id: number) =>
    req<any>(`/admin/bots/${id}/rotate-secret`, { method: "POST" }),
  resetDashboardPassword: (id: number, dashboardUsername: string, newPassword: string) =>
    req<any>(`/admin/bots/${id}/reset-dashboard-password`, {
      method: "POST",
      body: JSON.stringify({
        dashboard_username: dashboardUsername || null,
        new_password: newPassword,
      }),
    }),
  heartbeats: (id: number, limit = 50) =>
    req<any>(`/admin/bots/${id}/heartbeats?limit=${limit}`),
  auditLogs: (id: number, limit = 50) =>
    req<any>(`/admin/bots/${id}/audit-logs?limit=${limit}`),
};

// ============================================================
// EXISTING APIs — GIỮA NGUYÊN 100%
// ============================================================

export const signals = {
  list: (p: Record<string, any> = {}) => req<any>(`/api/signals${qs(p)}`),
  get: (id: number) => req<any>(`/api/signals/${id}`),
};

export const pending = {
  list: (p: Record<string, any> = {}) => req<any>(`/api/pending-signals${qs(p)}`),
};

export const analyticsSupport = {
  filterOptions: (p: Record<string, any> = {}) => req<any>(`/api/filter-options${qs(p)}`),
  preview: (body: Record<string, any>) =>
    req<any>("/api/analytics/preview", { method: "POST", body: JSON.stringify(body) }),
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
