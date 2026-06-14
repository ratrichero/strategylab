from sqlalchemy import text
from app.db.session import engine

def assert_schema_ok():
    with engine.connect() as conn:
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