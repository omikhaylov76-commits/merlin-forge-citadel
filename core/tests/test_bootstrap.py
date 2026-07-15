"""Bootstrap оператора (#15): сев из env, идемпотентность, no-op без env. БД — как у core-тестов."""

import uuid

from sqlalchemy import select, text

from app.bootstrap import seed_demo_instance, seed_operator, seed_orchestrator
from app.db import get_sessionmaker
from app.models import ApiToken, Instance, User
from app.security import hash_token


def _clear() -> None:
    sm = get_sessionmaker()
    with sm() as s:
        s.execute(text("TRUNCATE users, api_tokens, instances CASCADE"))
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


def test_seed_operator_syncs_password(_migrated, monkeypatch):
    # Пароль из env — источник истины: повторный сев новым паролем ОБНОВЛЯЕТ хэш.
    _clear()
    monkeypatch.setenv("BOOTSTRAP_OPERATOR_EMAIL", "boot@mfc.local")
    monkeypatch.setenv("BOOTSTRAP_OPERATOR_PASSWORD", "first-pass")
    seed_operator()
    sm = get_sessionmaker()
    with sm() as s:
        h1 = s.execute(select(User).where(User.email == "boot@mfc.local")).scalar_one()
        h1 = h1.password_hash
    monkeypatch.setenv("BOOTSTRAP_OPERATOR_PASSWORD", "second-pass")
    seed_operator()
    with sm() as s:
        u = s.execute(select(User).where(User.email == "boot@mfc.local")).scalar_one()
        assert u.password_hash != h1  # хэш сменился → новый пароль применён
    assert _count("boot@mfc.local") == 1  # без дубля


def test_seed_orchestrator_creates(_migrated, monkeypatch):
    _clear()
    monkeypatch.setenv("BOOTSTRAP_ORCHESTRATOR_TOKEN", "orch-token-abc")
    seed_orchestrator()
    sm = get_sessionmaker()
    with sm() as s:
        t = s.execute(
            select(ApiToken).where(ApiToken.token_sha256 == hash_token("orch-token-abc"))
        ).scalar_one()
        assert t.principal == "orchestrator" and t.scope == "orchestrator"


def test_seed_orchestrator_idempotent(_migrated, monkeypatch):
    _clear()
    monkeypatch.setenv("BOOTSTRAP_ORCHESTRATOR_TOKEN", "orch-token-xyz")
    seed_orchestrator()
    seed_orchestrator()
    sm = get_sessionmaker()
    with sm() as s:
        rows = s.execute(
            select(ApiToken).where(ApiToken.principal == "orchestrator")
        ).all()
        assert len(rows) == 1


def test_seed_orchestrator_noop_without_env(_migrated, monkeypatch):
    _clear()
    monkeypatch.delenv("BOOTSTRAP_ORCHESTRATOR_TOKEN", raising=False)
    seed_orchestrator()
    sm = get_sessionmaker()
    with sm() as s:
        rows = s.execute(select(ApiToken).where(ApiToken.principal == "orchestrator")).all()
        assert len(rows) == 0


def test_seed_demo_instance(_migrated, monkeypatch):
    _clear()
    iid = "11111111-1111-1111-1111-111111111111"
    monkeypatch.setenv("BOOTSTRAP_INSTANCE_ID", iid)
    monkeypatch.setenv("BOOTSTRAP_INSTANCE_TOKEN", "demo-inst-token-xyz")
    seed_demo_instance()
    sm = get_sessionmaker()
    with sm() as s:
        assert s.get(Instance, uuid.UUID(iid)) is not None
        t = s.execute(
            select(ApiToken).where(ApiToken.token_sha256 == hash_token("demo-inst-token-xyz"))
        ).scalar_one()
        assert t.principal == "instance" and t.subject_id == iid  # токен аутентифицируем


def test_seed_demo_instance_idempotent(_migrated, monkeypatch):
    _clear()
    iid = "22222222-2222-2222-2222-222222222222"
    monkeypatch.setenv("BOOTSTRAP_INSTANCE_ID", iid)
    monkeypatch.setenv("BOOTSTRAP_INSTANCE_TOKEN", "tok2")
    seed_demo_instance()
    seed_demo_instance()
    sm = get_sessionmaker()
    with sm() as s:
        assert len(s.execute(select(Instance).where(Instance.id == uuid.UUID(iid))).all()) == 1
