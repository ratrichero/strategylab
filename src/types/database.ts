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

export interface EquityPoint {
  timestamp: string;
  equity: number;
  drawdown: number;
  trade_count: number;
}

export interface Signal {
  id: number;
  symbol: string;
  pattern: string;
  direction: string;
  timeframe: string;
  entry_price: number;
  stop_loss: number;
  take_profit: number;
  score: number;
  regime: string;
  status: string;
  result_percent: number;
  candle_time: string;
  exit_time: string;
  exit_price: number;
  strategy_name: string;
  engine_version: number;
  created_at: string;
}
