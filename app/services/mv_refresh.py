import asyncio
import threading

_refresh_lock = threading.Lock()

async def safe_refresh_loop():
    while True:
        await asyncio.sleep(1200)  # 20 minutes
        await safe_refresh_once()

async def safe_refresh_once():
    try:
        await asyncio.to_thread(_do_refresh)
    except Exception as e:
        print(f"[MV REFRESH] {e}")

def _do_refresh():
    from app.db.session import SessionLocal
    from sqlalchemy import text
    MVS = ["mv_signal_performance", "mv_scan_flat"]
    if not _refresh_lock.acquire(blocking=False):
        print("[MV REFRESH] skipped: refresh already running")
        return
    with SessionLocal() as db:
        try:
            for mv in MVS:
                try:
                    db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv}"))
                    db.commit()
                    #print(f"  Refreshed: {mv}")
                except Exception as e:
                    print(f"  [MV] Concurrent refresh failed for {mv}: {e}")
                    db.rollback()
                    try:
                        db.execute(text(f"REFRESH MATERIALIZED VIEW {mv}"))
                        db.commit()
                        print(f"  [MV] Refreshed without CONCURRENTLY: {mv}")
                    except Exception as fallback_error:
                        print(f"  [MV] Skip {mv}: {fallback_error}")
                        db.rollback()
        finally:
            _refresh_lock.release()

def refresh_views_async(reason: str = "manual"):
    def _runner():
        try:
            print(f"[MV REFRESH] requested: {reason}")
            _do_refresh()
        except Exception as e:
            print(f"[MV REFRESH] async error: {e}")

    t = threading.Thread(target=_runner, name=f"mv_refresh_{reason}", daemon=True)
    t.start()
