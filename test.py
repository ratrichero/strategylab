#!/usr/bin/env python3
"""
Generate bootstrap_final.sql
Bản cuối cùng — schema + MV + indexes + config thực tế
"""
import os

OUT_DIR  = "sql"
OUT_FILE = os.path.join(OUT_DIR, "bootstrap_final.sql")


def build():
    return """-- ============================================================
--  QUANT RESEARCH LAB v6.0 — FULL BOOTSTRAP (FINAL)
--  Schema + MV + Indexes + UNIQUE constraints + Config thực tế
-- ============================================================

SET timezone = 'UTC';
SET search_path TO public;

-- ============================================================
-- CLEANUP
-- ============================================================
DROP MATERIALIZED VIEW IF EXISTS public.mv_signal_performance CASCADE;
DROP MATERIALIZED VIEW IF EXISTS public.mv_scan_flat CASCADE;
DROP TABLE IF EXISTS public.trade_outcome_analytics CASCADE;
DROP TABLE IF EXISTS public.signal_features CASCADE;
DROP TABLE IF EXISTS public.pending_signals CASCADE;
DROP TABLE IF EXISTS public.scan_debug CASCADE;
DROP TABLE IF EXISTS public.scan_run CASCADE;
DROP TABLE IF EXISTS public.scan_config CASCADE;
DROP TABLE IF EXISTS public.signals CASCADE;
DROP TABLE IF EXISTS public.market_data CASCADE;
DROP TABLE IF EXISTS public.strategy_stats CASCADE;
DROP TABLE IF EXISTS public.model_registry CASCADE;
DROP TABLE IF EXISTS public.audit_logs CASCADE;
DROP TABLE IF EXISTS public.reports CASCADE;
DROP TABLE IF EXISTS public.app_config CASCADE;

-- ============================================================
-- 1. APP_CONFIG
-- ============================================================
CREATE TABLE public.app_config (
    key        character varying PRIMARY KEY,
    value      text             NOT NULL,
    updated_at timestamptz      NOT NULL DEFAULT now()
);

-- ============================================================
-- 2. MARKET_DATA
-- ============================================================
CREATE TABLE public.market_data (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol     character varying NOT NULL,
    timeframe  character varying NOT NULL,
    time       timestamptz       NOT NULL,
    open       numeric,
    high       numeric,
    low        numeric,
    close      numeric,
    volume     numeric,
    created_at timestamptz       NOT NULL DEFAULT now(),
    CONSTRAINT uq_market_data_symbol_tf_time UNIQUE (symbol, timeframe, time)
);
CREATE INDEX idx_market_data_symbol_tf_time ON public.market_data (symbol, timeframe, time DESC);

-- ============================================================
-- 3. SCAN_CONFIG
-- ============================================================
CREATE TABLE public.scan_config (
    id                   integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    timeframe            character varying,
    score_threshold      double precision,
    body_ratio_threshold double precision,
    volume_multiplier    double precision,
    atr_ratio_min        double precision,
    cooldown_hours       double precision,
    ai_threshold         double precision,
    top_limit            integer,
    mtf_enabled          boolean,
    created_at           timestamptz NOT NULL DEFAULT now()
);

-- ============================================================
-- 4. SCAN_RUN
-- ============================================================
CREATE TABLE public.scan_run (
    id              integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    timeframe       character varying,
    scan_time       timestamptz NOT NULL,
    config_id       integer REFERENCES public.scan_config(id) ON DELETE SET NULL,
    engine_metadata jsonb,
    created_at      timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_scan_run_tf_time ON public.scan_run (timeframe, scan_time DESC);

-- ============================================================
-- 5. SIGNALS
-- ============================================================
CREATE TABLE public.signals (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol         character varying NOT NULL,
    timeframe      character varying NOT NULL,
    pattern        character varying,
    direction      character varying,
    score          numeric,
    entry_price    numeric,
    stop_loss      numeric,
    take_profit    numeric,
    rsi            numeric,
    volume_ratio   numeric,
    atr_ratio      numeric,
    regime         character varying,
    status         character varying NOT NULL DEFAULT 'OPEN',
    result_percent numeric,
    candle_time    timestamptz       NOT NULL,
    evaluated_at   timestamptz,
    created_at     timestamptz       NOT NULL DEFAULT now(),
    exit_price     numeric,
    exit_time      timestamptz,
    exit_reason    character varying,
    strategy_name  character varying,
    engine_version numeric,
    market_context jsonb,
    trading_mode   character varying NOT NULL DEFAULT 'PAPER'
);
CREATE INDEX idx_signals_status ON public.signals (status);
CREATE INDEX idx_signals_symbol_status ON public.signals (symbol, status);
CREATE INDEX idx_signals_symbol_tf_status ON public.signals (symbol, timeframe, status);
CREATE INDEX idx_signals_symbol_strategy_tf_status ON public.signals (symbol, strategy_name, timeframe, status);
CREATE INDEX idx_signals_status_exit_time ON public.signals (status, exit_time DESC);
CREATE INDEX idx_signals_exit_time ON public.signals (exit_time);
CREATE INDEX idx_signals_created_at ON public.signals (created_at DESC);
CREATE INDEX idx_signals_candle_time ON public.signals (candle_time DESC);
CREATE INDEX idx_signals_strategy ON public.signals (strategy_name);

-- ============================================================
-- 6. SCAN_DEBUG
-- ============================================================
CREATE TABLE public.scan_debug (
    id                  integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    scan_id             integer REFERENCES public.scan_run(id) ON DELETE CASCADE,
    signal_id           bigint  REFERENCES public.signals(id)  ON DELETE SET NULL,
    symbol              character varying,
    pattern             character varying,
    strategy_name       character varying,
    direction           character varying,
    trend_score         double precision,
    momentum_score      double precision,
    volume_score        double precision,
    pattern_score       double precision,
    mtf_score           double precision,
    penalty             double precision,
    rule_score_raw      double precision,
    derivative_bias     double precision,
    total_score         double precision,
    ml_prob             double precision,
    passed_score        boolean,
    block_reason        character varying,
    regime              character varying,
    indicators_snapshot jsonb,
    candle_time         timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_scan_debug_scan_id ON public.scan_debug (scan_id);
CREATE INDEX idx_scan_debug_symbol_created ON public.scan_debug (symbol, created_at DESC);

-- ============================================================
-- 7. PENDING_SIGNALS
-- ============================================================
CREATE TABLE public.pending_signals (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    symbol                character varying NOT NULL,
    timeframe             character varying NOT NULL,
    pattern               character varying,
    strategy_name         character varying,
    direction             character varying,
    signal_score          double precision,
    rule_score_raw        double precision,
    derivative_bias       double precision,
    trend_score           double precision,
    momentum_score        double precision,
    volume_score          double precision,
    pattern_score         double precision,
    mtf_score             double precision,
    penalty               double precision,
    ml_prob               double precision,
    indicators_snapshot   jsonb,
    candle_time           timestamptz,
    engine_version        numeric,
    trigger_price         double precision NOT NULL,
    stop_loss             double precision NOT NULL,
    take_profit           double precision NOT NULL,
    rr                    double precision,
    atr_value             double precision,
    atr_mult_entry        double precision,
    regime                character varying,
    scan_id               integer REFERENCES public.scan_run(id) ON DELETE SET NULL,
    scan_debug_id         integer REFERENCES public.scan_debug(id) ON DELETE SET NULL,
    status                character varying NOT NULL DEFAULT 'WAIT',
    expire_at             timestamptz       NOT NULL,
    filled_at             timestamptz,
    created_at            timestamptz       NOT NULL DEFAULT now(),
    rejection_reason      character varying,
    validation_details    jsonb,
    exchange_order_id     character varying,
    exchange_status       character varying,
    placed_at             timestamptz,
    order_quantity        double precision,
    executed_qty          double precision DEFAULT 0,
    accounted_qty         double precision DEFAULT 0,
    avg_fill_price        double precision,
    last_exchange_sync_at timestamptz,
    signal_id             bigint REFERENCES public.signals(id) ON DELETE SET NULL,
    sl_order_id           character varying,
    tp_order_id           character varying,
    CONSTRAINT chk_pending_status CHECK (status IN ('WAIT','FILLED','CANCELLED','REJECTED'))
);
CREATE INDEX idx_pending_status ON public.pending_signals (status);
CREATE INDEX idx_pending_symbol_status ON public.pending_signals (symbol, status);
CREATE INDEX idx_pending_expire ON public.pending_signals (expire_at);
CREATE INDEX idx_pending_symbol_strategy_tf_status ON public.pending_signals (symbol, strategy_name, timeframe, status);
CREATE INDEX idx_pending_wait_expire ON public.pending_signals (status, expire_at) WHERE status = 'WAIT';
CREATE INDEX idx_pending_created_at ON public.pending_signals (created_at DESC);
CREATE INDEX idx_pending_exchange_order_id ON public.pending_signals (exchange_order_id);
CREATE INDEX idx_pending_signal_id ON public.pending_signals (signal_id);

-- ============================================================
-- 8. SIGNAL_FEATURES
-- ============================================================
CREATE TABLE public.signal_features (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    signal_id      bigint NOT NULL REFERENCES public.signals(id) ON DELETE CASCADE,
    rsi            numeric,
    volume_ratio   numeric,
    atr_ratio      numeric,
    ema_distance   numeric,
    regime         character varying,
    trend_score    numeric,
    momentum_score numeric,
    volume_score   numeric,
    pattern_score  numeric,
    mtf_score      numeric,
    penalty_norm   numeric,
    total_score    numeric,
    rr             numeric,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_signal_features_signal_id UNIQUE (signal_id)
);
CREATE INDEX idx_sf_signal_id ON public.signal_features (signal_id);

-- ============================================================
-- 9. TRADE_OUTCOME_ANALYTICS
-- ============================================================
CREATE TABLE public.trade_outcome_analytics (
    id                      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    signal_id               bigint REFERENCES public.signals(id) ON DELETE SET NULL,
    symbol                  character varying,
    timeframe               character varying,
    direction               character varying,
    regime                  character varying,
    entry_price             numeric,
    exit_price              numeric,
    stop_loss               numeric,
    take_profit             numeric,
    rr_planned              numeric,
    rr_realized             numeric,
    trade_return            numeric,
    label                   integer,
    max_drawdown            numeric,
    max_favorable           numeric,
    time_to_exit            integer,
    time_to_mae             integer,
    time_to_mfe             integer,
    volatility_at_entry     numeric,
    volume_ratio_at_entry   numeric,
    total_score             numeric,
    trend_score             numeric,
    mtf_score               numeric,
    penalty_norm            numeric,
    exit_reason             character varying,
    created_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_toa_signal_id UNIQUE (signal_id)
);
CREATE INDEX idx_outcome_signal_id ON public.trade_outcome_analytics (signal_id);
CREATE INDEX idx_toa_created_at ON public.trade_outcome_analytics (created_at DESC);
CREATE INDEX idx_toa_symbol_tf ON public.trade_outcome_analytics (symbol, timeframe);

-- ============================================================
-- 10. STRATEGY_STATS
-- ============================================================
CREATE TABLE public.strategy_stats (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    strategy_name  character varying,
    timeframe      character varying,
    engine_version integer,
    total_trades   integer NOT NULL DEFAULT 0,
    wins           integer NOT NULL DEFAULT 0,
    losses         integer NOT NULL DEFAULT 0,
    winrate        numeric,
    avg_profit     numeric,
    avg_loss       numeric,
    sharpe         numeric,
    max_drawdown   numeric,
    last_updated   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_strategy_stats UNIQUE (strategy_name, timeframe, engine_version)
);

-- ============================================================
-- 11. MODEL_REGISTRY
-- ============================================================
CREATE TABLE public.model_registry (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    model_version character varying,
    scan_version  character varying,
    timeframe     character varying,
    features      text,
    target        character varying,
    train_size    integer,
    auc           numeric,
    sharpe        numeric,
    max_drawdown  numeric,
    train_start   timestamptz,
    train_end     timestamptz,
    model_path    text,
    is_active     boolean NOT NULL DEFAULT false,
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_model_registry_active ON public.model_registry (is_active, timeframe) WHERE is_active = true;

-- ============================================================
-- 12. AUDIT_LOGS
-- ============================================================
CREATE TABLE public.audit_logs (
    id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type character varying,
    message    text,
    metadata   jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_logs_event_type ON public.audit_logs (event_type);
CREATE INDEX idx_audit_logs_created_at ON public.audit_logs (created_at DESC);

-- ============================================================
-- 13. REPORTS
-- ============================================================
CREATE TABLE public.reports (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    report_type  character varying,
    period_start timestamptz,
    period_end   timestamptz,
    content      text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_reports_type_created ON public.reports (report_type, created_at DESC);

-- ============================================================
-- MV 1: Signal Performance
-- ============================================================
CREATE MATERIALIZED VIEW public.mv_signal_performance AS
SELECT DISTINCT ON (s.id)
    s.id, s.symbol, s.timeframe, s.pattern, s.direction,
    s.regime, s.score, s.status, s.result_percent,
    s.engine_version, s.strategy_name,
    s.candle_time, s.exit_time, s.created_at,
    s.exit_reason, s.trading_mode,
    sf.trend_score, sf.momentum_score, sf.volume_score,
    sf.pattern_score, sf.mtf_score, sf.penalty_norm,
    sf.total_score, sf.rr,
    toa.rr_planned, toa.rr_realized, toa.trade_return,
    toa.max_drawdown AS mae, toa.max_favorable AS mfe,
    toa.label, toa.exit_reason AS toa_exit_reason,
    toa.time_to_exit, toa.time_to_mae, toa.time_to_mfe
FROM public.signals s
LEFT JOIN public.signal_features sf ON sf.signal_id = s.id
LEFT JOIN public.trade_outcome_analytics toa ON toa.signal_id = s.id
WHERE s.status IN ('WIN', 'LOSS')
ORDER BY s.id, sf.id, toa.id;

CREATE UNIQUE INDEX idx_mv_sp_id ON public.mv_signal_performance (id);
CREATE INDEX idx_mv_sp_exit ON public.mv_signal_performance (exit_time);
CREATE INDEX idx_mv_sp_strategy ON public.mv_signal_performance (strategy_name);
CREATE INDEX idx_mv_sp_created ON public.mv_signal_performance (created_at);
CREATE INDEX idx_mv_sp_engine ON public.mv_signal_performance (engine_version);

-- ============================================================
-- MV 2: Scan Flat
-- ============================================================
CREATE MATERIALIZED VIEW public.mv_scan_flat AS
SELECT
    sd.id, sd.scan_id, sr.timeframe, sd.symbol, sd.pattern,
    sd.direction, sd.strategy_name, sd.total_score, sd.passed_score,
    sd.block_reason, sd.regime, sd.signal_id, sd.ml_prob,
    sd.derivative_bias, sd.created_at,
    (sr.engine_metadata->>'engine_version')::numeric AS engine_version,
    (sd.indicators_snapshot->>'rsi')::numeric AS rsi,
    (sd.indicators_snapshot->>'volume_ratio')::numeric AS vol_ratio,
    (sd.indicators_snapshot->>'atr_percentile')::numeric AS atr_pct,
    (sd.indicators_snapshot->>'ema_distance')::numeric AS ema_dist,
    (sd.indicators_snapshot->>'ema50')::numeric AS ema50,
    (sd.indicators_snapshot->>'ema200')::numeric AS ema200,
    (sd.indicators_snapshot->>'ema200_slope')::numeric AS ema200_slope,
    (sd.indicators_snapshot->>'rsi_slope')::numeric AS rsi_slope,
    (sd.indicators_snapshot->>'bb_width')::numeric AS bb_width,
    (sd.indicators_snapshot->>'atr_ratio')::numeric AS atr_ratio
FROM public.scan_debug sd
LEFT JOIN public.scan_run sr ON sr.id = sd.scan_id
WHERE sd.indicators_snapshot IS NOT NULL;

CREATE UNIQUE INDEX idx_mv_sf_id ON public.mv_scan_flat (id);
CREATE INDEX idx_mv_sf_created ON public.mv_scan_flat (created_at);
CREATE INDEX idx_mv_sf_signal ON public.mv_scan_flat (signal_id);
CREATE INDEX idx_mv_sf_timeframe ON public.mv_scan_flat (timeframe);
CREATE INDEX idx_mv_sf_engine ON public.mv_scan_flat (engine_version);

-- ============================================================
-- DEFAULT APP_CONFIG — config thực tế production
-- ============================================================
INSERT INTO public.app_config (key, value, updated_at) VALUES
    ('ACTIVE_STRATEGIES',         'candlestick',   now()),
    ('AI_THRESHOLD',              '0.0',           now()),
    ('ATR_RATIO_MIN',             '0.0015',        now()),
    ('BINANCE_API_KEY',           '',               now()),
    ('BINANCE_API_SECRET',        '',               now()),
    ('BINANCE_TESTNET_API_KEY',   '',               now()),
    ('BINANCE_TESTNET_API_SECRET','',               now()),
    ('BODY_RATIO_THRESHOLD',      '0.5',           now()),
    ('CONNECTION_OVERRIDE',       'false',          now()),
    ('COOLDOWN_HOURS',            '4',             now()),
    ('DERIVATIVE_CONFIG',         '{"bias_scale":{"15m":0.6,"1h":0.8,"4h":1},"pre_buffer":1}', now()),
    ('ENABLE_MONITOR',            'true',          now()),
    ('ENABLE_SCHEDULER',          'true',          now()),
    ('ENGINE_VERSION',            '6',             now()),
    ('GEMINI_API_KEY',            '',               now()),
    ('GROQ_API_KEY',              '',               now()),
    ('LIMIT_ORDER_CONFIG',        '{"enabled":true,"entry_reprice_pct":{"15m":0.005,"1h":0.005,"4h":0.005}}', now()),
    ('MAX_OPEN_TRADES',           '10',            now()),
    ('MTF_ENABLED',               'true',          now()),
    ('OPEN_TRADE_FILTER',         '{"enabled":true,"identity":{"strategies":["candlestick"],"timeframes":["15m"]},"score":{"min_overall":6,"min_mtf_score":0.3},"position":{"max_concurrent_trades":10,"max_per_symbol":1,"max_daily_trades":50,"max_daily_loss_pct":30,"pause_after_loss_streak":10}}', now()),
    ('PENDING_CONFIG',            '{"enabled":true,"atr_entry_multiplier":{"15m":0.4,"1h":0.5,"4h":0.6},"expire_hours":{"15m":1,"1h":4,"4h":8}}', now()),
    ('POSITION_SIZE_CONFIG',      '{"mode":"fixed_usdt","fixed_usdt_per_trade":1,"risk_per_trade_pct":0.01,"default_leverage":10,"max_position_usdt":10}', now()),
    ('PREFILL_CONFIG',            '{"enabled":true,"price_context":{"enabled":true,"max_adverse_move_pct":{"15m":1.0,"1h":1.8,"4h":3.0}},"candle_invalidation":{"enabled":true,"adverse_body_atr_mult":1.5},"momentum_check":{"enabled":true,"rsi_reject_long_above":75,"rsi_reject_short_below":25},"volatility_guard":{"enabled":true,"atr_spike_multiplier":2.5},"regime_check":{"enabled":true}}', now()),
    ('RISK_CONFIG',               '{"15m":{"sl_mult":0.02,"tp_mult":0.04},"1h":{"sl_mult":0.025,"tp_mult":0.05},"4h":{"sl_mult":0.03,"tp_mult":0.06}}', now()),
    ('SCORE_THRESHOLD',           '6',             now()),
    ('STRATEGY_THRESHOLDS',       '{"candlestick":5.0,"breakout":6.0,"mean_reversion":5.5,"pullback":5.5,"trend_following":5.5}', now()),
    ('TELEGRAM_BOT_TOKEN',       '',               now()),
    ('TIMEFRAME',                '15m',            now()),
    ('TOP_LIMIT',                '50',             now()),
    ('TRADING_MODE',             'PAPER',          now()),
    ('VOLUME_MULTIPLIER',        '1.15',           now())
ON CONFLICT (key) DO NOTHING;

-- ============================================================
-- POST-FLIGHT VERIFY
-- ============================================================
DO $$
DECLARE cnt integer;
BEGIN
    SELECT count(*) INTO cnt FROM information_schema.columns
    WHERE table_schema='public' AND data_type='timestamp without time zone';
    IF cnt > 0 THEN RAISE WARNING '% columns still naive timestamp!', cnt;
    ELSE RAISE NOTICE 'All timestamps are timestamptz. OK.';
    END IF;
END $$;

DO $$
DECLARE cnt integer;
BEGIN
    SELECT count(*) INTO cnt FROM information_schema.columns
    WHERE table_schema='public' AND table_name='pending_signals'
      AND column_name IN ('exchange_order_id','exchange_status','executed_qty',
                          'accounted_qty','avg_fill_price','signal_id','sl_order_id','tp_order_id');
    IF cnt < 8 THEN RAISE WARNING 'pending_signals missing % exchange columns!', 8-cnt;
    ELSE RAISE NOTICE 'pending_signals exchange columns OK.';
    END IF;
END $$;

DO $$
DECLARE tbl int; mv int; idx int;
BEGIN
    SELECT count(*) INTO tbl FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';
    SELECT count(*) INTO mv FROM pg_matviews WHERE schemaname='public';
    SELECT count(*) INTO idx FROM pg_indexes WHERE schemaname='public';
    RAISE NOTICE 'Bootstrap complete: % tables, % MVs, % indexes.', tbl, mv, idx;
END $$;
"""


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    content = build()
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    lines = content.count("\n")
    print(f"✅ Generated: {OUT_FILE}")
    print(f"   Lines: {lines:,}")


if __name__ == "__main__":
    main()