-- Bản patch chạy để chạy live future - v1
ALTER TABLE public.pending_signals
ADD COLUMN IF NOT EXISTS exchange_order_id character varying,
ADD COLUMN IF NOT EXISTS exchange_status character varying,
ADD COLUMN IF NOT EXISTS placed_at timestamptz,
ADD COLUMN IF NOT EXISTS order_quantity double precision,
ADD COLUMN IF NOT EXISTS executed_qty double precision DEFAULT 0,
ADD COLUMN IF NOT EXISTS accounted_qty double precision DEFAULT 0,
ADD COLUMN IF NOT EXISTS avg_fill_price double precision,
ADD COLUMN IF NOT EXISTS last_exchange_sync_at timestamptz,
ADD COLUMN IF NOT EXISTS signal_id bigint REFERENCES public.signals(id) ON DELETE SET NULL,
ADD COLUMN IF NOT EXISTS sl_order_id character varying,
ADD COLUMN IF NOT EXISTS tp_order_id character varying;

CREATE INDEX IF NOT EXISTS idx_pending_exchange_order_id
ON public.pending_signals(exchange_order_id);

CREATE INDEX IF NOT EXISTS idx_pending_signal_id
ON public.pending_signals(signal_id);

INSERT INTO public.app_config (key, value, updated_at)
VALUES (
  'LIMIT_ORDER_CONFIG',
  '{
    "enabled": true,
    "entry_reprice_pct": {
      "15m": 0.01,
      "1h": 0.008,
      "4h": 0.005
    }
  }',
  now()
)
ON CONFLICT (key) DO NOTHING;