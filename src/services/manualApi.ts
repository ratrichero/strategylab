import { buildAnalyticsFilter } from '../utils/analyticsFilters';

const API = '/api';

export interface ManualBehaviorRequest {
  start_date?: string;
  end_date?: string;
  date_field?: string;
  symbols?: string;
  symbol_mode?: 'include' | 'exclude';
  timeframes?: string[];
  strategies?: string[];
  patterns?: string[];
  regimes?: string[];
  directions?: string[];
  engine_version?: string;
  engine_mode?: 'only' | 'newest' | 'older';
  score_min?: number;
  score_max?: number;
  include_manual?: boolean;
}

export interface ManualBehaviorOverviewResponse {
  total: number;
  manual_count: number;
  wins: number;
  win_rate: number;
  manual_wins: number;
  manual_win_rate: number;
  avg_std_pnl: number;
  avg_manual_pnl: number;
  planned_total: number;
  actual_total: number;
  impact: number;
}

export interface ComparisonGroup {
  group_type: 'standard' | 'manual';
  total: number;
  wins: number;
  win_rate: number;
  avg_pnl: number;
  profit_factor: number;
}

export interface ManualBehaviorComparisonResponse {
  standard: ComparisonGroup;
  manual: ComparisonGroup;
}

export interface ManualBehaviorTradesRequest extends ManualBehaviorRequest {
  page: number;
  limit: number;
  search_symbols: string;
  sort_by: 'exit_time' | 'candle_time' | 'result_percent' | 'score';
  sort_order: 'desc' | 'asc';
}

export interface ManualTradeItem {
  id: number;
  symbol: string;
  direction: string;
  timeframe: string;
  pattern: string;
  score: number;
  entry_price: number;
  exit_price: number;
  result_percent: number;
  status: string;
  derived_status: string;
  derived_pnl: number;
  is_manual: boolean;
  regime: string;
  strategy_name: string;
  candle_time: string;
  exit_time: string;
}

export interface ManualBehaviorTradesResponse {
  data: ManualTradeItem[];
  total: number;
  page: number;
  limit: number;
  pages: number;
}

async function fetchManualBehaviorOverview(filter: ManualBehaviorRequest): Promise<ManualBehaviorOverviewResponse> {
  const payload = buildAnalyticsFilter(filter);
  
  const res = await fetch(`${API}/manual-behavior/overview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch manual behavior overview');
  return res.json();
}

async function fetchManualBehaviorComparison(filter: ManualBehaviorRequest): Promise<ManualBehaviorComparisonResponse> {
  const payload = buildAnalyticsFilter(filter);
  
  const res = await fetch(`${API}/manual-behavior/comparison`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch manual behavior comparison');
  return res.json();
}

async function fetchManualBehaviorTrades(filter: ManualBehaviorTradesRequest): Promise<ManualBehaviorTradesResponse> {
  const payload = {
    ...buildAnalyticsFilter(filter),
    page: filter.page,
    limit: filter.limit,
    search_symbols: filter.search_symbols,
    sort_by: filter.sort_by,
    sort_order: filter.sort_order,
  };
  
  const res = await fetch(`${API}/manual-behavior/trades`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch manual behavior trades');
  return res.json();
}

export const manualApi = {
  fetchOverview: fetchManualBehaviorOverview,
  fetchComparison: fetchManualBehaviorComparison,
  fetchTrades: fetchManualBehaviorTrades,
};
