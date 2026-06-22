"""
Migration: Add Retry Policy Config
==================================
Insert default RETRY_POLICY_CONFIG into app_config table.
Run this migration to enable the new retry policy service.
"""

import json
from sqlalchemy import text


def upgrade(db):
    """Insert default retry policy config."""
    default_config = {
        "enabled": True,
        "error_classification": {
            "deterministic": [
                "insufficient balance",
                "margin is insufficient",
                "leverage failed",
                "qty too small",
                "actual notional too small",
                "order would immediately trigger",
                "price is outside the price band",
                "apikey permission",
                "symbol not trading",
                "set_leverage_failed",
            ],
            "temporary": [
                "timeout",
                "network",
                "connection",
                "connection reset",
                "connection refused",
            ],
            "rate_limit": [
                "too many requests",
                "rate limit",
                "429",
            ]
        },
        "retry_strategies": {
            "duplicate_guard": {
                "max_retries": 0,
                "backoff": "none"
            },
            "deterministic": {
                "max_retries": 0,
                "backoff": "none"
            },
            "temporary": {
                "max_retries": 5,
                "backoff": "exponential",
                "initial": 10,
                "max": 300
            },
            "rate_limit": {
                "max_retries": 3,
                "backoff": "fixed",
                "seconds": 60
            }
        },
        "circuit_breaker": {
            "enabled": True,
            "failure_threshold": 5,
            "cooldown_seconds": 300
        }
    }
    
    try:
        # Check if config already exists
        existing = db.execute(
            text("SELECT value FROM app_config WHERE key = 'RETRY_POLICY_CONFIG'")
        ).fetchone()
        
        if existing:
            print("RETRY_POLICY_CONFIG already exists, skipping insertion")
            return
        
        # Insert default config
        db.execute(
            text("""
                INSERT INTO app_config (key, value, updated_at)
                VALUES (:key, :value, NOW())
            """),
            {
                "key": "RETRY_POLICY_CONFIG",
                "value": json.dumps(default_config)
            }
        )
        db.commit()
        print("[OK] Successfully inserted RETRY_POLICY_CONFIG")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to insert RETRY_POLICY_CONFIG: {e}")
        raise


def downgrade(db):
    """Remove retry policy config."""
    try:
        db.execute(
            text("DELETE FROM app_config WHERE key = 'RETRY_POLICY_CONFIG'")
        )
        db.commit()
        print("[OK] Successfully removed RETRY_POLICY_CONFIG")
        
    except Exception as e:
        db.rollback()
        print(f"[ERROR] Failed to remove RETRY_POLICY_CONFIG: {e}")
        raise


if __name__ == "__main__":
    """Run migration directly."""
    from app.db.session import SessionLocal
    
    print("Running migration: add_retry_policy_config")
    print("=" * 60)
    
    with SessionLocal() as db:
        try:
            upgrade(db)
            print("\n[OK] Migration completed successfully")
        except Exception as e:
            print(f"\n[ERROR] Migration failed: {e}")
            raise
