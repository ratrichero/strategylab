# check_pending.py
import os
from dotenv import load_dotenv
load_dotenv()

from app.db.session import SessionLocal
from app.db.models import PendingSignal, Signal
from app.services.config_service import get_runtime_config
from datetime import datetime

db = SessionLocal()

# 1. Pending WAIT hiện tại
wait_count = db.query(PendingSignal).filter(PendingSignal.status == "WAIT").count()
print(f"\nPending WAIT: {wait_count}")

# 2. Pending đã FILLED
filled = db.query(PendingSignal).filter(PendingSignal.status == "FILLED").count()
print(f"Pending FILLED: {filled}")

# 3. Pending CANCELLED
cancelled = db.query(PendingSignal).filter(PendingSignal.status == "CANCELLED").count()
print(f"Pending CANCELLED: {cancelled}")

# 4. Pending REJECTED
rejected = db.query(PendingSignal).filter(PendingSignal.status == "REJECTED").count()
print(f"Pending REJECTED: {rejected}")
if rejected > 0:
    reasons = db.query(PendingSignal.rejection_reason).filter(
        PendingSignal.status == "REJECTED"
    ).distinct().all()
    print(f"  Rejection reasons: {[r[0] for r in reasons]}")

# 5. Open signals
open_count = db.query(Signal).filter(Signal.status == "OPEN").count()
print(f"\nOpen signals: {open_count}")

# 6. Config
cfg = get_runtime_config(force_reload=True)
print(f"\nMAX_OPEN_TRADES: {cfg.get('MAX_OPEN_TRADES', 'NOT SET')}")
print(f"ENABLE_MONITOR: {cfg.get('ENABLE_MONITOR')}")
print(f"TRADING_MODE: {cfg.get('TRADING_MODE')}")

# 7. OTF config
otf = cfg.get("OPEN_TRADE_FILTER", {})
print(f"\nOTF enabled: {otf.get('enabled')}")
print(f"OTF config: {otf}")

# 8. Prefill config
pf = cfg.get("PREFILL_CONFIG", {})
print(f"\nPrefill enabled: {pf.get('enabled')}")

# 9. Sample pending — check trigger vs current price
from app.services.binance_service import get_all_prices
prices = get_all_prices()

pendings = db.query(PendingSignal).filter(
    PendingSignal.status == "WAIT"
).order_by(PendingSignal.created_at.desc()).limit(5).all()

print(f"\n--- Sample Pendings ---")
for p in pendings:
    current = prices.get(p.symbol, 0)
    should_fill = False
    if p.direction == "LONG" and current <= p.trigger_price:
        should_fill = True
    if p.direction == "SHORT" and current >= p.trigger_price:
        should_fill = True

    print(f"  {p.symbol} {p.direction} | trigger={p.trigger_price:.4f} | current={current:.4f} | should_fill={should_fill} | created={p.created_at}")

# 10. Check expired
now = datetime.utcnow()
expired_count = db.query(PendingSignal).filter(
    PendingSignal.status == "WAIT",
    PendingSignal.expire_at < now
).count()
print(f"\nExpired but still WAIT: {expired_count}")

db.close()