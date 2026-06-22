import json
from typing import Any, Dict, Optional, Tuple

from sqlalchemy import text

from app.core.time_utils import ensure_utc
from app.db.models import Signal, TradeOutcomeAnalytics
from app.db.session import SessionLocal


UNKNOWN_REASON = "EXCHANGE_CLOSE_UNKNOWN"


def _dt_to_ms(value) -> Optional[int]:
    if not value:
        return None
    try:
        return int(ensure_utc(value).timestamp() * 1000)
    except Exception:
        return None


def _positive_float(*values) -> Optional[float]:
    for value in values:
        try:
            out = float(value)
            if out > 0:
                return out
        except Exception:
            continue
    return None


def _raw_order(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = {}
    if not isinstance(raw, dict):
        return {}
    order = raw.get("o")
    return order if isinstance(order, dict) else {}


def _classify_event(row, signal: Signal) -> Optional[Tuple[str, float, Dict[str, Any]]]:
    order = _raw_order(row.get("raw"))
    client_order_id = str(row.get("client_order_id") or order.get("c") or "").upper()
    order_type = str(
        row.get("order_type")
        or order.get("o")
        or order.get("ot")
        or ""
    ).upper()

    reason = None
    fallback_price = None
    if client_order_id.startswith("QRL_TP_") or "TAKE_PROFIT" in order_type:
        reason = "TP"
        fallback_price = signal.take_profit
    elif client_order_id.startswith("QRL_SL_") or "STOP" in order_type:
        reason = "SL"
        fallback_price = signal.stop_loss

    if not reason:
        return None

    price = _positive_float(
        row.get("avg_price"),
        row.get("last_filled_price"),
        order.get("ap"),
        order.get("L"),
        fallback_price,
    )
    if not price:
        return None

    evidence = {
        "event_time_ms": row.get("event_time_ms"),
        "client_order_id": client_order_id,
        "order_type": order_type,
    }
    return reason, float(price), evidence


def _find_stream_close_evidence(db, signal: Signal) -> Optional[Tuple[str, float, Dict[str, Any]]]:
    start_ms = _dt_to_ms(signal.created_at) or _dt_to_ms(signal.candle_time)
    if not start_ms:
        return None

    end_ms = _dt_to_ms(signal.exit_time)
    end_clause = ""
    params = {
        "symbol": signal.symbol,
        "start_ms": start_ms,
    }
    if end_ms:
        end_clause = "AND event_time_ms <= :end_ms"
        params["end_ms"] = end_ms + 30 * 60 * 1000

    rows = db.execute(text(f"""
        SELECT client_order_id, order_type, avg_price, last_filled_price, raw, event_time_ms
        FROM exchange_order_events
        WHERE symbol = :symbol
          AND event_type = 'ORDER_TRADE_UPDATE'
          AND order_status = 'FILLED'
          AND execution_type = 'TRADE'
          AND event_time_ms >= :start_ms
          {end_clause}
          AND (
            close_position IS TRUE
            OR reduce_only IS TRUE
            OR order_type IN ('STOP_MARKET', 'TAKE_PROFIT_MARKET')
          )
        ORDER BY event_time_ms DESC
        LIMIT 50
    """), params).mappings().all()

    for row in rows:
        classified = _classify_event(row, signal)
        if classified:
            return classified
    return None


def _result_percent(signal: Signal, exit_price: float) -> float:
    entry = _positive_float(signal.entry_price)
    if not entry:
        return 0.0
    if str(signal.direction).upper() == "LONG":
        return ((exit_price - entry) / entry) * 100
    return ((entry - exit_price) / entry) * 100


def _rr_realized(signal: Signal, result_pct: float) -> Optional[float]:
    entry = _positive_float(signal.entry_price)
    stop_loss = _positive_float(signal.stop_loss)
    if not entry or not stop_loss:
        return None
    risk_pct = abs((stop_loss - entry) / entry * 100)
    if risk_pct <= 0:
        return None
    return round(result_pct / risk_pct, 4)


def backfill_exchange_close_unknown(limit: int = 500, dry_run: bool = True) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 500), 2000))
    scanned = matched = updated = skipped = 0
    samples = []

    with SessionLocal() as db:
        signals = db.query(Signal).filter(
            Signal.exit_reason == UNKNOWN_REASON,
            Signal.status.in_(["WIN", "LOSS", "MANUAL"]),
        ).order_by(Signal.exit_time.desc().nullslast()).limit(limit).all()

        for signal in signals:
            scanned += 1
            try:
                evidence = _find_stream_close_evidence(db, signal)
            except Exception as e:
                skipped += 1
                samples.append({
                    "signal_id": signal.id,
                    "symbol": signal.symbol,
                    "error": f"{type(e).__name__}: {e}",
                })
                continue

            if not evidence:
                skipped += 1
                continue

            reason, exit_price, evidence_meta = evidence
            matched += 1
            result_pct = _result_percent(signal, exit_price)
            rr_realized = _rr_realized(signal, result_pct)
            new_status = "WIN" if result_pct > 0 else "LOSS"

            samples.append({
                "signal_id": signal.id,
                "symbol": signal.symbol,
                "reason": reason,
                "exit_price": exit_price,
                "result_percent": round(result_pct, 6),
                **evidence_meta,
            })

            if dry_run:
                continue

            signal.exit_reason = reason
            signal.exit_price = exit_price
            signal.result_percent = result_pct
            signal.status = new_status

            outcome = db.query(TradeOutcomeAnalytics).filter(
                TradeOutcomeAnalytics.signal_id == signal.id
            ).first()
            if outcome:
                outcome.exit_reason = reason
                outcome.exit_price = exit_price
                outcome.trade_return = result_pct
                outcome.label = 1 if result_pct > 0 else 0
                if rr_realized is not None:
                    outcome.rr_realized = rr_realized

            updated += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()

    return {
        "ok": True,
        "dry_run": dry_run,
        "limit": limit,
        "scanned": scanned,
        "matched": matched,
        "updated": updated,
        "skipped": skipped,
        "samples": samples[:20],
    }
