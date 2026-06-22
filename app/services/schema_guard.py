from sqlalchemy import text
from app.db.session import get_engine

def assert_schema_ok():
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(text("""
            select count(*)
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'pending_signals'
              and column_name = 'engine_version'
        """)).scalar()

        if row == 0:
            raise RuntimeError(
                "Schema mismatch: public.pending_signals.engine_version missing")

        conn.execute(text("""
            ALTER TABLE public.pending_signals
            ADD COLUMN IF NOT EXISTS client_order_id varchar
        """))
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS idx_pending_client_order_id
            ON public.pending_signals (client_order_id)
        """))
