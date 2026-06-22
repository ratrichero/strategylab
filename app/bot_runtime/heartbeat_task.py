"""
Background heartbeat task cho bot runtime.
Định kỳ gọi admin API để sync status/license/endpoints.
"""

import asyncio
from typing import Optional

from app.core.bg_runner import is_shutting_down
from app.bot_runtime.runtime_gate import get_runtime_gate
from app.bot_runtime.license_client import LicenseClient


async def bot_heartbeat_loop(
    license_client: LicenseClient,
    interval_sec: int = 60,
):
    """
    Background loop: gọi admin heartbeat mỗi N giây.

    Cập nhật:
      - RuntimeGate (status, license)
      - Bootstrap cache (endpoints, license snapshot)
      - BotRuntime monitor_only state

    Nếu admin unreachable:
      - không crash
      - giữ state hiện tại
      - RuntimeGate tự check license expiry realtime
    """
    gate = get_runtime_gate()

    print(f"💓 [HEARTBEAT] Started (interval={interval_sec}s)")

    while True:
        await asyncio.sleep(interval_sec)

        if is_shutting_down():
            print("💓 [HEARTBEAT] Shutting down")
            return

        try:
            # Lấy stats hiện tại
            trading_mode = ""
            open_trades = 0
            pending_count = 0

            try:
                from app.services.config_service import get_runtime_config
                cfg = get_runtime_config()
                trading_mode = cfg.get("TRADING_MODE", "")

                from app.db.session import SessionLocal
                from app.db.models import Signal, PendingSignal
                with SessionLocal() as db:
                    open_trades = db.query(Signal).filter(
                        Signal.status == "OPEN"
                    ).count()
                    pending_count = db.query(PendingSignal).filter(
                        PendingSignal.status == "WAIT"
                    ).count()
            except Exception:
                pass

            # Gọi heartbeat
            result = license_client.heartbeat(
                trading_mode=trading_mode,
                open_trades=open_trades,
                pending_count=pending_count,
            )

            if result.success:
                # Cập nhật gate
                gate.update(
                    status=result.status,
                    license_expires_at=result.license_expires_at,
                )

                # Cập nhật BotRuntime
                from app.bot_runtime.runtime import get_bot_runtime
                runtime = get_bot_runtime()
                runtime.set_monitor_only(gate.is_monitor_only())
                runtime._state.license_status = result.status
                runtime._state.license_expires_at = result.license_expires_at

                if result.db_url_changed:
                    print("📢 [HEARTBEAT] Admin has updated DB URL — will apply on next restart")

            else:
                # Admin unreachable — không crash, gate tự check expiry
                pass

        except Exception as e:
            print(f"💓 [HEARTBEAT ERROR] {e}")