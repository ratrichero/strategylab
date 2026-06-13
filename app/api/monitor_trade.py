from fastapi import APIRouter
router = APIRouter()

@router.post("/monitor")
async def trigger_monitor():
    import asyncio
    from app.services.trade_monitor import monitor_open_trades
    await asyncio.to_thread(monitor_open_trades)
    return {"status": "ok"}
