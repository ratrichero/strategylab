"""
Khởi tạo Bot Database khi admin tạo bot mới.

Chức năng:
  - Validate connection đến bot DB
  - Chạy trading schema migration trên bot DB
  - Chạy auth migration trên bot DB (dashboard_users)
  - Tạo dashboard user đầu tiên cho bot
  - Insert default app_config values

Đặc điểm:
  - Idempotent
  - Không DROP table
  - Dùng engine riêng (không phải admin engine)
"""

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.auth.models import DashboardUser
from app.auth.password import hash_password

# Import trading models để Base.metadata biết về chúng
from app.db.models import Signal, PendingSignal  # noqa: F401 — cần cho metadata
from app.auth.models import DashboardUser  # noqa: F401


BOT_DB_TABLES = [
    "signals",
    "signal_features",
    "trade_outcome_analytics",
    "scan_config",
    "scan_run",
    "scan_debug",
    "pending_signals",
    "execution_commands",
    "market_data",
    "app_config",
    "strategy_stats",
    "model_registry",
    "audit_logs",
    "reports",
    "dashboard_users",
]


def validate_db_connection(database_url: str) -> bool:
    """
    Test kết nối đến database.
    Returns True nếu connect được, False nếu không.
    """
    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        return True
    except Exception as e:
        print(f"[BOT DB INIT] Connection failed: {e}")
        return False


def init_bot_database(
    database_url: str,
    dashboard_username: str,
    dashboard_password: str,
) -> dict:
    """
    Khởi tạo toàn bộ Bot Database.

    Steps:
      1. Connect đến bot DB
      2. Tạo tất cả trading tables nếu chưa có
      3. Tạo dashboard_users table nếu chưa có
      4. Tạo dashboard user cho bot owner
      5. Insert default app_config values

    Args:
        database_url: connection string cho bot DB
        dashboard_username: username cho bot dashboard login
        dashboard_password: plain password cho bot dashboard login

    Returns:
        dict: { success, message, tables_created, user_created }

    Raises:
        Exception nếu có lỗi nghiêm trọng
    """
    result = {
        "success": False,
        "message": "",
        "tables_created": [],
        "user_created": False,
    }

    try:
        engine = create_engine(database_url, pool_pre_ping=True)
        Session = sessionmaker(bind=engine)

        # ── Step 1: Tạo tất cả tables ─────────────────────────
        inspector = inspect(engine)
        existing_before = set(inspector.get_table_names())

        table_objects = [
            Base.metadata.tables[name]
            for name in BOT_DB_TABLES
            if name in Base.metadata.tables
        ]
        Base.metadata.create_all(engine, tables=table_objects, checkfirst=True)

        inspector = inspect(engine)
        existing_after = set(inspector.get_table_names())
        new_tables = existing_after - existing_before
        result["tables_created"] = list(new_tables)

        if new_tables:
            print(f"  📦 Bot DB: created tables: {', '.join(new_tables)}")
        else:
            print(f"  ✅ Bot DB: all tables already exist")

        # ── Step 2: Tạo dashboard user ────────────────────────
        db = Session()
        try:
            existing_user = db.query(DashboardUser).filter(
                DashboardUser.username == dashboard_username
            ).first()

            if existing_user:
                print(f"  ✅ Bot DB: dashboard user '{dashboard_username}' already exists")
                result["user_created"] = False
            else:
                user = DashboardUser(
                    username=dashboard_username,
                    password_hash=hash_password(dashboard_password),
                    role="USER",
                    is_active=True,
                )
                db.add(user)
                db.commit()
                print(f"  ✅ Bot DB: created dashboard user '{dashboard_username}'")
                result["user_created"] = True

            # ── Step 3: Insert default app_config ──────────────
            _ensure_default_app_config(db)

            db.commit()
        finally:
            db.close()

        engine.dispose()

        result["success"] = True
        result["message"] = "Bot database initialized successfully"

    except Exception as e:
        result["success"] = False
        result["message"] = f"Bot database init failed: {e}"
        print(f"  ❌ {result['message']}")
        raise

    return result


def _ensure_default_app_config(db):
    """
    Insert default app_config values nếu chưa có.
    Dùng DEFAULTS từ config_service.
    """
    from app.services.config_service import DEFAULTS

    existing_keys = set()
    try:
        rows = db.execute(text("SELECT key FROM app_config")).fetchall()
        existing_keys = {r[0] for r in rows}
    except Exception:
        # Table might not exist yet or be empty
        pass

    inserted = 0
    for key, value in DEFAULTS.items():
        if key not in existing_keys:
            try:
                db.execute(
                    text("""
                        INSERT INTO app_config (key, value, updated_at)
                        VALUES (:k, :v, NOW())
                        ON CONFLICT (key) DO NOTHING
                    """),
                    {"k": key, "v": str(value)}
                )
                inserted += 1
            except Exception:
                pass

    if inserted > 0:
        print(f"  ✅ Bot DB: inserted {inserted} default app_config values")
