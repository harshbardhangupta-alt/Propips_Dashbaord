from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None


def _sqlite_pragmas(dbapi_conn, _record):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=10000")
    cur.close()


def init_engine(url: str | None = None) -> Engine:
    global _engine, _SessionLocal
    url = url or get_settings().database_url
    kwargs = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
    _engine = create_engine(url, future=True, **kwargs)
    if url.startswith("sqlite"):
        event.listen(_engine, "connect", _sqlite_pragmas)
    _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        init_engine()
    return _engine  # type: ignore[return-value]


def SessionLocal() -> Session:
    if _SessionLocal is None:
        init_engine()
    return _SessionLocal()  # type: ignore[misc]


@contextmanager
def session_scope() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_db() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
