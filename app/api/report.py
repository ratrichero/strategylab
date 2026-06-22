from fastapi import APIRouter
from app.services.report_service import send_daily, send_weekly, send_monthly
from app.services.trading_agent_service import (
    send_agent_daily, send_agent_weekly, send_agent_monthly, send_agent_live,
)

router = APIRouter()

@router.post("/daily-report")
def daily(): send_daily(); return {"status": "sent"}

@router.post("/weekly-report")
def weekly(): send_weekly(); return {"status": "sent"}

@router.post("/monthly-report")
def monthly(): send_monthly(); return {"status": "sent"}

@router.post("/agent-daily-report")
def agent_daily(): send_agent_daily(); return {"status": "sent"}

@router.post("/agent-weekly-report")
def agent_weekly(): send_agent_weekly(); return {"status": "sent"}

@router.post("/agent-monthly-report")
def agent_monthly(): send_agent_monthly(); return {"status": "sent"}

@router.post("/agent-live-report")
def agent_live(): send_agent_live(); return {"status": "sent"}
