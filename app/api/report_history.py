from fastapi import APIRouter
from app.db.session import SessionLocal
from sqlalchemy import text
router = APIRouter()

@router.get("/report/{report_type}")
def get_report(report_type: str):
    db = SessionLocal()
    result = db.execute(text("SELECT content FROM reports WHERE report_type=:t ORDER BY created_at DESC LIMIT 1"),
                        {"t": report_type}).fetchone()
    db.close()
    return {"content": result[0] if result else "Chưa có báo cáo."}
