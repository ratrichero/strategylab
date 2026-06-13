from fastapi import APIRouter
router = APIRouter()

@router.post("/retrain")
async def retrain(timeframe: str = None, force: bool = False):
    import asyncio
    from app.services.model_retrainer import retrain_model
    result = await asyncio.to_thread(retrain_model, timeframe, force)
    return result
