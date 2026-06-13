from fastapi import APIRouter
from app.services.report_service import send_daily, send_weekly, send_monthly
router = APIRouter()

@router.post("/daily-report")  
def daily(): send_daily(); return {"status": "sent"}

@router.post("/weekly-report")
def weekly(): send_weekly(); return {"status": "sent"}

@router.post("/monthly-report")
def monthly(): send_monthly(); return {"status": "sent"}
