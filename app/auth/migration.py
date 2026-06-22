"""
Migration tự động cho dashboard_users table.
Chạy cho CẢ admin DB và bot DB khi startup.

Đặc điểm:
  - Idempotent: chạy nhiều lần không lỗi
  - Không DROP table
  - Không tạo user mặc định (admin tạo qua first-visit setup)
  - Sau khi DB đã chuẩn hóa, có thể tắt bằng SKIP_AUTH_MIGRATION=true
"""

import os
from sqlalchemy import inspect

from app.db.session import Base, get_engine

# Import model để Base.metadata biết về nó
from app.auth.models import DashboardUser

# ── Cờ để tắt migration sau khi DB đã chuẩn hóa ──────────
_SKIP_ENV = "SKIP_AUTH_MIGRATION"


def run_auth_migration():
    """
    Tạo bảng dashboard_users nếu chưa có.
    Idempotent — an toàn chạy lại nhiều lần.
    """
    # Cho phép tắt migration khi DB đã chuẩn hóa
    if os.environ.get(_SKIP_ENV, "").lower() == "true":
        return

    print("🔧 [AUTH MIGRATION] Checking dashboard_users table...")

    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "dashboard_users" in existing_tables:
        print("  ✅ dashboard_users already exists")
        return

    print("  📦 Creating dashboard_users table...")

    table_obj = Base.metadata.tables.get("dashboard_users")
    if table_obj is not None:
        Base.metadata.create_all(
            engine,
            tables=[table_obj],
            checkfirst=True
        )
        print("  ✅ dashboard_users created")
    else:
        print("  ❌ dashboard_users not found in metadata — check model import")
