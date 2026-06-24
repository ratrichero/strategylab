export type SymbolMode = 'include' | 'exclude';
export type EngineMode = 'only' | 'newest' | 'older';

export type AnalyticsFilterPayload = {
  start_date?: string;
  end_date?: string;
  date_field?: 'exit_time' | 'created_at' | 'candle_time';
  symbols?: string;
  symbol_mode?: SymbolMode;
  timeframes?: string[];
  strategies?: string[];
  patterns?: string[];
  regimes?: string[];
  directions?: string[];
  engine_version?: string;
  engine_mode?: EngineMode;
  score_min?: number;
  score_max?: number;
  include_manual?: boolean;
};

function cleanArray(value: any): string[] {
  return Array.isArray(value)
    ? value.map(v => String(v).trim()).filter(Boolean)
    : [];
}

function cleanNumber(value: any): number | undefined {
  if (value === undefined || value === null || value === '') return undefined;
  const n = Number(value);
  return Number.isFinite(n) ? n : undefined;
}

export function buildAnalyticsFilter(input: Record<string, any> = {}): AnalyticsFilterPayload {
  const payload: AnalyticsFilterPayload = {
    date_field: input.date_field || input.dateField || 'exit_time',
    symbol_mode: input.symbol_mode || input.symbolMode || 'include',
    engine_version: String(input.engine_version ?? input.engineVersion ?? 'all'),
    engine_mode: input.engine_mode || input.engineMode || 'only',
  };

  const startDate = input.start_date ?? input.startDate;
  const endDate = input.end_date ?? input.endDate;
  if (startDate) payload.start_date = String(startDate);
  if (endDate) payload.end_date = String(endDate);

  const symbols = input.symbols;
  if (symbols && String(symbols).trim()) payload.symbols = String(symbols).trim();

  const arrayFields = [
    ['timeframes', 'timeframes'],
    ['strategies', 'strategies'],
    ['patterns', 'patterns'],
    ['regimes', 'regimes'],
    ['directions', 'directions'],
  ] as const;
  arrayFields.forEach(([outKey, inKey]) => {
    const arr = cleanArray(input[inKey]);
    if (arr.length) payload[outKey] = arr;
  });

  const scoreMin = cleanNumber(input.score_min ?? input.scoreMin);
  const scoreMax = cleanNumber(input.score_max ?? input.scoreMax);
  if (scoreMin !== undefined) payload.score_min = scoreMin;
  if (scoreMax !== undefined) payload.score_max = scoreMax;

  if (input.include_manual !== undefined || input.includeManual !== undefined) {
    payload.include_manual = Boolean(input.include_manual ?? input.includeManual);
  }

  return payload;
}

export function analyticsFilterQuery(input: Record<string, any> = {}): string {
  const payload = buildAnalyticsFilter(input);
  const params = new URLSearchParams();
  Object.entries(payload).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) {
      if (value.length) params.set(key, value.join(','));
    } else {
      params.set(key, String(value));
    }
  });
  const text = params.toString();
  return text ? `?${text}` : '';
}
