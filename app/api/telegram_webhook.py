from fastapi import APIRouter
router = APIRouter()
# Webhook endpoint — chỉ dùng nếu không dùng polling mode
# Hiện tại bot dùng polling → file này placeholder
@router.post("/telegram-webhook")
async def webhook():
    return {"status": "ok"}
