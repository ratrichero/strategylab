from sqlalchemy import (
    Column, BigInteger, Integer, String, Numeric,
    Float, Boolean, DateTime, JSON, ForeignKey,
    Text, UniqueConstraint, Index
)
from sqlalchemy.orm import relationship
from app.db.session import Base
from app.core.time_utils import utc_now


# ── Shorthand helpers ────────────────────────────────────────

def _dt(**kw):
    """Cột DateTime UTC aware — không có default."""
    return Column(DateTime(timezone=True), **kw)


def _dt_now(**kw):
    """Cột DateTime UTC aware — default = utc_now() lúc INSERT."""
    return Column(DateTime(timezone=True), default=utc_now, **kw)


def _dt_now_update(**kw):
    """
    Cột DateTime UTC aware.
    default = utc_now() lúc INSERT.
    onupdate = utc_now() lúc UPDATE.
    Dùng cho updated_at / last_updated.
    """
    return Column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        **kw
    )


def _dt_server(**kw):
    """Cột DateTime UTC aware — server_default = DB now()."""
    from sqlalchemy.sql import func
    return Column(DateTime(timezone=True), server_default=func.now(), **kw)


# ============================================================
# Signal
# ============================================================
class Signal(Base):
    __tablename__ = "signals"

    id             = Column(BigInteger, primary_key=True)   # ← fix: Integer → BigInteger
    symbol         = Column(String(20),  nullable=False)
    timeframe      = Column(String(10),  nullable=False)
    pattern        = Column(String(50))
    direction      = Column(String(10))
    score          = Column(Numeric)
    entry_price    = Column(Numeric)
    stop_loss      = Column(Numeric)
    take_profit    = Column(Numeric)
    rsi            = Column(Numeric)
    volume_ratio   = Column(Numeric)
    atr_ratio      = Column(Numeric)
    regime         = Column(String(20))
    status         = Column(String(20),  nullable=False, default="OPEN")
    result_percent = Column(Numeric)
    candle_time    = _dt(nullable=False)
    evaluated_at   = _dt(nullable=True)
    created_at     = _dt_now(nullable=False)
    exit_price     = Column(Numeric)
    exit_time      = _dt(nullable=True)
    exit_reason    = Column(String)
    strategy_name  = Column(String,      nullable=True)
    engine_version = Column(Numeric)
    market_context = Column(JSON,        nullable=True)
    trading_mode   = Column(String(20),  nullable=False, default="PAPER")

    features = relationship(
        "SignalFeature",
        back_populates="signal",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        Index("idx_signals_symbol_tf_status", "symbol", "timeframe", "status"),
        Index("idx_signals_status_exit_time", "status", "exit_time"),
        Index("idx_signals_created_at",       "created_at"),
        Index("idx_signals_candle_time",      "candle_time"),
    )


# ============================================================
# SignalFeature
# ============================================================
class SignalFeature(Base):
    __tablename__ = "signal_features"

    id             = Column(BigInteger, primary_key=True)
    signal_id      = Column(
        BigInteger,
        ForeignKey("signals.id", ondelete="CASCADE"),
        nullable=False,
    )
    rsi            = Column(Numeric)
    volume_ratio   = Column(Numeric)
    atr_ratio      = Column(Numeric)
    ema_distance   = Column(Numeric)
    regime         = Column(String)
    trend_score    = Column(Numeric)
    momentum_score = Column(Numeric)
    volume_score   = Column(Numeric)
    pattern_score  = Column(Numeric)
    mtf_score      = Column(Numeric)
    penalty_norm   = Column(Numeric)
    total_score    = Column(Numeric)
    rr             = Column(Numeric)
    created_at     = _dt_now(nullable=False)

    signal = relationship("Signal", back_populates="features")

    __table_args__ = (
        Index("idx_signal_features_signal_id", "signal_id"),
    )


# ============================================================
# TradeOutcomeAnalytics
# ============================================================
class TradeOutcomeAnalytics(Base):
    __tablename__ = "trade_outcome_analytics"

    id                    = Column(BigInteger, primary_key=True)
    signal_id             = Column(
        BigInteger,
        ForeignKey("signals.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol                = Column(String)
    timeframe             = Column(String)
    direction             = Column(String)
    regime                = Column(String)
    entry_price           = Column(Numeric)
    exit_price            = Column(Numeric)
    stop_loss             = Column(Numeric)
    take_profit           = Column(Numeric)
    rr_planned            = Column(Numeric)
    rr_realized           = Column(Numeric)
    trade_return          = Column(Numeric)
    label                 = Column(Integer)       # 1=WIN, 0=LOSS
    max_drawdown          = Column(Numeric)
    max_favorable         = Column(Numeric)
    time_to_exit          = Column(Integer)       # seconds
    time_to_mae           = Column(Integer,  nullable=True)
    time_to_mfe           = Column(Integer,  nullable=True)
    volatility_at_entry   = Column(Numeric)
    volume_ratio_at_entry = Column(Numeric)
    total_score           = Column(Numeric)
    trend_score           = Column(Numeric)
    mtf_score             = Column(Numeric)
    penalty_norm          = Column(Numeric)
    exit_reason           = Column(String)
    created_at            = _dt_now(nullable=False)

    __table_args__ = (
        Index("idx_toa_signal_id",  "signal_id"),
        Index("idx_toa_created_at", "created_at"),
        Index("idx_toa_symbol_tf",  "symbol", "timeframe"),
    )


# ============================================================
# ScanConfig
# ============================================================
class ScanConfig(Base):
    __tablename__ = "scan_config"

    id                   = Column(Integer, primary_key=True)
    timeframe            = Column(String)
    score_threshold      = Column(Float)
    body_ratio_threshold = Column(Float)
    volume_multiplier    = Column(Float)
    atr_ratio_min        = Column(Float)
    cooldown_hours       = Column(Float)
    ai_threshold         = Column(Float)
    top_limit            = Column(Integer)
    mtf_enabled          = Column(Boolean)
    created_at           = _dt_now(nullable=False)


# ============================================================
# ScanRun
# ============================================================
class ScanRun(Base):
    __tablename__ = "scan_run"

    id              = Column(Integer, primary_key=True)
    timeframe       = Column(String)
    scan_time       = _dt(nullable=False)        # ← fix: app tự set explicit, không dùng default
    config_id       = Column(Integer, ForeignKey("scan_config.id", ondelete="SET NULL"), nullable=True)
    created_at      = _dt_now(nullable=False)
    engine_metadata = Column(JSON, nullable=True)

    __table_args__ = (
        Index("idx_scan_run_tf_time", "timeframe", "scan_time"),
    )


# ============================================================
# ScanDebug
# ============================================================
class ScanDebug(Base):
    __tablename__ = "scan_debug"

    id                  = Column(Integer, primary_key=True)
    scan_id             = Column(
        Integer,
        ForeignKey("scan_run.id", ondelete="CASCADE"),   # ← fix: thêm ondelete
        nullable=True,
    )
    signal_id           = Column(
        BigInteger,
        ForeignKey("signals.id", ondelete="SET NULL"),   # ← fix: thêm ondelete
        nullable=True,
    )
    symbol              = Column(String)
    pattern             = Column(String)
    strategy_name       = Column(String,  nullable=True)
    direction           = Column(String)
    trend_score         = Column(Float)
    momentum_score      = Column(Float)
    volume_score        = Column(Float)
    pattern_score       = Column(Float)
    mtf_score           = Column(Float)
    penalty             = Column(Float)
    rule_score_raw      = Column(Float,   nullable=True)
    derivative_bias     = Column(Float,   nullable=True)
    total_score         = Column(Float)
    ml_prob             = Column(Float)
    passed_score        = Column(Boolean)
    block_reason        = Column(String)
    regime              = Column(String)
    indicators_snapshot = Column(JSON)
    candle_time         = _dt(nullable=True)
    created_at          = _dt_now(nullable=False)

    __table_args__ = (
        Index("idx_scan_debug_scan_id",       "scan_id"),
        Index("idx_scan_debug_symbol_created", "symbol", "created_at"),
    )


# ============================================================
# PendingSignal
# ============================================================
class PendingSignal(Base):
    __tablename__ = "pending_signals"

    id               = Column(BigInteger, primary_key=True)
    symbol           = Column(String,  nullable=False)
    timeframe        = Column(String,  nullable=False)
    pattern          = Column(String)
    strategy_name    = Column(String)
    direction        = Column(String)

    # ── Scores ───────────────────────────────────────────
    signal_score     = Column(Float)
    rule_score_raw   = Column(Float)
    derivative_bias  = Column(Float)
    trend_score      = Column(Float)
    momentum_score   = Column(Float)
    volume_score     = Column(Float)
    pattern_score    = Column(Float)
    mtf_score        = Column(Float)
    penalty          = Column(Float)
    ml_prob          = Column(Float)

    # ── Snapshot at scan time ─────────────────────────────
    indicators_snapshot = Column(JSON)
    candle_time         = _dt(nullable=True)
    engine_version      = Column(Numeric, nullable=True)  # ← version lúc scan, không đổi khi fill

    # ── Entry params ─────────────────────────────────────
    trigger_price    = Column(Float,  nullable=False)
    stop_loss        = Column(Float,  nullable=False)
    take_profit      = Column(Float,  nullable=False)
    rr               = Column(Float)
    atr_value        = Column(Float)
    atr_mult_entry   = Column(Float)
    regime           = Column(String)

    # ── live/testnet execution tracking params ─────────────────────────────────────
    exchange_order_id   = Column(String, nullable=True)
    exchange_status     = Column(String, nullable=True)
    placed_at           = _dt(nullable=True)
    order_quantity      = Column(Float, nullable=True)
    executed_qty        = Column(Float, nullable=True, default=0)
    accounted_qty       = Column(Float, nullable=True, default=0)
    avg_fill_price      = Column(Float, nullable=True)
    last_exchange_sync_at = _dt(nullable=True)

    signal_id           = Column(BigInteger, ForeignKey("signals.id", ondelete="SET NULL"), nullable=True)

    sl_order_id         = Column(String, nullable=True)
    tp_order_id         = Column(String, nullable=True)
    reprice_applied     = Column(Boolean, nullable=False, default=False)

    
    # ── Refs ─────────────────────────────────────────────
    scan_id       = Column(
        Integer,
        ForeignKey("scan_run.id", ondelete="SET NULL"),   # ← fix: thêm ondelete
        nullable=True,
    )
    scan_debug_id = Column(
        Integer,
        ForeignKey("scan_debug.id", ondelete="SET NULL"), # ← fix: thêm ondelete
        nullable=True,
    )

    # ── Lifecycle ─────────────────────────────────────────
    status           = Column(String, nullable=False, default="WAIT")
    expire_at        = _dt(nullable=False)
    filled_at        = _dt(nullable=True)
    created_at       = _dt_now(nullable=False)

    # ── Rejection ─────────────────────────────────────────
    rejection_reason   = Column(String, nullable=True)
    validation_details = Column(JSON,   nullable=True)

    __table_args__ = (
        Index(
            "idx_pending_status_expire",
            "status", "expire_at",
            postgresql_where=("status = 'WAIT'"),   # partial index
        ),
        Index("idx_pending_symbol_tf_status", "symbol", "timeframe", "status"),
        Index("idx_pending_created_at",       "created_at"),
    )


# ============================================================
# MarketData
# ============================================================
class MarketData(Base):
    __tablename__ = "market_data"

    id         = Column(BigInteger, primary_key=True)
    symbol     = Column(String,  nullable=False)
    timeframe  = Column(String,  nullable=False)
    time       = _dt(nullable=False)
    open       = Column(Numeric)
    high       = Column(Numeric)
    low        = Column(Numeric)
    close      = Column(Numeric)
    volume     = Column(Numeric)
    created_at = _dt_server(nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "symbol", "timeframe", "time",
            name="uq_market_data_symbol_tf_time",
        ),
        Index(
            "idx_market_data_symbol_tf_time",
            "symbol", "timeframe", "time",
        ),
    )


# ============================================================
# AppConfig
# ============================================================
class AppConfig(Base):
    __tablename__ = "app_config"

    key        = Column(String, primary_key=True)
    value      = Column(Text,   nullable=False)
    updated_at = _dt_now_update(nullable=False)   # ← fix: tự update khi UPDATE row


# ============================================================
# StrategyStats
# ============================================================
class StrategyStats(Base):
    __tablename__ = "strategy_stats"

    id             = Column(BigInteger, primary_key=True)
    strategy_name  = Column(String)
    timeframe      = Column(String)
    engine_version = Column(Integer)
    total_trades   = Column(Integer, nullable=False, default=0)
    wins           = Column(Integer, nullable=False, default=0)
    losses         = Column(Integer, nullable=False, default=0)
    winrate        = Column(Numeric)
    avg_profit     = Column(Numeric)
    avg_loss       = Column(Numeric)
    sharpe         = Column(Numeric)
    max_drawdown   = Column(Numeric)
    last_updated   = _dt_now_update(nullable=False)   # ← fix: tự update

    __table_args__ = (
        UniqueConstraint(
            "strategy_name", "timeframe", "engine_version",
            name="uq_strategy_stats",
        ),
    )


# ============================================================
# ModelRegistry
# ============================================================
class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id            = Column(BigInteger, primary_key=True)
    model_version = Column(String)
    scan_version  = Column(String)
    timeframe     = Column(String)
    features      = Column(Text)
    target        = Column(String)
    train_size    = Column(Integer)
    auc           = Column(Numeric)
    sharpe        = Column(Numeric)
    max_drawdown  = Column(Numeric)
    train_start   = _dt(nullable=True)
    train_end     = _dt(nullable=True)
    model_path    = Column(Text)
    is_active     = Column(Boolean, nullable=False, default=False)
    created_at    = _dt_now(nullable=False)

    __table_args__ = (
        Index(
            "idx_model_registry_active",
            "is_active", "timeframe",
            postgresql_where=("is_active = true"),
        ),
    )


# ============================================================
# AuditLog
# ============================================================
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id         = Column(BigInteger, primary_key=True)
    event_type = Column(String)
    message    = Column(Text)
    meta_json  = Column("metadata", JSON)   # ← "metadata" = tên cột DB, meta_json = tên Python
    created_at = _dt_now(nullable=False)

    __table_args__ = (
        Index("idx_audit_logs_event_type", "event_type"),
        Index("idx_audit_logs_created_at", "created_at"),
    )


# ============================================================
# Report
# ============================================================
class Report(Base):
    __tablename__ = "reports"

    id           = Column(BigInteger, primary_key=True)
    report_type  = Column(String)
    period_start = _dt(nullable=True)
    period_end   = _dt(nullable=True)
    content      = Column(Text)
    created_at   = _dt_now(nullable=False)

    __table_args__ = (
        Index("idx_reports_type_created", "report_type", "created_at"),
    )