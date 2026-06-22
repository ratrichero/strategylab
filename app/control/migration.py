"""
Migration tự động cho Control Plane tables.
Chỉ chạy khi APP_ROLE=ADMIN.

Đặc điểm:
  - Idempotent: chạy nhiều lần không lỗi
  - Không DROP table
  - Không xóa data trading hiện tại
  - Không tạo user (admin tạo qua first-visit setup ở auth module)
  - Sau khi DB đã chuẩn hóa, tắt bằng SKIP_CONTROL_MIGRATION=true
"""

import os
from sqlalchemy import inspect

from app.db.session import Base, get_engine

# Import models để Base.metadata biết về chúng
from app.control.models import (
    BotRegistry, BotCredential,
    BotHeartbeatLog, BotAuditLog
)

# ── Cờ để tắt migration sau khi DB đã chuẩn hóa ──────────
_SKIP_ENV = "SKIP_CONTROL_MIGRATION"

# ── Danh sách bảng control plane ──────────────────────────
CONTROL_TABLES = [
    "bot_registry",
    "bot_credentials",
    "bot_heartbeat_logs",
    "bot_audit_logs",
]


def run_control_plane_migration():
    """
    Tạo các bảng control plane nếu chưa có.
    Idempotent — an toàn chạy lại nhiều lần.

    Yêu cầu: dashboard_users phải đã tồn tại
    (được tạo bởi auth migration chạy trước).
    """
    # Cho phép tắt migration khi DB đã chuẩn hóa
    if os.environ.get(_SKIP_ENV, "").lower() == "true":
        return

    print("\n🔧 [CONTROL MIGRATION] Running control plane migration...")

    engine = get_engine()
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # ── Kiểm tra dashboard_users đã tồn tại chưa ──────────
    if "dashboard_users" not in existing_tables:
        print("  ⚠️  dashboard_users not found — run auth migration first")
        print("  ⚠️  Skipping control plane migration")
        return

    # ── Xác định bảng nào cần tạo ─────────────────────────
    tables_to_create = []
    tables_existing = []

    for table_name in CONTROL_TABLES:
        if table_name in existing_tables:
            tables_existing.append(table_name)
        else:
            tables_to_create.append(table_name)

    if tables_existing:
        print(f"  ✅ Already exist: {', '.join(tables_existing)}")

    if not tables_to_create:
        print("  ✅ All control plane tables already exist")
    else:
        print(f"  📦 Creating: {', '.join(tables_to_create)}")

        # Chỉ tạo các bảng thuộc control plane
        control_table_objects = [
            Base.metadata.tables[t]
            for t in tables_to_create
            if t in Base.metadata.tables
        ]

        if control_table_objects:
            Base.metadata.create_all(
                engine,
                tables=control_table_objects,
                checkfirst=True
            )
            print(f"  ✅ Created: {', '.join(tables_to_create)}")

    print("🔧 [CONTROL MIGRATION] Complete\n")
