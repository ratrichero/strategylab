from fastapi import APIRouter
from app.services.config_service import get_runtime_config
router = APIRouter()

@router.post("/scan")
async def scan():
    import asyncio
    from app.services.signal_service import run_market_scan_single_tf
    cfg = get_runtime_config()
    tf  = cfg["TIMEFRAME"]
    result = await asyncio.to_thread(run_market_scan_single_tf, tf)
    return {"status": "ok", "timeframe": tf, "result": result}

@router.post("/scan-multi")
async def scan_multi():
    import asyncio
    from app.services.signal_service import run_market_scan_multi_tf
    result = await asyncio.to_thread(run_market_scan_multi_tf)
    return {"status": "ok", "result": result}
