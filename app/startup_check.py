import os, sys

def check_critical_files():
    critical = [
        "app/core/config.py", "app/core/auth.py", "app/core/trading_mode.py",
        "app/db/models.py", "app/db/session.py", "app/db/async_pool.py",
        "app/services/binance_service.py", "app/services/indicator_service.py",
        "app/services/signal_service.py", "app/services/config_service.py",
        "app/services/price_feed.py", "app/services/pending_engine.py",
        "app/services/trade_monitor.py", "app/services/trade_close_service.py",
        "app/services/outcome_service.py", "app/services/open_trade_filter.py",
        "app/services/prefill_validator.py", "app/services/report_service.py",
        "app/strategies/base.py", "app/strategies/registry.py",
        "app/strategies/candlestick_strategy.py",
        "app/ml/config.py", "app/ml/features.py", "app/ml/predict.py",
        "app/analytics/performance_engine.py",
        "app/bot/telegram_bot.py", "app/bot/handlers.py",
        "app/api/health.py", "app/api/scan.py",
    ]
    return [f for f in critical if not os.path.exists(f)]

def check_env_vars():
    from dotenv import load_dotenv
    load_dotenv()
    required = ["DATABASE_URL", "TELEGRAM_TOKEN", "TELEGRAM_CHAT_ID"]
    return [k for k in required if not os.getenv(k)]

def check_db_connection():
    try:
        from app.db.session import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True, None
    except Exception as e:
        return False, str(e)

def run_all_checks():
    print("\n" + "="*60)
    print("STARTUP VALIDATION")
    print("="*60)
    all_ok = True
    missing = check_critical_files()
    if missing:
        print(f"\nMISSING FILES ({len(missing)}):")
        for f in missing: print(f"  - {f}")
        all_ok = False
    else: print("\n  All critical files present")
    missing_env = check_env_vars()
    if missing_env:
        print(f"\nMISSING ENV: {missing_env}")
        all_ok = False
    else: print("  Env vars OK")
    db_ok, db_err = check_db_connection()
    if not db_ok:
        print(f"\nDB FAIL: {db_err}")
        all_ok = False
    else: print("  DB connected")
    print("\n" + "="*60)
    print("ALL OK" if all_ok else "ISSUES FOUND")
    print("="*60 + "\n")
    return all_ok
