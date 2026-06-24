import { buildAnalyticsFilter } from '../utils/analyticsFilters';

const API = '/api';

export interface IndicatorsOverviewRequest {
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

export interface IndicatorsOverviewResponse {
  total: number;
  win_rate: number;
  profit_factor: number;
  expectancy: number;
}

export interface ThresholdsRequest extends IndicatorsOverviewRequest {
  indicator: 'rsi' | 'volume_ratio' | 'atr_ratio' | 'score';
}

export interface ThresholdItem {
  threshold: number;
  trades: number;
  winrate: number;
}

export interface ThresholdsResponse {
  thresholds: ThresholdItem[];
}

export interface DistributionRequest extends IndicatorsOverviewRequest {
  indicator: 'rsi' | 'volume_ratio' | 'atr_ratio' | 'score';
}

export interface DistributionBucketItem {
  range: string;
  wins: number;
  losses: number;
  total: number;
  winrate: number;
}

export interface DistributionResponse {
  buckets: DistributionBucketItem[];
}

export interface OutcomeAveragesRequest extends IndicatorsOverviewRequest {}

export interface OutcomeAverageItem {
  indicator: string;
  win_avg: number;
  loss_avg: number;
}

export interface OutcomeAveragesResponse {
  averages: OutcomeAverageItem[];
}

export interface ScatterRequest extends IndicatorsOverviewRequest {
  x_indicator: 'rsi' | 'volume_ratio' | 'atr_ratio' | 'score';
  y_indicator: 'rsi' | 'volume_ratio' | 'atr_ratio' | 'score';
  limit?: number;
}

export interface ScatterItem {
  x: number;
  y: number;
  label: number;
  symbol: string;
}

export interface ScatterResponse {
  data: ScatterItem[];
}

export interface RegimeFingerprintRequest extends IndicatorsOverviewRequest {}

export interface RegimeFingerprintItem {
  regime: string;
  trades: number;
  winrate: number;
  rsi: number;
  volume_ratio: number;
  atr_ratio: number;
  score: number;
}

export interface RegimeFingerprintResponse {
  regimes: RegimeFingerprintItem[];
}

async function fetchIndicatorsOverview(filter: IndicatorsOverviewRequest): Promise<IndicatorsOverviewResponse> {
  const payload = buildAnalyticsFilter(filter);
  
  const res = await fetch(`${API}/indicators/overview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch indicators overview');
  return res.json();
}

async function fetchThresholds(filter: ThresholdsRequest): Promise<ThresholdsResponse> {
  const payload = buildAnalyticsFilter(filter);
  payload.indicator = filter.indicator;
  
  const res = await fetch(`${API}/indicators/thresholds`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch thresholds');
  return res.json();
}

async function fetchDistribution(filter: DistributionRequest): Promise<DistributionResponse> {
  const payload = buildAnalyticsFilter(filter);
  payload.indicator = filter.indicator;
  
  const res = await fetch(`${API}/indicators/distribution`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch distribution');
  return res.json();
}

async function fetchOutcomeAverages(filter: OutcomeAveragesRequest): Promise<OutcomeAveragesResponse> {
  const payload = buildAnalyticsFilter(filter);
  
  const res = await fetch(`${API}/indicators/outcome-averages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch outcome averages');
  return res.json();
}

async function fetchScatter(filter: ScatterRequest): Promise<ScatterResponse> {
  const payload = buildAnalyticsFilter(filter);
  payload.x_indicator = filter.x_indicator;
  payload.y_indicator = filter.y_indicator;
  payload.limit = filter.limit || 300;
  
  const res = await fetch(`${API}/indicators/scatter`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch scatter');
  return res.json();
}

async function fetchRegimeFingerprint(filter: RegimeFingerprintRequest): Promise<RegimeFingerprintResponse> {
  const payload = buildAnalyticsFilter(filter);
  
  const res = await fetch(`${API}/indicators/regime-fingerprint`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error('Failed to fetch regime fingerprint');
  return res.json();
}

export const indicatorsApi = {
  fetchOverview: fetchIndicatorsOverview,
  fetchThresholds: fetchThresholds,
  fetchDistribution: fetchDistribution,
  fetchOutcomeAverages: fetchOutcomeAverages,
  fetchScatter: fetchScatter,
  fetchRegimeFingerprint: fetchRegimeFingerprint,
};
