"""Доступ к Postgres. core — единственный владелец БД платформы (закон №3, ADR-0009).

Движок/сессии ленивы: импорт app.* не требует живой БД (тесты liveness идут без Postgres).
"""

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> "sessionmaker[Session]":
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = sessionmaker(bind=get_engine(), expire_on_commit=False)
    return _sessionmaker


def get_session() -> Iterator[Session]:
    # FastAPI-зависимость: короткая сессия на запрос. Long-poll её НЕ держит (SCL1).
    with get_sessionmaker()() as session:
        yield session
