from fastapi import APIRouter, Body
from app.db.session import SessionLocal
from app.db.models import Signal
from app.analytics.performance_engine import calculate_performance
from app.services.llm_router import ask_groq, ask_gemini
router = APIRouter()

@router.post("/assistant")
def assistant(question: str = Body(...)):
    db = SessionLocal()
    trades = db.query(Signal).filter(Signal.status.in_(["WIN","LOSS"])).order_by(Signal.candle_time.asc()).all()
    db.close()
    metrics = calculate_performance(trades)
    context = f"""
Total trades: {metrics.get('total_trades')}
Winrate: {metrics.get('winrate_percent')}%
Sharpe: {metrics.get('sharpe_ratio')}
Max DD: {metrics.get('max_drawdown_percent')}%
Profit Factor: {metrics.get('profit_factor')}
Expectancy: {metrics.get('expectancy_percent')}%
"""
    prompt = f"Bạn là trợ lý phân tích giao dịch quant.\n\nDữ liệu:\n{context}\n\nCâu hỏi: {question}"
    result = ask_gemini(prompt) or ask_groq(prompt)
    return {"answer": result or "AI không khả dụng."}
