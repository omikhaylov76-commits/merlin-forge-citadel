"""Bootstrap оператора (#15): сев из env, идемпотентность, no-op без env. БД — как у core-тестов."""

from sqlalchemy import select, text

from app.bootstrap import seed_operator
from app.db import get_sessionmaker
from app.models import User


def _clear() -> None:
    sm = get_sessionmaker()
    with sm() as s:
        s.execute(text("TRUNCATE users, api_tokens CASCADE"))
        s.commit()


def _count(email: str) -> int:
    sm = get_sessionmaker()
    with sm() as s:
        return len(s.execute(select(User).where(User.email == email)).all())


def test_seed_operator_creates(_migrated, monkeypatch):
    _clear()
    monkeypatch.setenv("BOOTSTRAP_OPERATOR_EMAIL", "boot@mfc.local")
    monkeypatch.setenv("BOOTSTRAP_OPERATOR_PASSWORD", "boot-pass-123")
    seed_operator()
    sm = get_sessionmaker()
    with sm() as s:
        u = s.execute(select(User).where(User.email == "boot@mfc.local")).scalar_one()
        assert u.role == "operator" and u.password_hash  # хэш, не пароль


def test_seed_operator_idempotent(_migrated, monkeypatch):
    _clear()
    monkeypatch.setenv("BOOTSTRAP_OPERATOR_EMAIL", "boot@mfc.local")
    monkeypatch.setenv("BOOTSTRAP_OPERATOR_PASSWORD", "boot-pass-123")
    seed_operator()
    seed_operator()
    assert _count("boot@mfc.local") == 1


def test_seed_operator_noop_without_env(_migrated, monkeypatch):
    _clear()
    monkeypatch.delenv("BOOTSTRAP_OPERATOR_EMAIL", raising=False)
    monkeypatch.delenv("BOOTSTRAP_OPERATOR_PASSWORD", raising=False)
    seed_operator()
    sm = get_sessionmaker()
    with sm() as s:
        assert len(s.execute(select(User)).all()) == 0
