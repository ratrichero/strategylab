"""
License client: bot runtime gọi admin API.

Chức năng:
  - activate(): gọi admin để nhận DB URL + license
  - heartbeat(): periodic sync
  - Thử nhiều endpoints, fallback lần lượt
  - Cập nhật bootstrap cache sau mỗi lần sync thành công
"""

import time
from datetime import datetime, timezone
from typing import Optional, List
from dataclasses import dataclass

import httpx

from app.core.encryption import decrypt_from_transport
from app.bot_runtime.bootstrap import BootstrapCache, BootstrapData


# ── Timeout config ────────────────────────────────────────────
CONNECT_TIMEOUT = 10  # seconds
REQUEST_TIMEOUT = 30  # seconds


@dataclass
class ActivateResult:
    success: bool
    allowed: bool = False
    status: str = ""
    database_url: str = ""  # plain, đã decrypt
    license_expires_at: str = ""
    admin_endpoints: Optional[List[str]] = None
    heartbeat_interval_sec: int = 60
    error: str = ""


@dataclass
class HeartbeatResult:
    success: bool
    status: str = ""
    license_expires_at: str = ""
    admin_endpoints: Optional[List[str]] = None
    db_url_changed: bool = False
    error: str = ""


class LicenseClient:
    """
    Client để bot gọi admin API.
    """

    def __init__(
        self,
        bot_id: str,
        bot_secret: str,
        admin_endpoints: List[str],
        cache: BootstrapCache,
    ):
        self._bot_id = bot_id
        self._bot_secret = bot_secret
        self._admin_endpoints = admin_endpoints
        self._cache = cache
        self._app_version = "5.0"
        self._start_time = time.time()

    def set_app_version(self, version: str):
        self._app_version = version

    def _build_endpoint_list(self) -> List[str]:
        """
        Tạo danh sách endpoint để thử, theo thứ tự ưu tiên:
          1. last_good từ cache
          2. từ env (self._admin_endpoints)
          3. từ cache snapshot
        Bỏ trùng, giữ thứ tự.
        """
        seen = set()
        ordered = []

        def _add(ep: str):
            ep = ep.rstrip("/")
            if ep and ep not in seen:
                seen.add(ep)
                ordered.append(ep)

        # Priority 1: last good từ cache
        cached = self._cache.load()
        if cached and cached.last_good_admin_endpoint:
            _add(cached.last_good_admin_endpoint)

        # Priority 2: từ env
        for ep in self._admin_endpoints:
            _add(ep)

        # Priority 3: từ cache snapshot
        if cached and cached.admin_endpoints_snapshot:
            for ep in cached.admin_endpoints_snapshot:
                _add(ep)

        return ordered

    def activate(self) -> ActivateResult:
        """
        Gọi admin /bot/auth/activate.
        Thử lần lượt các endpoint.

        Returns:
            ActivateResult với DB URL đã decrypt nếu thành công
        """
        endpoints = self._build_endpoint_list()

        if not endpoints:
            return ActivateResult(
                success=False,
                error="No admin endpoints available"
            )

        last_error = ""

        for endpoint in endpoints:
            url = f"{endpoint}/bot/auth/activate"
            try:
                print(f"  📡 Activating via {url}")
                with httpx.Client(timeout=httpx.Timeout(
                    connect=CONNECT_TIMEOUT,
                    read=REQUEST_TIMEOUT,
                    write=REQUEST_TIMEOUT,
                    pool=REQUEST_TIMEOUT,
                )) as client:
                    resp = client.post(url, json={
                        "bot_id": self._bot_id,
                        "bot_secret": self._bot_secret,
                        "app_version": self._app_version,
                    })

                if resp.status_code == 200:
                    data = resp.json()

                    # Decrypt DB URL
                    plain_db_url = ""
                    if data.get("database_url"):
                        try:
                            plain_db_url = decrypt_from_transport(
                                data["database_url"],
                                self._bot_secret
                            )
                        except Exception as e:
                            return ActivateResult(
                                success=False,
                                error=f"DB URL decrypt failed: {e}"
                            )

                    result = ActivateResult(
                        success=True,
                        allowed=data.get("allowed", False),
                        status=data.get("status", ""),
                        database_url=plain_db_url,
                        license_expires_at=data.get("license_expires_at", ""),
                        admin_endpoints=data.get("admin_endpoints"),
                        heartbeat_interval_sec=data.get("heartbeat_interval_sec", 60),
                    )

                    # Cập nhật cache
                    self._update_cache_from_activate(result, endpoint)

                    print(f"  ✅ Admin activate OK via {endpoint}")
                    return result

                elif resp.status_code == 401:
                    detail = resp.json().get("detail", "unauthorized")
                    print(f"  ❌ Admin activate rejected by {endpoint}: 401 {detail}")
                    return ActivateResult(
                        success=False,
                        error=f"Authentication failed: {detail}"
                    )
                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    print(f"  ❌ Admin activate failed via {endpoint}: {last_error}")

            except httpx.ConnectError:
                last_error = f"Cannot connect to {endpoint}"
                print(f"  ⚠️ Admin endpoint unreachable: {endpoint}")
            except httpx.TimeoutException:
                last_error = f"Timeout connecting to {endpoint}"
                print(f"  ⚠️ Admin endpoint timeout: {endpoint}")
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                print(f"  ⚠️ Admin endpoint error: {endpoint}: {last_error}")

        return ActivateResult(
            success=False,
            error=f"All admin endpoints failed. Last error: {last_error}"
        )

    def heartbeat(
        self,
        trading_mode: str = "",
        open_trades: int = 0,
        pending_count: int = 0,
    ) -> HeartbeatResult:
        """
        Gọi admin /bot/heartbeat.
        Thử lần lượt các endpoint.
        """
        endpoints = self._build_endpoint_list()

        if not endpoints:
            return HeartbeatResult(
                success=False,
                error="No admin endpoints available"
            )

        uptime = int(time.time() - self._start_time)
        last_error = ""

        for endpoint in endpoints:
            url = f"{endpoint}/bot/heartbeat"
            try:
                print(f"  📡 Heartbeat via {url}")
                with httpx.Client(timeout=httpx.Timeout(
                    connect=CONNECT_TIMEOUT,
                    read=REQUEST_TIMEOUT,
                    write=REQUEST_TIMEOUT,
                    pool=REQUEST_TIMEOUT,
                )) as client:
                    resp = client.post(url, json={
                        "bot_id": self._bot_id,
                        "bot_secret": self._bot_secret,
                        "app_version": self._app_version,
                        "uptime_seconds": uptime,
                        "trading_mode": trading_mode,
                        "open_trades": open_trades,
                        "pending_count": pending_count,
                    })

                if resp.status_code == 200:
                    data = resp.json()

                    result = HeartbeatResult(
                        success=True,
                        status=data.get("status", ""),
                        license_expires_at=data.get("license_expires_at", ""),
                        admin_endpoints=data.get("admin_endpoints"),
                        db_url_changed=data.get("db_url_changed", False),
                    )

                    # Cập nhật cache
                    self._update_cache_from_heartbeat(result, endpoint)

                    return result

                else:
                    last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                    print(f"  ❌ Admin heartbeat failed via {endpoint}: {last_error}")

            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                print(f"  ⚠️ Admin heartbeat error via {endpoint}: {last_error}")

        return HeartbeatResult(
            success=False,
            error=f"Heartbeat failed. Last: {last_error}"
        )

    def _update_cache_from_activate(self, result: ActivateResult, endpoint: str):
        """Cập nhật bootstrap cache sau activate thành công."""
        from app.core.encryption import encrypt_for_cache

        cached = self._cache.load() or BootstrapData()
        cached.bot_id = self._bot_id
        cached.license_status = result.status
        cached.license_expires_at = result.license_expires_at or ""
        cached.last_sync_at = datetime.now(timezone.utc).isoformat()
        cached.last_good_admin_endpoint = endpoint

        # Encrypt DB URL cho cache (khác key với transport)
        if result.database_url:
            cached.db_url_encrypted = encrypt_for_cache(
                result.database_url, self._bot_secret
            )

        if result.admin_endpoints:
            cached.admin_endpoints_snapshot = result.admin_endpoints

        if not self._cache.save(cached):
            print("[LICENSE CLIENT] Bootstrap cache was not saved after activate")

    def _update_cache_from_heartbeat(self, result: HeartbeatResult, endpoint: str):
        """Cập nhật bootstrap cache sau heartbeat thành công."""
        cached = self._cache.load()
        if not cached:
            return

        cached.license_status = result.status
        cached.license_expires_at = result.license_expires_at or cached.license_expires_at
        cached.last_sync_at = datetime.now(timezone.utc).isoformat()
        cached.last_good_admin_endpoint = endpoint

        if result.admin_endpoints:
            cached.admin_endpoints_snapshot = result.admin_endpoints

        if not self._cache.save(cached):
            print("[LICENSE CLIENT] Bootstrap cache was not saved after heartbeat")

    def get_cached_db_url(self) -> Optional[str]:
        """
        Đọc DB URL từ bootstrap cache.
        Dùng khi admin API down.
        Returns plain DB URL hoặc None.
        """
        cached = self._cache.load()
        if not cached or not cached.db_url_encrypted:
            return None

        try:
            from app.core.encryption import decrypt_from_cache
            return decrypt_from_cache(cached.db_url_encrypted, self._bot_secret)
        except Exception as e:
            print(f"[LICENSE CLIENT] Cache DB URL decrypt failed: {e}")
            return None

    def get_cached_data(self) -> Optional[BootstrapData]:
        """Đọc toàn bộ bootstrap cache data."""
        return self._cache.load()
