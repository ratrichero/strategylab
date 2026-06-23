from app.services.live.reconciler import reconcile_all_exchange_symbols
from app.core.trading_mode import get_current_mode


def run_startup_live_recovery():
    mode_label = get_current_mode().value
    print(f"\n🔍 {mode_label} startup reconcile...")
    reconcile_all_exchange_symbols()
    print(f"✅ {mode_label} startup reconcile done")
