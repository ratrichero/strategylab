from app.services.live.reconciler import reconcile_all_exchange_symbols


def run_startup_live_recovery():
    print("\n🔍 LIVE startup reconcile...")
    reconcile_all_exchange_symbols()
    print("✅ LIVE startup reconcile done")
