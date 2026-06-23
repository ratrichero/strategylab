"""
Migration: Update mv_signal_performance Materialized View
=========================================================
Add missing fields to mv_signal_performance for dashboard use:
- entry_price, stop_loss, take_profit, exit_price (from signals)
- market_context (from signals)
- indicators_snapshot (from scan_debug)

This allows dashboard to query without additional JOINs.
"""

from sqlalchemy import text


def upgrade(db):
    """Update materialized view with additional fields."""
    try:
        # Drop existing view
        db.execute(text("DROP MATERIALIZED VIEW IF EXISTS mv_signal_performance CASCADE"))
        
        # Recreate view with additional fields
        db.execute(text("""
            CREATE MATERIALIZED VIEW mv_signal_performance AS
            SELECT
              s.id,
              s.symbol,
              s.timeframe,
              s.pattern,
              s.direction,
              s.regime,
              s.score,
              s.status,
              s.result_percent,
              s.engine_version,
              s.strategy_name,
              s.entry_price,
              s.stop_loss,
              s.take_profit,
              s.exit_price,
              s.candle_time,
              s.exit_time,
              s.created_at,
              s.exit_reason,
              s.trading_mode,
              s.market_context,
              sf.trend_score,
              sf.momentum_score,
              sf.volume_score,
              sf.pattern_score,
              sf.mtf_score,
              sf.penalty_norm,
              sf.total_score,
              sf.rr,
              toa.rr_planned,
              toa.rr_realized,
              toa.trade_return,
              toa.max_drawdown AS mae,
              toa.max_favorable AS mfe,
              toa.label,
              toa.exit_reason AS toa_exit_reason,
              toa.time_to_exit,
              toa.time_to_mae,
              toa.time_to_mfe,
              sd.indicators_snapshot
            FROM signals s
            LEFT JOIN signal_features sf ON sf.signal_id = s.id
            LEFT JOIN trade_outcome_analytics toa ON toa.signal_id = s.id
            LEFT JOIN scan_debug sd ON sd.signal_id = s.id
            WHERE s.status IN ('WIN', 'LOSS', 'MANUAL')
            WITH DATA
        """))
        
        # Recreate indexes
        db.execute(text("CREATE INDEX idx_mv_signal_performance_symbol ON mv_signal_performance(symbol)"))
        db.execute(text("CREATE INDEX idx_mv_signal_performance_status ON mv_signal_performance(status)"))
        db.execute(text("CREATE INDEX idx_mv_signal_performance_candle_time ON mv_signal_performance(candle_time DESC)"))
        db.execute(text("CREATE INDEX idx_mv_signal_performance_timeframe ON mv_signal_performance(timeframe)"))
        db.execute(text("CREATE INDEX idx_mv_signal_performance_regime ON mv_signal_performance(regime)"))
        
        db.commit()
        print("[OK] Successfully updated mv_signal_performance materialized view")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to update mv_signal_performance: {e}")
        raise


def downgrade(db):
    """Revert to original view definition."""
    try:
        # Drop updated view
        db.execute(text("DROP MATERIALIZED VIEW IF EXISTS mv_signal_performance CASCADE"))
        
        # Recreate original view
        db.execute(text("""
            CREATE MATERIALIZED VIEW mv_signal_performance AS
            SELECT
              s.id,
              s.symbol,
              s.timeframe,
              s.pattern,
              s.direction,
              s.regime,
              s.score,
              s.status,
              s.result_percent,
              s.engine_version,
              s.strategy_name,
              s.candle_time,
              s.exit_time,
              s.created_at,
              s.exit_reason,
              s.trading_mode,
              sf.trend_score,
              sf.momentum_score,
              sf.volume_score,
              sf.pattern_score,
              sf.mtf_score,
              sf.penalty_norm,
              sf.total_score,
              sf.rr,
              toa.rr_planned,
              toa.rr_realized,
              toa.trade_return,
              toa.max_drawdown AS mae,
              toa.max_favorable AS mfe,
              toa.label,
              toa.exit_reason AS toa_exit_reason,
              toa.time_to_exit,
              toa.time_to_mae,
              toa.time_to_mfe
            FROM signals s
            LEFT JOIN signal_features sf ON sf.signal_id = s.id
            LEFT JOIN trade_outcome_analytics toa ON toa.signal_id = s.id
            WHERE s.status IN ('WIN', 'LOSS', 'MANUAL')
            WITH DATA
        """))
        
        # Recreate indexes
        db.execute(text("CREATE INDEX idx_mv_signal_performance_symbol ON mv_signal_performance(symbol)"))
        db.execute(text("CREATE INDEX idx_mv_signal_performance_status ON mv_signal_performance(status)"))
        db.execute(text("CREATE INDEX idx_mv_signal_performance_candle_time ON mv_signal_performance(candle_time DESC)"))
        db.execute(text("CREATE INDEX idx_mv_signal_performance_timeframe ON mv_signal_performance(timeframe)"))
        db.execute(text("CREATE INDEX idx_mv_signal_performance_regime ON mv_signal_performance(regime)"))
        
        db.commit()
        print("[OK] Successfully reverted mv_signal_performance to original definition")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to revert mv_signal_performance: {e}")
        raise


if __name__ == "__main__":
    """Run migration directly."""
    from app.db.session import SessionLocal
    
    print("Running migration: update_mv_signal_performance")
    print("=" * 60)
    
    with SessionLocal() as db:
        try:
            upgrade(db)
            print("\n[OK] Migration completed successfully")
        except Exception as e:
            print(f"\n[ERROR] Migration failed: {e}")
            raise
