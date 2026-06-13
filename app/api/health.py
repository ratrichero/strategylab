from fastapi import APIRouter
router = APIRouter()

@router.get("/health")
async def health():
    try:
        from app.db.session import SessionLocal
        from sqlalchemy import text
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
