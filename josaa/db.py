from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from tenacity import retry, stop_after_delay, wait_fixed

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@retry(stop=stop_after_delay(60), wait=wait_fixed(2), reraise=True)
def wait_for_db() -> None:
    """Block until Postgres accepts connections (useful right after compose up)."""
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")


@contextmanager
def session_scope() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
