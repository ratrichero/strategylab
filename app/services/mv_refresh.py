import asyncio

async def safe_refresh_loop():
    while True:
        await asyncio.sleep(300)  # 5 minutes
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
    with SessionLocal() as db:
        for mv in MVS:
            try:
                db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv}"))
                db.commit()
                #print(f"  Refreshed: {mv}")
            except Exception as e:
                print(f"  [MV] Skip {mv}: {e}")
                db.rollback()
