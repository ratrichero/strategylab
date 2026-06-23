"""
Migration: Add Volatility Alert Config
=======================================
Insert default VOL_ALERT_CONFIG into app_config table.
Run this migration to enable the new volatility alert configuration.
"""

import json
from sqlalchemy import text


def upgrade(db):
    """Insert default volatility alert config."""
    default_config = {
        "enabled": True,
        "cycle_seconds": 3,
        "symbols_limit": 1200,
        "history_seconds": 600,
        "btc": {
            "threshold_1m_pct": 2.0,
            "threshold_5m_pct": 3.5,
            "cooldown_minutes": 20
        },
        "major": {
            "threshold_1m_pct": 5.0,
            "threshold_5m_pct": 8.0,
            "cooldown_minutes": 30,
            "symbols": ["ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "ADAUSDT"]
        },
        "watchlist": {
            "threshold_1m_pct": 6.0,
            "threshold_5m_pct": 10.0,
            "cooldown_minutes": 25,
            "symbols": []
        },
        "coin": {
            "threshold_1m_pct": 10.0,
            "threshold_5m_pct": 15.0,
            "cooldown_minutes": 40
        },
        "unusual_ratio": 3.0,
        "priority_symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"],
        "exclude_tokens": ["UP", "DOWN", "BULL", "BEAR", "SHORT", "LONG"]
    }
    
    try:
        # Check if config already exists
        existing = db.execute(
            text("SELECT value FROM app_config WHERE key = 'VOL_ALERT_CONFIG'")
        ).fetchone()
        
        if existing:
            print("VOL_ALERT_CONFIG already exists, skipping insertion")
            return
        
        # Insert default config
        db.execute(
            text("""
                INSERT INTO app_config (key, value, updated_at)
                VALUES (:key, :value, NOW())
            """),
            {
                "key": "VOL_ALERT_CONFIG",
                "value": json.dumps(default_config)
            }
        )
        db.commit()
        print("[OK] Successfully inserted VOL_ALERT_CONFIG")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to insert VOL_ALERT_CONFIG: {e}")
        raise


def downgrade(db):
    """Remove volatility alert config."""
    try:
        db.execute(
            text("DELETE FROM app_config WHERE key = 'VOL_ALERT_CONFIG'")
        )
        db.commit()
        print("[OK] Successfully removed VOL_ALERT_CONFIG")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to remove VOL_ALERT_CONFIG: {e}")
        raise


if __name__ == "__main__":
    """Run migration directly."""
    from app.db.session import SessionLocal
    
    print("Running migration: add_vol_alert_config")
    print("=" * 60)
    
    with SessionLocal() as db:
        try:
            upgrade(db)
            print("\n[OK] Migration completed successfully")
        except Exception as e:
            print(f"\n[ERROR] Migration failed: {e}")
            raise
