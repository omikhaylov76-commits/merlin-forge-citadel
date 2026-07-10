"""Фикстуры тестов БД. Требуют живой Postgres в DATABASE_URL; без него тесты БД пропускаются
(liveness-тест /healthz идёт всегда, он БД не трогает)."""

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.db import get_sessionmaker

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
