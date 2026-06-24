import { buildAnalyticsFilter } from '../utils/analyticsFilters';

const API = '/api';

async function postJSON<T>(url: string, body: unknown): Promise<T> {
  const r = await fetch(`${API}${url}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

export function fetchDashboardOverview(filters: Record<string, unknown>) {
  return postJSON<{ total_trades: number; trades_today: number; wins: number; losses: number; win_rate: number; profit_factor: number; expectancy: number; sharpe: number; streaks: any; direction: any; avg_duration_seconds: number | null; avg_duration_display: string }>('/dashboard/overview', buildAnalyticsFilter(filters));
}

export function fetchDashboardPortfolio(filters: Record<string, unknown>, initial_capital: number, position_size: number) {
  return postJSON<{ compounding: any; fixed: any }>('/dashboard/portfolio', { ...buildAnalyticsFilter(filters), initial_capital, position_size });
}

export function fetchDashboardBreakdowns(filters: Record<string, unknown>) {
  return postJSON<{ regime_breakdown: any[]; heatmap: any[] }>('/dashboard/breakdowns', buildAnalyticsFilter(filters));
}

export function fetchDashboardRecentTrades(filters: Record<string, unknown>, page: number, limit: number, search_symbols?: string) {
  return postJSON<{ data: any[]; total: number; page: number; limit: number; pages: number }>('/dashboard/recent-trades', { ...buildAnalyticsFilter(filters), page, limit, search_symbols });
}