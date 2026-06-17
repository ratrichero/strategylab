from app.services.live.reconciler import reconcile_all_active_symbols


def run_startup_live_recovery():
    print("\n🔍 LIVE startup reconcile...")
    reconcile_all_active_symbols()
    print("✅ LIVE startup reconcile done")