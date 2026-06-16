from dotenv import load_dotenv
load_dotenv()

import math
from datetime import timezone

from app.db.session import SessionLocal
from app.db.models import PendingSignal
from app.services.config_service import get_runtime_config
from app.services.binance_service import get_klines_closed, get_all_prices, get_binance_server_time
from app.services.indicator_service import add_indicators_advanced


SYMBOLS = ["FETUSDT", "PUMPUSDT"]


def estimate_reprice_rounds(current_trigger, reference_trigger, reprice_pct, direction):
    """
    Ước lượng số vòng reprice lặp lại.
    LONG: trigger_new = trigger_old * (1 - p)
    SHORT: trigger_new = trigger_old * (1 + p)
    """
    try:
        if current_trigger <= 0 or reference_trigger <= 0:
            return None

        if direction == "LONG":
            factor = 1 - reprice_pct
        else:
            factor = 1 + reprice_pct

        if factor <= 0 or factor == 1:
            return None

        rounds = math.log(current_trigger / reference_trigger) / math.log(factor)
        return round(rounds, 2)
    except Exception:
        return None


def debug_symbol(symbol: str):
    cfg = get_runtime_config()
    server_now = get_binance_server_time()

    with SessionLocal() as db:
        p = (
            db.query(PendingSignal)
            .filter(PendingSignal.symbol == symbol)
            .order_by(PendingSignal.id.desc())
            .first()
        )

        if not p:
            print(f"\n❌ No pending found for {symbol}")
            return

        tf = p.timeframe
        df = get_klines_closed(symbol, interval=tf, limit=100, server_now=server_now)
        if df is None or df.empty:
            print(f"\n❌ No klines for {symbol}")
            return

        df = add_indicators_advanced(df)
        last = df.iloc[-1]

        current_price = get_all_prices().get(symbol)
        atr_val = float(last.get("atr") or 0)
        close_price = float(current_price or 0)

        pending_cfg = cfg.get("PENDING_CONFIG", {})
        risk_cfg = cfg.get("RISK_CONFIG", {})
        limit_cfg = cfg.get("LIMIT_ORDER_CONFIG", {})

        atr_mult_entry = pending_cfg.get("atr_entry_multiplier", {}).get(tf, 0.5)
        sl_pct = risk_cfg.get(tf, {}).get("sl_mult", 0.02)
        tp_pct = risk_cfg.get(tf, {}).get("tp_mult", 0.04)
        reprice_pct = limit_cfg.get("entry_reprice_pct", {}).get(tf, 0.0)

        # ── Trigger gốc theo scan-time formula ───────────────────
        if p.direction == "LONG":
            trigger_from_formula = close_price - atr_val * atr_mult_entry
            trigger_after_one_reprice = trigger_from_formula * (1 - reprice_pct)
            sl_from_formula = trigger_from_formula * (1 - sl_pct)
            tp_from_formula = trigger_from_formula * (1 + tp_pct)
        else:
            trigger_from_formula = close_price + atr_val * atr_mult_entry
            trigger_after_one_reprice = trigger_from_formula * (1 + reprice_pct)
            sl_from_formula = trigger_from_formula * (1 + sl_pct)
            tp_from_formula = trigger_from_formula * (1 - tp_pct)

        # Ước lượng số vòng reprice nếu đang compound
        rounds_vs_formula = estimate_reprice_rounds(
            current_trigger=float(p.trigger_price),
            reference_trigger=trigger_from_formula,
            reprice_pct=reprice_pct,
            direction=p.direction
        )

        rounds_vs_one_reprice = estimate_reprice_rounds(
            current_trigger=float(p.trigger_price),
            reference_trigger=trigger_after_one_reprice,
            reprice_pct=reprice_pct,
            direction=p.direction
        )

        print("\n" + "=" * 90)
        print(f"DEBUG PENDING: {symbol}")
        print("=" * 90)
        print(f"Pending ID            : {p.id}")
        print(f"Status                : {p.status}")
        print(f"Direction             : {p.direction}")
        print(f"Timeframe             : {p.timeframe}")
        print(f"Created At            : {p.created_at}")
        print(f"Exchange Order ID     : {p.exchange_order_id}")
        print(f"Exchange Status       : {p.exchange_status}")
        print("-" * 90)
        print(f"Current Price         : {close_price:.10f}")
        print(f"ATR Value             : {atr_val:.10f}")
        print(f"ATR Mult Entry        : {atr_mult_entry}")
        print(f"Reprice %             : {reprice_pct} ({reprice_pct*100:.2f}%)")
        print(f"SL %                  : {sl_pct} ({sl_pct*100:.2f}%)")
        print(f"TP %                  : {tp_pct} ({tp_pct*100:.2f}%)")
        print("-" * 90)
        print(f"Pending Trigger (DB)  : {float(p.trigger_price):.10f}")
        print(f"Pending SL (DB)       : {float(p.stop_loss):.10f}")
        print(f"Pending TP (DB)       : {float(p.take_profit):.10f}")
        print("-" * 90)
        print(f"Trigger from formula  : {trigger_from_formula:.10f}")
        print(f"Trigger after 1x repr : {trigger_after_one_reprice:.10f}")
        print(f"SL from formula       : {sl_from_formula:.10f}")
        print(f"TP from formula       : {tp_from_formula:.10f}")
        print("-" * 90)
        print(f"Estimated rounds vs formula      : {rounds_vs_formula}")
        print(f"Estimated rounds vs one reprice  : {rounds_vs_one_reprice}")
        print("=" * 90)


def main():
    for sym in SYMBOLS:
        debug_symbol(sym)


if __name__ == "__main__":
    main()