"""Гвозди на продюсеры jobs (MFC-004): POST /v1/instances (+deploy-job) и /teardown.
Оператор-only, ≤1 живой/счёт, идемпотентность teardown, producer→lease сквозняк. Нужен Postgres."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import issue_token
from app.db import get_sessionmaker
from app.main import create_app
from app.models import Instance, Job


@pytest.fixture
def clean(_migrated: None):
    with get_sessionmaker()() as s:
        s.execute(text("DELETE FROM jobs"))
        s.execute(text("DELETE FROM instances"))
        s.commit()


def _login(c: TestClient, email: str, pw: str) -> dict:
    r = c.post("/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _body(account_id: str | None = None) -> dict:
    return {
        "client_id": str(uuid.uuid4()),
        "account_id": account_id or str(uuid.uuid4()),
        "bot_type_id": str(uuid.uuid4()),
        "profile_id": str(uuid.uuid4()),
        "image": "paper-bot:v0",
    }


def test_create_instance_enqueues_deploy(users, clean):
    c = TestClient(create_app())
    r = c.post("/v1/instances", headers=_login(c, "op@mfc.local", "op-pass"), json=_body())
    assert r.status_code == 201, r.text
    data = r.json()
    with get_sessionmaker()() as s:
        inst = s.get(Instance, uuid.UUID(data["id"]))
        assert inst.status == "pending"
        job = s.get(Job, uuid.UUID(data["deploy_job_id"]))
        assert job.kind == "deploy" and job.status == "pending"
        assert job.payload["name"] == f"mfc-inst-{data['id']}"        # имя детерминировано от id
        env = job.payload["env"]
        assert env["MF_INSTANCE_ID"] == data["id"]                    # Контракт Бота v0 (MF_*)
        assert env["MF_INSTANCE_TOKEN"] and env["MF_CORE_URL"]  # токен инстанса + URL ядра


def test_create_instance_requires_operator(users, clean):
    c = TestClient(create_app())
    r = c.post("/v1/instances", headers=_login(c, "a@mfc.local", "a-pass"), json=_body())
    assert r.status_code == 403  # клиент не заводит инстансы


def test_create_instance_conflict_on_busy_account(users, clean):
    c = TestClient(create_app())
    h = _login(c, "op@mfc.local", "op-pass")
    acct = str(uuid.uuid4())
    assert c.post("/v1/instances", headers=h, json=_body(acct)).status_code == 201
    # второй живой инстанс на тот же счёт — 409 (партиал-уникальность instances, OPS3)
    assert c.post("/v1/instances", headers=h, json=_body(acct)).status_code == 409


def test_teardown_enqueues_job(users, clean):
    with get_sessionmaker()() as s:
        inst = Instance(
            client_id=uuid.uuid4(), account_id=uuid.uuid4(), bot_type_id=uuid.uuid4(),
            profile_id=uuid.uuid4(), status="running", health="ok", infra_ref="railway:p:s",
        )
        s.add(inst)
        s.commit()
        iid = inst.id
    c = TestClient(create_app())
    r = c.post(f"/v1/instances/{iid}/teardown", headers=_login(c, "op@mfc.local", "op-pass"))
    assert r.status_code == 202, r.text
    with get_sessionmaker()() as s:
        job = s.get(Job, uuid.UUID(r.json()["teardown_job_id"]))
        assert job.kind == "teardown" and job.payload["infra_ref"] == "railway:p:s"


def test_teardown_404_for_unknown(users, clean):
    c = TestClient(create_app())
    h = _login(c, "op@mfc.local", "op-pass")
    assert c.post(f"/v1/instances/{uuid.uuid4()}/teardown", headers=h).status_code == 404


def test_teardown_rejects_pending(users, clean):
    # инстанс в pending → deploy в полёте, сворачивать нельзя (409)
    c = TestClient(create_app())
    h = _login(c, "op@mfc.local", "op-pass")
    iid = c.post("/v1/instances", headers=h, json=_body()).json()["id"]
    assert c.post(f"/v1/instances/{iid}/teardown", headers=h).status_code == 409


def test_teardown_idempotent_rejects_double(users, clean):
    with get_sessionmaker()() as s:
        inst = Instance(
            client_id=uuid.uuid4(), account_id=uuid.uuid4(), bot_type_id=uuid.uuid4(),
            profile_id=uuid.uuid4(), status="running", health="ok",
        )
        s.add(inst)
        s.commit()
        iid = inst.id
    c = TestClient(create_app())
    h = _login(c, "op@mfc.local", "op-pass")
    assert c.post(f"/v1/instances/{iid}/teardown", headers=h).status_code == 202
    assert c.post(f"/v1/instances/{iid}/teardown", headers=h).status_code == 409  # уже в очереди


def test_producer_to_lease_end_to_end(users, clean):
    # оператор создаёт инстанс → оркестратор арендует его deploy-job
    c = TestClient(create_app())
    op_h = _login(c, "op@mfc.local", "op-pass")
    created = c.post("/v1/instances", headers=op_h, json=_body()).json()
    with get_sessionmaker()() as s:
        raw = issue_token(s, principal="orchestrator", subject_id="orch-1", scope="orchestrator")
        s.commit()
    r = c.get("/v1/internal/jobs/next?wait=0", headers={"Authorization": f"Bearer {raw}"})
    assert r.status_code == 200, r.text
    assert r.json()["id"] == created["deploy_job_id"]  # арендован именно тот deploy-job
    with get_sessionmaker()() as s:  # инстанс перешёл pending→deploying на аренде
        assert s.get(Instance, uuid.UUID(created["id"])).status == "deploying"
