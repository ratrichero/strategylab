"""API endpoint cho pending status dashboard."""
from fastapi import APIRouter
from app.services.pending_monitor import get_pending_status

router = APIRouter(prefix="/api", tags=["pending"])


@router.get("/pending-status")
def pending_status():
    """
    Full pending system status.
    Dùng cho dashboard debug panel.
    """
    return get_pending_status()


@router.get("/pending-signals")
def pending_signals(
    status: str = "WAIT",
    limit:  int = 50,
):
    """Paginated pending list với filter."""
    from app.db.session import SessionLocal
    from app.db.models import PendingSignal
    from app.core.time_utils import to_vn_str, utc_now

    with SessionLocal() as db:
        q = db.query(PendingSignal)
        if status != "ALL":
            q = q.filter(PendingSignal.status == status)
        items = q.order_by(PendingSignal.created_at.desc()).limit(limit).all()

        return [
            {
                "id":            p.id,
                "symbol":        p.symbol,
                "timeframe":     p.timeframe,
                "direction":     p.direction,
                "strategy_name": p.strategy_name,
                "pattern":       p.pattern,
                "signal_score":  p.signal_score,
                "trigger_price": p.trigger_price,
                "stop_loss":     p.stop_loss,
                "take_profit":   p.take_profit,
                "rr":            p.rr,
                "status":        p.status,
                "regime":        p.regime,
                "ml_prob":       p.ml_prob,
                "expire_at":     to_vn_str(p.expire_at),
                "filled_at":     to_vn_str(p.filled_at),
                "created_at":    to_vn_str(p.created_at),
                "rejection_reason": p.rejection_reason,
            }
            for p in items
        ]