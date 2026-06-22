"""
Bot Runtime — orchestrator cho BOT mode startup.

Chức năng:
  - Đọc env (BOT_ID, BOT_SECRET, ADMIN_ENDPOINTS)
  - Gọi admin API activate
  - Fallback bootstrap cache nếu admin down
  - Connect bot DB
  - Cung cấp trạng thái license cho runtime gate

Lifecycle:
  1. startup() → connect DB
  2. is_monitor_only() → check quyền trading
  3. get_license_info() → trả thông tin license hiện tại
"""

from typing import Optional
from dataclasses import dataclass

from app.core.app_role import get_bot_env
from app.bot_runtime.bootstrap import BootstrapCache, BootstrapData
from app.bot_runtime.license_client import LicenseClient
from app.db.session import configure_database


@dataclass
class RuntimeState:
    db_connected: bool = False
    database_url: str = ""  # plain, chỉ trong RAM
    license_status: str = ""
    license_expires_at: str = ""
    monitor_only: bool = True
    boot_source: str = ""  # "admin_api" hoặc "cache"
    heartbeat_interval_sec: int = 60


class BotRuntime:
    """
    Singleton quản lý bot runtime lifecycle.
    """

    def __init__(self):
        self._state = RuntimeState()
        self._license_client: Optional[LicenseClient] = None
        self._cache: Optional[BootstrapCache] = None
        self._bot_env = None

    def startup(self) -> bool:
        """
        Bot startup flow:
          1. Đọc env
          2. Gọi admin API
          3. Nếu admin fail → fallback cache
          4. Connect DB
          5. Set trạng thái

        Returns:
            True nếu boot thành công (DB connected)

        Raises:
            EnvironmentError nếu thiếu env
            RuntimeError nếu không boot được
        """
        print("\n🤖 [BOT RUNTIME] Starting...")

        # ── Step 1: Đọc env ────────────────────────────────────
        self._bot_env = get_bot_env()
        bot_id = self._bot_env["bot_id"]
        bot_secret = self._bot_env["bot_secret"]
        admin_endpoints = self._bot_env["admin_endpoints"]
        cache_path = self._bot_env["cache_path"]

        print(f"  BOT_ID: {bot_id[:8]}...")
        print(f"  ADMIN_ENDPOINTS: {', '.join(admin_endpoints)}")
        print(f"  CACHE_PATH: {cache_path}")

        # ── Step 2: Init cache + license client ────────────────
        self._cache = BootstrapCache(cache_path, bot_secret)
        self._license_client = LicenseClient(
            bot_id=bot_id,
            bot_secret=bot_secret,
            admin_endpoints=admin_endpoints,
            cache=self._cache,
        )

        # ── Step 3: Thử activate từ admin ─────────────────────
        print("\n  📡 Contacting admin server...")
        result = self._license_client.activate()

        if result.success:
            # ── Admin OK ────────────────────────────────────────
            print(f"  ✅ Admin response: status={result.status}, allowed={result.allowed}")

            if not result.database_url:
                raise RuntimeError("Admin returned empty database_url")

            self._state.database_url = result.database_url
            self._state.license_status = result.status
            self._state.license_expires_at = result.license_expires_at
            self._state.heartbeat_interval_sec = result.heartbeat_interval_sec
            self._state.boot_source = "admin_api"

            if result.allowed:
                self._state.monitor_only = False
            else:
                self._state.monitor_only = True
                print(f"  ⚠️ Bot not allowed: status={result.status}")

        else:
            # ── Admin fail → fallback cache ─────────────────────
            print(f"  ⚠️ Admin unreachable: {result.error}")
            print("  📦 Trying bootstrap cache...")

            if not self._boot_from_cache():
                raise RuntimeError(
                    "Cannot boot: admin unreachable and no valid bootstrap cache. "
                    "Bot must connect to admin at least once."
                )

        # ── Step 4: Connect DB ─────────────────────────────────
        print(f"\n  🔌 Connecting to bot database...")
        try:
            engine = configure_database(self._state.database_url, dispose_existing=True)

            # Test connection
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))

            self._state.db_connected = True
            print(f"  ✅ Bot DB connected (source: {self._state.boot_source})")

        except Exception as e:
            raise RuntimeError(f"Bot DB connection failed: {e}")

        # ── Summary ────────────────────────────────────────────
        mode_label = "monitor_only" if self._state.monitor_only else "full_trading"
        print(f"\n  📋 License: {self._state.license_status}")
        print(f"  📋 Expires: {self._state.license_expires_at or 'unlimited'}")
        print(f"  📋 Mode: {mode_label}")
        print(f"  📋 Boot source: {self._state.boot_source}")
        print("🤖 [BOT RUNTIME] Startup complete\n")

        return True

    def _boot_from_cache(self) -> bool:
        """
        Thử boot từ bootstrap cache.
        Returns True nếu cache valid + có DB URL.
        """
        cached = self._cache.load()

        if not cached or not cached.is_valid():
            print("  ❌ No valid bootstrap cache found")
            return False

        # Decrypt DB URL từ cache
        db_url = self._license_client.get_cached_db_url()
        if not db_url:
            print("  ❌ Cannot decrypt DB URL from cache")
            return False

        self._state.database_url = db_url
        self._state.license_status = cached.license_status
        self._state.license_expires_at = cached.license_expires_at
        self._state.boot_source = "cache"

        # Check license
        if cached.is_license_active():
            self._state.monitor_only = False
            print("  ✅ Cache valid, license active → full trading")
        else:
            self._state.monitor_only = True
            print("  ⚠️ Cache valid, but license expired → monitor_only")

        return True

    @property
    def state(self) -> RuntimeState:
        return self._state

    @property
    def license_client(self) -> Optional[LicenseClient]:
        return self._license_client

    def is_monitor_only(self) -> bool:
        return self._state.monitor_only

    def set_monitor_only(self, value: bool):
        if value != self._state.monitor_only:
            label = "monitor_only" if value else "full_trading"
            print(f"🔄 [BOT RUNTIME] Mode changed → {label}")
        self._state.monitor_only = value

    def get_license_info(self) -> dict:
        return {
            "status": self._state.license_status,
            "license_expires_at": self._state.license_expires_at,
            "monitor_only": self._state.monitor_only,
            "boot_source": self._state.boot_source,
            "db_connected": self._state.db_connected,
        }


# ── Singleton ─────────────────────────────────────────────────
_instance: Optional[BotRuntime] = None


def get_bot_runtime() -> BotRuntime:
    """Get singleton BotRuntime instance."""
    global _instance
    if _instance is None:
        _instance = BotRuntime()
    return _instance