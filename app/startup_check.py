import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


VALID_ROLES = {"ADMIN", "BOT"}


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass


def _app_role() -> str:
    role = os.getenv("APP_ROLE", "ADMIN").strip().upper()
    return role if role in VALID_ROLES else "ADMIN"


def check_critical_files():
    critical = [
        "app/core/config.py",
        "app/core/app_role.py",
        "app/core/encryption.py",
        "app/core/trading_mode.py",
        "app/db/models.py",
        "app/db/session.py",
        "app/db/async_pool.py",
        "app/services/binance_service.py",
        "app/services/indicator_service.py",
        "app/services/signal_service.py",
        "app/services/config_service.py",
        "app/services/price_feed.py",
        "app/services/pending_engine.py",
        "app/services/trade_monitor.py",
        "app/services/trade_close_service.py",
        "app/services/outcome_service.py",
        "app/services/open_trade_filter.py",
        "app/services/prefill_validator.py",
        "app/services/report_service.py",
        "app/strategies/base.py",
        "app/strategies/registry.py",
        "app/strategies/candlestick_strategy.py",
        "app/ml/config.py",
        "app/ml/features.py",
        "app/ml/predict.py",
        "app/analytics/performance_engine.py",
        "app/bot/telegram_bot.py",
        "app/bot/handlers.py",
        "app/api/health.py",
        "app/api/scan.py",
        "app/auth/routes.py",
        "app/auth/migration.py",
    ]
    if _app_role() == "ADMIN":
        critical += [
            "app/control/admin_routes.py",
            "app/control/bot_api.py",
            "app/control/migration.py",
        ]
    else:
        critical += [
            "app/bot_runtime/runtime.py",
            "app/bot_runtime/bootstrap.py",
            "app/bot_runtime/license_client.py",
            "app/bot_runtime/runtime_gate.py",
        ]
    return [f for f in critical if not os.path.exists(f)]


def check_env_vars():
    _load_env()
    role = _app_role()
    required = ["JWT_SECRET_KEY"]
    warnings = []

    if not os.getenv("APP_ROLE"):
        warnings.append("APP_ROLE is not set; defaulting to ADMIN.")

    if role == "ADMIN":
        required += ["DATABASE_URL", "ADMIN_MASTER_KEY"]
        if not os.getenv("TELEGRAM_TOKEN") or not os.getenv("TELEGRAM_CHAT_ID"):
            warnings.append("Telegram is not configured; polling bot/notifications will be disabled.")
    else:
        required += ["BOT_ID", "BOT_SECRET", "ADMIN_ENDPOINTS"]

    missing = [k for k in required if not os.getenv(k)]
    return missing, warnings


def check_db_connection():
    role = _app_role()
    try:
        if role == "BOT" and not os.getenv("DATABASE_URL"):
            from app.bot_runtime.runtime import get_bot_runtime
            runtime = get_bot_runtime()
            runtime.startup()
        else:
            from app.db.session import configure_database
            configure_database(os.getenv("DATABASE_URL", ""))

        from app.db.session import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return True, None
    except Exception as e:
        return False, str(e)


def run_all_checks():
    _load_env()
    role = _app_role()

    print("\n" + "=" * 60)
    print(f"STARTUP VALIDATION [{role}]")
    print("=" * 60)

    all_ok = True

    missing = check_critical_files()
    if missing:
        print(f"\nMISSING FILES ({len(missing)}):")
        for f in missing:
            print(f"  - {f}")
        all_ok = False
    else:
        print("\n  All critical files present")

    missing_env, warnings = check_env_vars()
    if missing_env:
        print(f"\nMISSING ENV: {missing_env}")
        all_ok = False
    else:
        print("  Required env vars OK")

    for warning in warnings:
        print(f"  WARN: {warning}")

    db_ok, db_err = check_db_connection()
    if not db_ok:
        print(f"\nDB FAIL: {db_err}")
        all_ok = False
    else:
        print("  DB connected")

    print("\n" + "=" * 60)
    print("ALL OK" if all_ok else "ISSUES FOUND")
    print("=" * 60 + "\n")
    return all_ok


if __name__ == "__main__":
    raise SystemExit(0 if run_all_checks() else 1)
