"""Готовность ядра: БД доступна И миграции накатаны до head.

Отдельно от liveness (/healthz): liveness = «процесс жив», readiness = «можно принимать
трафик» (БД на месте, схема актуальна). Railway/uptime-пинг бьёт по обоим.
"""

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text

from app.db import get_engine

_CORE = Path(__file__).resolve().parents[1]


def _head_revision() -> str | None:
    cfg = Config()
    cfg.set_main_option("script_location", str(_CORE / "alembic"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def is_ready() -> bool:
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
            current = MigrationContext.configure(conn).get_current_revision()
        return current is not None and current == _head_revision()
    except Exception:
        # Любой сбой (БД недоступна, миграции не на head) = не готов; деталь — в логи, не в ответ.
        return False
