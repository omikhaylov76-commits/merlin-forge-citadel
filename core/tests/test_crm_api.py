"""Гвозди на CRM-API оператора (MFC-F3-2): RBAC (только оператор), CRUD clients/exchange_accounts/
contracts, v1-гейт договора (profit_hwm/hurdle0/mgmt0) при создании/подписании, аудит write.
Нужен Postgres."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import get_sessionmaker
from app.main import create_app
from app.models import AuditLog


def _clean() -> None:
    with get_sessionmaker()() as s:
        s.execute(text(
            "TRUNCATE billing_periods, cashflows, contracts, instances, "
            "exchange_accounts, clients CASCADE"
        ))
        s.commit()


@pytest.fixture
def crm(users, _migrated: None):
    _clean()
    yield
    _clean()


def _login(c: TestClient, email: str, pw: str) -> dict:
    r = c.post("/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _op(c: TestClient) -> dict:
    return _login(c, "op@mfc.local", "op-pass")


def test_create_client_list_get(crm) -> None:
    c = TestClient(create_app())
    h = _op(c)
    r = c.post("/v1/clients", headers=h, json={"name": "Acme", "fee_pct_default": "0.2"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    assert cid in [x["id"] for x in c.get("/v1/clients", headers=h).json()]
    got = c.get(f"/v1/clients/{cid}", headers=h).json()
    assert got["name"] == "Acme" and got["fee_pct_default"] == "0.2000"


def test_rbac_client_role_forbidden(crm) -> None:
    c = TestClient(create_app())
    h = _login(c, "a@mfc.local", "a-pass")  # роль client
    assert c.post("/v1/clients", headers=h, json={"name": "X"}).status_code == 403


def test_rbac_unauthenticated_401(crm) -> None:
    c = TestClient(create_app())
    assert c.post("/v1/clients", json={"name": "X"}).status_code == 401


def test_create_account_ok_and_unknown_client_404(crm) -> None:
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    r = c.post("/v1/exchange-accounts", headers=h,
               json={"client_id": cid, "exchange": "bybit", "label": "demo"})
    assert r.status_code == 201, r.text
    accs = c.get(f"/v1/clients/{cid}/exchange-accounts", headers=h).json()
    assert len(accs) == 1 and accs[0]["exchange"] == "bybit"
    bad = c.post("/v1/exchange-accounts", headers=h,
                 json={"client_id": str(uuid.uuid4()), "exchange": "okx"})
    assert bad.status_code == 404


def test_create_contract_defaults(crm) -> None:
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    r = c.post("/v1/contracts", headers=h, json={"client_id": cid})
    assert r.status_code == 201, r.text
    kid = r.json()["id"]
    got = c.get(f"/v1/contracts/{kid}", headers=h).json()
    assert got["payment_model"] == "profit_hwm" and got["fee_pct"] == "0.1500"
    assert got["capital"] == "1000.00" and got["status"] == "draft"


def test_contract_v1_guard_rejects_unsupported(crm) -> None:
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    # payment_model ≠ profit_hwm → 422
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "payment_model": "subscription"}).status_code == 422
    # hurdle_pct ≠ 0 → 422
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "hurdle_pct": "0.01"}).status_code == 422
    # mgmt_fee_pct ≠ 0 → 422
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "mgmt_fee_pct": "0.02"}).status_code == 422


def test_contract_field_validation(crm) -> None:
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    # capital ниже пола 500 → 422 (Pydantic)
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "capital": "100"}).status_code == 422
    # fee_pct ≥ 1 → 422
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "fee_pct": "1.5"}).status_code == 422


def test_contract_unknown_client_404(crm) -> None:
    c = TestClient(create_app())
    h = _op(c)
    r = c.post("/v1/contracts", headers=h, json={"client_id": str(uuid.uuid4())})
    assert r.status_code == 404


def test_contract_sign_status(crm) -> None:
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    kid = c.post("/v1/contracts", headers=h, json={"client_id": cid}).json()["id"]
    r = c.patch(f"/v1/contracts/{kid}/status", headers=h, json={"status": "signed"})
    assert r.status_code == 200 and r.json()["status"] == "signed"


def test_audit_written_on_client_create(crm) -> None:
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    with get_sessionmaker()() as s:
        row = s.execute(
            select(AuditLog).where(AuditLog.action == "client_created", AuditLog.entity == cid)
        ).scalar_one()
        assert row.after["name"] == "Acme"
