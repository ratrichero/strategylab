"""
Bootstrap cache cho bot runtime.
Lưu trữ fallback data khi admin API tạm down.

Cache là file encrypted local:
  - encrypt bằng key derive từ BOT_SECRET
  - user bot không nhìn thấy, không sửa được
  - tự động cập nhật sau mỗi lần sync thành công

Cấu trúc cache:
  {
    "bot_id": "...",
    "db_url_encrypted": "...",
    "license_status": "active",
    "license_expires_at": "...",
    "last_sync_at": "...",
    "last_good_admin_endpoint": "...",
    "admin_endpoints_snapshot": [...],
    "cache_version": 1
  }
"""

import os
import json
from datetime import datetime, timezone
from typing import Optional
from dataclasses import dataclass, field, asdict

from app.core.encryption import encrypt_cache_file, decrypt_cache_file


CACHE_VERSION = 1


@dataclass
class BootstrapData:
    bot_id: str = ""
    db_url_encrypted: str = ""
    license_status: str = ""
    license_expires_at: str = ""
    last_sync_at: str = ""
    last_good_admin_endpoint: str = ""
    admin_endpoints_snapshot: list = field(default_factory=list)
    cache_version: int = CACHE_VERSION

    def is_valid(self) -> bool:
        """Cache có đủ data tối thiểu để boot không."""
        return bool(self.bot_id and self.db_url_encrypted)

    def is_license_active(self) -> bool:
        """License snapshot có còn hạn không."""
        if self.license_status not in ("active",):
            return False
        if not self.license_expires_at:
            return True  # không set expiry = unlimited
        try:
            expires = datetime.fromisoformat(self.license_expires_at)
            # Đảm bảo timezone aware
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) < expires
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "BootstrapData":
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class BootstrapCache:
    """
    Quản lý đọc/ghi bootstrap cache file.
    """

    def __init__(self, cache_path: str, bot_secret: str):
        self._cache_path = cache_path
        self._bot_secret = bot_secret

    def verify_parent_writable(self) -> bool:
        """Check that the configured cache directory can actually be written."""
        cache_dir = os.path.dirname(self._cache_path) or "."
        test_path = os.path.join(cache_dir, f".bootstrap_write_test_{os.getpid()}")
        try:
            os.makedirs(cache_dir, mode=0o700, exist_ok=True)
            with open(test_path, "w") as f:
                f.write("ok")
            os.remove(test_path)
            print(f"[BOOTSTRAP] Cache directory writable: {cache_dir}")
            return True
        except Exception as e:
            print(f"[BOOTSTRAP] Cache directory is not writable: {cache_dir}: {e}")
            return False

    def load(self) -> Optional[BootstrapData]:
        """
        Đọc cache từ file.
        Returns None nếu file không tồn tại hoặc decrypt fail.
        """
        if not os.path.exists(self._cache_path):
            return None

        try:
            with open(self._cache_path, "r") as f:
                encrypted = f.read().strip()

            if not encrypted:
                return None

            data = decrypt_cache_file(encrypted, self._bot_secret)
            if data is None:
                print("[BOOTSTRAP] Cache decrypt failed — file corrupted or secret changed")
                return None

            return BootstrapData.from_dict(data)

        except Exception as e:
            print(f"[BOOTSTRAP] Cache load error: {e}")
            return None

    def save(self, data: BootstrapData) -> bool:
        """
        Ghi cache xuống file.
        Tạo thư mục nếu chưa có.
        Returns True nếu thành công.
        """
        try:
            # Đảm bảo thư mục tồn tại
            cache_dir = os.path.dirname(self._cache_path)
            if cache_dir and not os.path.exists(cache_dir):
                os.makedirs(cache_dir, mode=0o700, exist_ok=True)

            encrypted = encrypt_cache_file(data.to_dict(), self._bot_secret)

            with open(self._cache_path, "w") as f:
                f.write(encrypted)

            # Set file permission 600 (owner read/write only)
            try:
                os.chmod(self._cache_path, 0o600)
            except OSError:
                pass  # Windows không support chmod

            if not os.path.exists(self._cache_path):
                print(f"[BOOTSTRAP] Cache save reported success but file is missing: {self._cache_path}")
                return False

            size = os.path.getsize(self._cache_path)
            #print(f"[BOOTSTRAP] Cache saved: {self._cache_path} ({size} bytes)")
            return True

        except Exception as e:
            print(f"[BOOTSTRAP] Cache save error at {self._cache_path}: {e}")
            return False

    def exists(self) -> bool:
        """Check cache file tồn tại không."""
        return os.path.exists(self._cache_path)
