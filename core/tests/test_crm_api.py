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


def test_contract_v1_guard_rejects_quarter_and_no_hwm(crm) -> None:
    # C1/M1: billing_period=quarter и high_water_mark=false не поддержаны v1 → 422
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "billing_period": "quarter"}).status_code == 422
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "high_water_mark": False}).status_code == 422


def test_one_signed_contract_per_client(crm) -> None:
    # M2: второй подписанный договор одному клиенту → 409
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    k1 = c.post("/v1/contracts", headers=h, json={"client_id": cid}).json()["id"]
    k2 = c.post("/v1/contracts", headers=h, json={"client_id": cid}).json()["id"]
    r1 = c.patch(f"/v1/contracts/{k1}/status", headers=h, json={"status": "signed"})
    assert r1.status_code == 200
    r2 = c.patch(f"/v1/contracts/{k2}/status", headers=h, json={"status": "signed"})
    assert r2.status_code == 409  # второй signed отвергнут
    # прямое создание второго signed — тоже 409
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "status": "signed"}).status_code == 409


def test_contract_status_transition_guard(crm) -> None:
    # M5: signed→draft запрещён (сначала suspend)
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    kid = c.post("/v1/contracts", headers=h, json={"client_id": cid}).json()["id"]
    c.patch(f"/v1/contracts/{kid}/status", headers=h, json={"status": "signed"})
    assert c.patch(f"/v1/contracts/{kid}/status", headers=h,
                   json={"status": "draft"}).status_code == 409


def test_rbac_on_contracts(crm) -> None:
    c = TestClient(create_app())
    cid_op = _op(c)
    cid = c.post("/v1/clients", headers=cid_op, json={"name": "Acme"}).json()["id"]
    hcl = _login(c, "a@mfc.local", "a-pass")  # роль client
    assert c.post("/v1/contracts", headers=hcl, json={"client_id": cid}).status_code == 403
    assert c.post("/v1/contracts", json={"client_id": cid}).status_code == 401  # без токена


def test_sign_inactive_client_rejected(crm) -> None:
    # NEW-1: draft-договор + деактивация клиента → подписание отвергается (409)
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    kid = c.post("/v1/contracts", headers=h, json={"client_id": cid}).json()["id"]
    with get_sessionmaker()() as s:  # эндпоинта деактивации пока нет — правим напрямую
        s.execute(text("UPDATE clients SET is_active=false WHERE id=:i"), {"i": cid})
        s.commit()
    r = c.patch(f"/v1/contracts/{kid}/status", headers=h, json={"status": "signed"})
    assert r.status_code == 409


def test_rbac_patch_status(crm) -> None:
    c = TestClient(create_app())
    h = _op(c)
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    kid = c.post("/v1/contracts", headers=h, json={"client_id": cid}).json()["id"]
    hcl = _login(c, "a@mfc.local", "a-pass")  # роль client
    body = {"status": "signed"}
    assert c.patch(f"/v1/contracts/{kid}/status", headers=hcl, json=body).status_code == 403
    assert c.patch(f"/v1/contracts/{kid}/status", json=body).status_code == 401  # без токена


def test_contract_bad_uuid_and_overflow_422(crm) -> None:
    # M3/M4: битый UUID и capital-overflow ловятся Pydantic → 422 (не 500)
    c = TestClient(create_app())
    h = _op(c)
    assert c.post("/v1/contracts", headers=h, json={"client_id": "garbage"}).status_code == 422
    cid = c.post("/v1/clients", headers=h, json={"name": "Acme"}).json()["id"]
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "capital": "1e20"}).status_code == 422
    # N1: fee_pct с 5 знаками → 422 (не тихое округление тарифа)
    assert c.post("/v1/contracts", headers=h,
                  json={"client_id": cid, "fee_pct": "0.15007"}).status_code == 422


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
