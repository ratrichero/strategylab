from fastapi import APIRouter
from app.db.session import SessionLocal
from app.db.models import Signal
from app.analytics.performance_engine import calculate_performance
router = APIRouter()

@router.get("/performance")
def performance():
    db = SessionLocal()
    trades = db.query(Signal).filter(Signal.status.in_(["WIN","LOSS"])).order_by(Signal.candle_time.asc()).all()
    db.close()
    overall = calculate_performance(trades)
    patterns = {}
    for t in trades: patterns.setdefault(t.pattern, []).append(t)
    regimes = {}
    for t in trades: regimes.setdefault(t.regime, []).append(t)
    return {
        "overall": overall,
        "by_pattern": {p: calculate_performance(ts) for p, ts in patterns.items()},
        "by_regime":  {r: calculate_performance(ts) for r, ts in regimes.items()},
    }
