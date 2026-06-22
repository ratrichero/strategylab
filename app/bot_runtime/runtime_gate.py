"""
Runtime Gate — check quyền hoạt động của bot.

Dùng bởi:
  - scanner: trước khi scan
  - scheduler: trước khi enqueue scan
  - bất kỳ chỗ nào cần check bot được phép trading không

Logic:
  - Nếu monitor_only → không scan, không mở lệnh
  - Check realtime license expiry
"""

from datetime import datetime, timezone
from typing import Optional


class RuntimeGate:
    """
    Gate kiểm soát quyền hoạt động.
    Singleton, được cập nhật bởi heartbeat.
    """

    def __init__(self):
        self._status: str = "active"
        self._license_expires_at: Optional[str] = None
        self._monitor_only: bool = False
        self._last_sync_at: Optional[str] = None

    def update(
        self,
        status: str,
        license_expires_at: Optional[str] = None,
        monitor_only: Optional[bool] = None,
    ):
        """Cập nhật từ heartbeat hoặc activate response."""
        old_status = self._status
        self._status = status
        self._license_expires_at = license_expires_at
        self._last_sync_at = datetime.now(timezone.utc).isoformat()

        if monitor_only is not None:
            self._monitor_only = monitor_only
        else:
            # Auto detect từ status
            self._monitor_only = status not in ("active",)

        if old_status != status:
            print(f"🔄 [RUNTIME GATE] Status: {old_status} → {status}")

    def is_allowed(self) -> bool:
        """
        Bot được phép full trading không?
        Check cả status và license expiry realtime.
        """
        if self._monitor_only:
            return False

        if self._status not in ("active",):
            return False

        # Check license expiry realtime
        if self._license_expires_at:
            try:
                expires = datetime.fromisoformat(self._license_expires_at)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) >= expires:
                    self._monitor_only = True
                    self._status = "expired"
                    print("⏰ [RUNTIME GATE] License expired → monitor_only")
                    return False
            except (ValueError, TypeError):
                pass

        return True

    def is_monitor_only(self) -> bool:
        """Inverse of is_allowed, check realtime."""
        return not self.is_allowed()

    def get_info(self) -> dict:
        return {
            "status": self._status,
            "license_expires_at": self._license_expires_at,
            "monitor_only": self._monitor_only,
            "last_sync_at": self._last_sync_at,
        }


# ── Singleton ─────────────────────────────────────────────────
_gate: Optional[RuntimeGate] = None


def get_runtime_gate() -> RuntimeGate:
    global _gate
    if _gate is None:
        _gate = RuntimeGate()
    return _gate