"""Гвозди на «Динамика» ядро (S8/ADR-0020): readout критериев (дефолты→desired), применение
(desired + журнал audit, БЕЗ команды — D2), валидация (верхний кап stack_max обязателен), /self по
instance-токену, идемпотентность, RBAC (клиент 403), 404. Ядро=истина. Критерии — движко-скоуп
отбора монет из печки, не торговля. Нужен PG."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import issue_token
from app.db import get_sessionmaker
from app.main import create_app
from app.models import AuditLog, Command, DynamicSettings, Instance
from tests.crm_helpers import ensure_parents


@pytest.fixture
def clean(_migrated: None):
    with get_sessionmaker()() as s:
        for t in ("dynamic_settings", "commands"):
            s.execute(text(f"DELETE FROM {t}"))
        s.execute(text("DELETE FROM instances"))
        s.execute(text("DELETE FROM exchange_accounts"))
        s.execute(text("DELETE FROM clients"))
        s.commit()


def _login(c: TestClient, email: str, pw: str) -> dict:
    r = c.post("/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _mk_instance() -> uuid.UUID:
    with get_sessionmaker()() as s:
        cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        inst = Instance(
            client_id=cid, account_id=aid, bot_type_id=uuid.uuid4(),
            profile_id=uuid.uuid4(), status="running", health="ok",
        )
        s.add(inst)
        s.commit()
        return inst.id


def _valid_settings() -> dict:
    return {"min_score": 50, "stack_max": 5, "fresh_bars": 48}


def _instance_token(iid: uuid.UUID) -> str:
    with get_sessionmaker()() as s:
        raw = issue_token(s, principal="instance", subject_id=str(iid), scope="instance")
        s.commit()
        return raw


def test_dynamic_settings_defaults_then_apply(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = str(_mk_instance())

    # readout без строки → генные дефолты (== поведению Борса без настроек Оператора)
    r = c.get(f"/v1/instances/{iid}/dynamic/settings", headers=op)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"] == {"min_score": 0, "stack_max": 10, "fresh_bars": 0}
    assert body["defaults"]["stack_max"] == 10

    # применить критерии → desired сохранён (команды НЕТ — живое применение через re-fetch, D2)
    new = _valid_settings()
    p = c.put(f"/v1/instances/{iid}/dynamic/settings", headers=op, json=new)
    assert p.status_code == 200, p.text
    assert p.json()["settings"] == new

    # НИКАКОЙ команды dynamic_apply не поставлено (в отличие от дозора)
    with get_sessionmaker()() as s:
        assert s.query(Command).filter_by(instance_id=uuid.UUID(iid)).count() == 0

    # readout теперь отражает desired
    r2 = c.get(f"/v1/instances/{iid}/dynamic/settings", headers=op).json()
    assert r2["settings"] == {"min_score": 50, "stack_max": 5, "fresh_bars": 48}
    assert r2["updated_at"] is not None

    # аудит: одно изменение (что→что) в audit_log
    with get_sessionmaker()() as s:
        rows = s.query(AuditLog).filter_by(
            action="dynamic_settings_changed", entity=iid,
        ).all()
        assert len(rows) == 1
        assert rows[0].before["stack_max"] == 10 and rows[0].after["stack_max"] == 5


def test_dynamic_settings_validation(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = str(_mk_instance())

    # верхний кап stack_max ОБЯЗАТЕЛЕН: снять предохранитель через PUT нельзя (100000 не пройдёт)
    bad = {**_valid_settings(), "stack_max": 100_000}
    assert c.put(f"/v1/instances/{iid}/dynamic/settings", headers=op, json=bad).status_code == 422
    # stack_max=0 (нижняя граница ge=1) → 422
    bad2 = {**_valid_settings(), "stack_max": 0}
    assert c.put(f"/v1/instances/{iid}/dynamic/settings", headers=op, json=bad2).status_code == 422
    # min_score вне диапазона → 422
    bad3 = {**_valid_settings(), "min_score": 5000}
    assert c.put(f"/v1/instances/{iid}/dynamic/settings", headers=op, json=bad3).status_code == 422
    # fresh_bars отрицательный → 422 (0 допустим = без фильтра, но <0 нет)
    bad4 = {**_valid_settings(), "fresh_bars": -1}
    assert c.put(f"/v1/instances/{iid}/dynamic/settings", headers=op, json=bad4).status_code == 422


def test_dynamic_settings_idempotent(clean, users):
    """Дважды тот же PUT → тот же результат, один ряд (upsert)."""
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = str(_mk_instance())
    new = _valid_settings()
    c.put(f"/v1/instances/{iid}/dynamic/settings", headers=op, json=new)
    p2 = c.put(f"/v1/instances/{iid}/dynamic/settings", headers=op, json=new)
    assert p2.status_code == 200 and p2.json()["settings"] == new
    with get_sessionmaker()() as s:
        assert s.query(DynamicSettings).filter_by(instance_id=uuid.UUID(iid)).count() == 1


def test_dynamic_settings_self_instance_token(clean, users):
    """Картридж (instance-токен) читает СВОИ критерии через /dynamic/settings/self."""
    c = TestClient(create_app())
    iid = _mk_instance()
    op = _login(c, "op@mfc.local", "op-pass")
    ih = {"Authorization": f"Bearer {_instance_token(iid)}"}

    r = c.get("/v1/dynamic/settings/self", headers=ih)
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["stack_max"] == 10  # дефолты, пока не менялись

    c.put(f"/v1/instances/{iid}/dynamic/settings", headers=op, json=_valid_settings())
    r2 = c.get("/v1/dynamic/settings/self", headers=ih).json()
    assert r2["settings"] == {"min_score": 50, "stack_max": 5, "fresh_bars": 48}


def test_dynamic_settings_rbac_client_forbidden(clean, users):
    c = TestClient(create_app())
    cli = _login(c, "a@mfc.local", "a-pass")
    iid = str(_mk_instance())
    assert c.get(f"/v1/instances/{iid}/dynamic/settings", headers=cli).status_code == 403
    put = c.put(f"/v1/instances/{iid}/dynamic/settings", headers=cli, json=_valid_settings())
    assert put.status_code == 403


def test_dynamic_settings_unknown_instance_404(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    assert c.get(f"/v1/instances/{uuid.uuid4()}/dynamic/settings", headers=op).status_code == 404
