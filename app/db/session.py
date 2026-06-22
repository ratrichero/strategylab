import os
from typing import Optional

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

import app.core.env_bootstrap


Base = declarative_base()

_engine: Optional[Engine] = None
_database_url: str = ""
_session_factory = None


def _attach_session_settings(db_engine: Engine) -> None:
    @event.listens_for(db_engine, "connect")
    def set_session_settings(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("SET timezone = 'UTC'")
        cursor.execute("SET search_path TO public")
        cursor.close()


def configure_database(database_url: str, *, dispose_existing: bool = False) -> Engine:
    """
    Bind the process-wide SQLAlchemy engine/session factory.

    SessionLocal is a stable proxy object below, so modules that imported
    `SessionLocal` before BOT bootstrap still resolve sessions against the
    latest configured engine.
    """
    global _engine, _database_url, _session_factory

    database_url = (database_url or "").strip()
    if not database_url:
        raise RuntimeError("DATABASE_URL is empty")

    if _engine is not None and _database_url == database_url:
        return _engine

    old_engine = _engine
    db_engine = create_engine(
        database_url,
        pool_pre_ping=True,
        connect_args={"options": "-c timezone=UTC -c search_path=public"},
    )
    _attach_session_settings(db_engine)

    _engine = db_engine
    _database_url = database_url
    _session_factory = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=db_engine,
    )

    if dispose_existing and old_engine is not None:
        old_engine.dispose()

    return db_engine


def get_engine() -> Engine:
    if _engine is None:
        raise RuntimeError("Database is not configured")
    return _engine


def get_database_url() -> str:
    return _database_url


class _SessionLocalProxy:
    def __call__(self, *args, **kwargs):
        if _session_factory is None:
            raise RuntimeError("Database is not configured")
        return _session_factory(*args, **kwargs)

    def configure(self, **kwargs):
        if _session_factory is None:
            raise RuntimeError("Database is not configured")
        return _session_factory.configure(**kwargs)


class _EngineProxy:
    def __getattr__(self, name):
        return getattr(get_engine(), name)

    def begin(self, *args, **kwargs):
        return get_engine().begin(*args, **kwargs)

    def connect(self, *args, **kwargs):
        return get_engine().connect(*args, **kwargs)

    def dispose(self, *args, **kwargs):
        return get_engine().dispose(*args, **kwargs)


SessionLocal = _SessionLocalProxy()
engine = _EngineProxy()


_env_database_url = os.getenv("DATABASE_URL", "").strip()
if _env_database_url:
    configure_database(_env_database_url)
