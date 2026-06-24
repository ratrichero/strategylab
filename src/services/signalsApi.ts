import { buildAnalyticsFilter } from '../utils/analyticsFilters';

const API = '/api';

export interface SignalsOverviewRequest {
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
  initial_capital?: number;
  position_size?: number;
}

export interface SignalsOverviewResponse {
  nav: number;
  total: number;
  scanned: number;
  win_rate: number;
  profit_factor: number;
  expectancy: number;
  score_return_corr: number;
}

export interface GroupPerformanceRequest extends SignalsOverviewRequest {
  group_by: 'pattern' | 'direction' | 'regime' | 'timeframe' | 'strategy_name' | 'score' | 'engine_version';
}

export interface GroupPerformanceItem {
  name: string;
  trades: number;
  wins: number;
  losses: number;
  winrate: number;
  profit_factor: number;
  avg_return: number;
}

export interface GroupPerformanceResponse {
  groups: GroupPerformanceItem[];
}

export interface HeatmapsRequest extends SignalsOverviewRequest {}

export interface HeatmapItem {
  x: string;
  y: string;
  value: number;
  count: number;
}

export interface HeatmapsResponse {
  pattern_timeframe: HeatmapItem[];
}

export interface IndicatorDistributionRequest extends SignalsOverviewRequest {
  indicator: 'rsi' | 'volume_ratio' | 'atr_percentile';
}

export interface IndicatorBucketItem {
  bucket: string;
  trades: number;
  win_rate: number;
  avg_return: number;
}

export interface IndicatorDistributionResponse {
  buckets: IndicatorBucketItem[];
}

export interface SignalsTradesRequest extends SignalsOverviewRequest {
  page: number;
  limit: number;
  search_symbols: string;
  sort_by: 'exit_time' | 'candle_time' | 'result_percent' | 'score';
  sort_order: 'desc' | 'asc';
}

export interface TradeItem {
  id: number;
  symbol: string;
  direction: string;
  timeframe: string;
  pattern: string;
  score: number;
  entry_price: number;
  result_percent: number;
  status: string;
  regime: string;
  strategy_name: string;
  candle_time: string;
  exit_time: string;
}

export interface SignalsTradesResponse {
  data: TradeItem[];
  total: number;
  page: number;
  limit: number;
  pages: number;
}

async function fetchSignalsOverview(filter: SignalsOverviewRequest): Promise<SignalsOverviewResponse> {
  const payload = buildAnalyticsFilter(filter);
  payload.initial_capital = filter.initial_capital || 10000;
  payload.position_size = filter.position_size || 1000;
  
  const res = await fetch(`${API}/signals/overview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch signals overview');
  return res.json();
}

async function fetchGroupPerformance(filter: GroupPerformanceRequest): Promise<GroupPerformanceResponse> {
  const payload = buildAnalyticsFilter(filter);
  payload.group_by = filter.group_by;
  
  const res = await fetch(`${API}/signals/group-performance`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch group performance');
  return res.json();
}

async function fetchHeatmaps(filter: HeatmapsRequest): Promise<HeatmapsResponse> {
  const payload = buildAnalyticsFilter(filter);
  
  const res = await fetch(`${API}/signals/heatmaps`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch heatmaps');
  return res.json();
}

async function fetchIndicatorDistribution(filter: IndicatorDistributionRequest): Promise<IndicatorDistributionResponse> {
  const payload = buildAnalyticsFilter(filter);
  payload.indicator = filter.indicator;
  
  const res = await fetch(`${API}/signals/indicator-distribution`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch indicator distribution');
  return res.json();
}

async function fetchSignalsTrades(filter: SignalsTradesRequest): Promise<SignalsTradesResponse> {
  const payload = buildAnalyticsFilter(filter);
  payload.page = filter.page;
  payload.limit = filter.limit;
  payload.search_symbols = filter.search_symbols;
  payload.sort_by = filter.sort_by;
  payload.sort_order = filter.sort_order;
  
  const res = await fetch(`${API}/signals/trades`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch signals trades');
  return res.json();
}

export const signalsApi = {
  fetchOverview: fetchSignalsOverview,
  fetchGroupPerformance: fetchGroupPerformance,
  fetchHeatmaps: fetchHeatmaps,
  fetchIndicatorDistribution: fetchIndicatorDistribution,
  fetchTrades: fetchSignalsTrades,
};
