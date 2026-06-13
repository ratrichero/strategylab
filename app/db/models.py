from sqlalchemy import (Column, BigInteger, Integer, String, Numeric,
    Float, Boolean, DateTime, JSON, ForeignKey)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.session import Base


class Signal(Base):
    __tablename__ = "signals"
    id             = Column(Integer, primary_key=True)
    symbol         = Column(String(20))
    timeframe      = Column(String(10))
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
    status         = Column(String(20), default="OPEN")
    result_percent = Column(Numeric)
    candle_time    = Column(DateTime)
    evaluated_at   = Column(DateTime, nullable=True)
    created_at     = Column(DateTime, server_default=func.now())
    exit_time      = Column(DateTime)
    exit_price     = Column(Numeric)
    exit_reason    = Column(String)
    strategy_name  = Column(String, nullable=True)
    engine_version = Column(Numeric)
    market_context = Column(JSON, nullable=True)
    trading_mode   = Column(String(20), default="PAPER")


class SignalFeature(Base):
    __tablename__   = "signal_features"
    id              = Column(BigInteger, primary_key=True)
    signal_id       = Column(BigInteger, ForeignKey("signals.id"))
    rsi             = Column(Numeric)
    volume_ratio    = Column(Numeric)
    atr_ratio       = Column(Numeric)
    ema_distance    = Column(Numeric)
    regime          = Column(String)
    trend_score     = Column(Numeric)
    momentum_score  = Column(Numeric)
    volume_score    = Column(Numeric)
    pattern_score   = Column(Numeric)
    mtf_score       = Column(Numeric)
    penalty_norm    = Column(Numeric)
    total_score     = Column(Numeric)
    rr              = Column(Numeric)
    created_at      = Column(DateTime, default=datetime.utcnow)


class TradeOutcomeAnalytics(Base):
    __tablename__         = "trade_outcome_analytics"
    id                    = Column(BigInteger, primary_key=True)
    signal_id             = Column(BigInteger, ForeignKey("signals.id"))
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
    label                 = Column(Integer)
    max_drawdown          = Column(Numeric)
    max_favorable         = Column(Numeric)
    time_to_exit          = Column(Integer)
    time_to_mae           = Column(Integer, nullable=True)
    time_to_mfe           = Column(Integer, nullable=True)
    volatility_at_entry   = Column(Numeric)
    volume_ratio_at_entry = Column(Numeric)
    total_score           = Column(Numeric)
    trend_score           = Column(Numeric)
    mtf_score             = Column(Numeric)
    penalty_norm          = Column(Numeric)
    exit_reason           = Column(String)
    created_at            = Column(DateTime, default=datetime.utcnow)


class ScanConfig(Base):
    __tablename__        = "scan_config"
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
    created_at           = Column(DateTime, default=datetime.utcnow)


class ScanRun(Base):
    __tablename__   = "scan_run"
    id              = Column(Integer, primary_key=True)
    timeframe       = Column(String)
    scan_time       = Column(DateTime, default=datetime.utcnow)
    config_id       = Column(Integer, ForeignKey("scan_config.id"))
    created_at      = Column(DateTime, default=datetime.utcnow)
    engine_metadata = Column(JSON, nullable=True)


class ScanDebug(Base):
    __tablename__       = "scan_debug"
    id                  = Column(Integer, primary_key=True)
    scan_id             = Column(Integer, ForeignKey("scan_run.id"))
    symbol              = Column(String)
    pattern             = Column(String)
    direction           = Column(String)
    trend_score         = Column(Float)
    momentum_score      = Column(Float)
    volume_score        = Column(Float)
    pattern_score       = Column(Float)
    mtf_score           = Column(Float)
    penalty             = Column(Float)
    total_score         = Column(Float)
    passed_score        = Column(Boolean)
    block_reason        = Column(String)
    regime              = Column(String)
    ml_prob             = Column(Float)
    signal_id           = Column(BigInteger, ForeignKey("signals.id"), nullable=True)
    candle_time         = Column(DateTime)
    created_at          = Column(DateTime, default=datetime.utcnow)
    rule_score_raw      = Column(Float, nullable=True)
    indicators_snapshot = Column(JSON)
    derivative_bias     = Column(Float, nullable=True)
    strategy_name       = Column(String, nullable=True)


class PendingSignal(Base):
    __tablename__       = "pending_signals"
    id                  = Column(BigInteger, primary_key=True)
    symbol              = Column(String, nullable=False)
    timeframe           = Column(String, nullable=False)
    pattern             = Column(String)
    strategy_name       = Column(String)
    direction           = Column(String)
    signal_score        = Column(Float)
    rule_score_raw      = Column(Float)
    derivative_bias     = Column(Float)
    trend_score         = Column(Float)
    momentum_score      = Column(Float)
    volume_score        = Column(Float)
    pattern_score       = Column(Float)
    mtf_score           = Column(Float)
    penalty             = Column(Float)
    ml_prob             = Column(Float)
    indicators_snapshot = Column(JSON)
    candle_time         = Column(DateTime)
    trigger_price       = Column(Float, nullable=False)
    stop_loss           = Column(Float, nullable=False)
    take_profit         = Column(Float, nullable=False)
    rr                  = Column(Float)
    atr_value           = Column(Float)
    atr_mult_entry      = Column(Float)
    regime              = Column(String)
    scan_id             = Column(Integer, ForeignKey("scan_run.id"))
    scan_debug_id       = Column(Integer, ForeignKey("scan_debug.id"))
    status              = Column(String, default="WAIT")
    expire_at           = Column(DateTime)
    filled_at           = Column(DateTime)
    created_at          = Column(DateTime, default=datetime.utcnow)
    rejection_reason    = Column(String, nullable=True)
    validation_details  = Column(JSON, nullable=True)


class MarketData(Base):
    __tablename__ = "market_data"
    id            = Column(BigInteger, primary_key=True)
    symbol        = Column(String, nullable=False)
    timeframe     = Column(String, nullable=False)
    time          = Column(DateTime, nullable=False)
    open          = Column(Numeric)
    high          = Column(Numeric)
    low           = Column(Numeric)
    close         = Column(Numeric)
    volume        = Column(Numeric)
    created_at    = Column(DateTime, server_default=func.now())
