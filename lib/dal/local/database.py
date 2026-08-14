from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from lib.core.settings import load_settings


class Base(DeclarativeBase):
    pass


_settings = load_settings()


def _prepare_sqlite_path(database_url: str) -> None:
    if database_url.startswith("sqlite:///"):
        sqlite_path = database_url.replace("sqlite:///", "", 1)
        Path(sqlite_path).parent.mkdir(parents=True, exist_ok=True)


_prepare_sqlite_path(_settings.database_url)
engine = create_engine(_settings.database_url, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, class_=Session)


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
