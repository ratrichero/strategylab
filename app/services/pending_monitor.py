"""
Pending Monitor — Dashboard status + debug helper.
Cung cấp thông tin realtime về pending worker.
"""
from app.core.time_utils import utc_now, ensure_utc, to_vn_str
from app.db.session import SessionLocal
from app.db.models import PendingSignal, Signal


def get_pending_status() -> dict:
    """
    Trả về full status của pending system.
    Dùng cho dashboard / API / debug.
    """
    with SessionLocal() as db:
        from sqlalchemy import text, func

        # ── Counts by status ─────────────────────────────
        counts = dict(
            db.query(PendingSignal.status, func.count())
            .group_by(PendingSignal.status)
            .all()
        )

        now = utc_now()

        # ── Expired WAIT ─────────────────────────────────
        expired_wait = db.query(PendingSignal).filter(
            PendingSignal.status   == "WAIT",
            PendingSignal.expire_at < now
        ).count()

        # ── Active WAIT ──────────────────────────────────
        active_wait = db.query(PendingSignal).filter(
            PendingSignal.status   == "WAIT",
            PendingSignal.expire_at >= now
        ).count()

        # ── Open signals ─────────────────────────────────
        open_signals = db.query(Signal).filter(Signal.status == "OPEN").count()

        # ── Worker heartbeat ─────────────────────────────
        hb_row = db.execute(text(
            "SELECT value, updated_at FROM app_config "
            "WHERE key = 'PENDING_WORKER_LAST_SEEN'"
        )).fetchone()

        worker_last_seen   = None
        worker_last_seen_vn = None
        worker_lag_seconds  = None
        worker_alive        = False

        if hb_row:
            worker_last_seen    = ensure_utc(hb_row[1])
            worker_last_seen_vn = to_vn_str(worker_last_seen)
            worker_lag_seconds  = (now - worker_last_seen).total_seconds()
            worker_alive        = worker_lag_seconds < 30   # threshold 30s

        # ── Sample pendings ──────────────────────────────
        from app.services.binance_service import get_all_prices
        price_map = get_all_prices() or {}

        samples = []
        recent = (
            db.query(PendingSignal)
            .filter(
                PendingSignal.status   == "WAIT",
                PendingSignal.expire_at >= now
            )
            .order_by(PendingSignal.created_at.desc())
            .limit(10)
            .all()
        )

        for p in recent:
            current = price_map.get(p.symbol)
            dist_pct = None
            should_fill = False

            if current:
                current = float(current)
                dist_pct = (current - p.trigger_price) / p.trigger_price * 100
                if p.direction == "LONG":
                    should_fill = current <= p.trigger_price
                else:
                    should_fill = current >= p.trigger_price

            samples.append({
                "id":          p.id,
                "symbol":      p.symbol,
                "direction":   p.direction,
                "timeframe":   p.timeframe,
                "strategy":    p.strategy_name,
                "trigger":     p.trigger_price,
                "current":     current,
                "dist_pct":    round(dist_pct, 4) if dist_pct is not None else None,
                "should_fill": should_fill,
                "expire_at":   to_vn_str(p.expire_at),
                "created_at":  to_vn_str(p.created_at),
            })

        return {
            "now_utc":             now.isoformat(),
            "now_vn":              to_vn_str(now),

            "counts": {
                "WAIT":      counts.get("WAIT",      0),
                "FILLED":    counts.get("FILLED",    0),
                "CANCELLED": counts.get("CANCELLED", 0),
                "REJECTED":  counts.get("REJECTED",  0),
            },

            "active_wait":   active_wait,
            "expired_wait":  expired_wait,
            "open_signals":  open_signals,

            "worker": {
                "alive":            worker_alive,
                "last_seen_utc":    worker_last_seen.isoformat() if worker_last_seen else None,
                "last_seen_vn":     worker_last_seen_vn,
                "lag_seconds":      round(worker_lag_seconds) if worker_lag_seconds else None,
            },

            "samples": samples,
        }


def print_pending_status():
    """Quick debug print — dùng trong terminal."""
    s = get_pending_status()

    print("\n" + "=" * 55)
    print(f"📋 PENDING STATUS — {s['now_vn']} GMT+7")
    print("=" * 55)

    w = s["worker"]
    alive_icon = "✅" if w["alive"] else "❌"
    print(f"Worker:  {alive_icon} last seen {w['lag_seconds']}s ago ({w['last_seen_vn']})")

    c = s["counts"]
    print(f"\nPending WAIT      : {c['WAIT']}")
    print(f"  Active (not exp): {s['active_wait']}")
    print(f"  Expired WAIT    : {s['expired_wait']}")
    print(f"Pending FILLED    : {c['FILLED']}")
    print(f"Pending CANCELLED : {c['CANCELLED']}")
    print(f"Pending REJECTED  : {c['REJECTED']}")
    print(f"\nOpen signals      : {s['open_signals']}")

    print(f"\n{'─'*55}")
    print(f"{'Symbol':<14} {'Dir':<6} {'Trigger':>10} {'Current':>10} {'Dist%':>7} {'Fill?'}")
    print(f"{'─'*55}")

    for p in s["samples"]:
        fill_icon = "🟢" if p["should_fill"] else "⬜"
        dist_str  = f"{p['dist_pct']:+.3f}%" if p["dist_pct"] is not None else "N/A"
        curr_str  = f"{p['current']:.6f}"    if p["current"]  is not None else "N/A"
        print(
            f"{p['symbol']:<14} {p['direction']:<6} "
            f"{p['trigger']:>10.6f} {curr_str:>10} "
            f"{dist_str:>7} {fill_icon}"
        )

    print("=" * 55 + "\n")