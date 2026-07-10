"""Фикстуры тестов БД. Требуют живой Postgres в DATABASE_URL; без него тесты БД пропускаются
(liveness-тест /healthz идёт всегда, он БД не трогает)."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_sessionmaker
from app.models import User
from app.security import hash_password

_CORE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def _migrated() -> None:
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL не задан — тест БД пропущен")
    cfg = Config(str(_CORE / "alembic.ini"))
    cfg.set_main_option("script_location", str(_CORE / "alembic"))
    command.downgrade(cfg, "base")  # чистое дерево перед прогоном
    command.upgrade(cfg, "head")
    yield


@pytest.fixture
def session(_migrated: None) -> Session:
    with get_sessionmaker()() as s:
        yield s


@pytest.fixture
def users(session: Session) -> dict[str, User]:
    # Чистое состояние на каждый тест (audit_log не трогаем — он append-only).
    session.execute(text("TRUNCATE users, api_tokens"))
    people = {
        "op": User(email="op@mfc.local", role="operator", password_hash=hash_password("op-pass")),
        "a": User(email="a@mfc.local", role="client", password_hash=hash_password("a-pass")),
        "b": User(email="b@mfc.local", role="client", password_hash=hash_password("b-pass")),
    }
    session.add_all(people.values())
    session.commit()
    return people
