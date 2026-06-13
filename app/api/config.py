from fastapi import APIRouter, Body, HTTPException
from app.services.config_service import get_runtime_config, update_runtime_config
router = APIRouter()

@router.get("/config")
def get_config(): return get_runtime_config()

@router.post("/config")
def save_config(payload: dict = Body(...)):
    try: update_runtime_config(payload); return {"status": "✅ saved"}
    except Exception as e: raise HTTPException(status_code=400, detail=str(e))
