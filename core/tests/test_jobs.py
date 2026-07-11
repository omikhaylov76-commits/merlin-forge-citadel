"""Гвозди на jobs-транспорт шва S3 (MFC-004, ADR-0009): аренда, fencing, attempts, компенсация,
release, реклейм, партиал-уникальность deploy, CHECK kind + HTTP round-trip и авторизация.
Нужен Postgres (SKIP LOCKED, партиал-индексы). Идемпотентность/fencing — закон №8."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.auth import issue_token
from app.db import get_sessionmaker
from app.jobs import LeaseConflict, ack, lease_next
from app.main import create_app
from app.models import Instance, Job


@pytest.fixture
def sm(_migrated: None):
    m = get_sessionmaker()
    with m() as s:  # дети instances → instances (FK-порядок); audit_log append-only не трогаем
        for t in ("commands", "jobs", "equity_points", "trades", "events"):
            s.execute(text(f"DELETE FROM {t}"))
        s.execute(text("DELETE FROM instances"))
        s.commit()
    return m


def _mk_instance(session, status="pending", infra_ref=None) -> Instance:
    inst = Instance(
        client_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        bot_type_id=uuid.uuid4(),
        profile_id=uuid.uuid4(),
        status=status,
        health="ok",
        infra_ref=infra_ref,
    )
    session.add(inst)
    session.flush()
    return inst


def _mk_job(session, instance_id, kind="deploy", status="pending", payload=None) -> Job:
    job = Job(kind=kind, instance_id=instance_id, status=status, payload=payload or {})
    session.add(job)
    session.flush()
    return job


def _orch_token(sm) -> str:
    with sm() as s:
        raw = issue_token(s, principal="orchestrator", subject_id="orch-1", scope="orchestrator")
        s.commit()
    return raw


def _hdr(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


# ── сервис: аренда ──────────────────────────────────────────────────────────

def test_lease_claims_oldest_and_transitions_instance(sm):
    with sm() as s:
        inst = _mk_instance(s, status="pending")
        _mk_job(s, inst.id, "deploy")
        s.commit()
        iid = inst.id

    with sm() as s:
        job = lease_next(s, lease_ttl_s=60, max_deploy_attempts=3)
        s.commit()
        assert job is not None
        assert job.status == "leased"
        assert job.lease_nonce is not None
        assert s.get(Instance, iid).status == "deploying"  # pending → deploying на аренде


def test_lease_returns_none_when_empty(sm):
    with sm() as s:
        assert lease_next(s, lease_ttl_s=60, max_deploy_attempts=3) is None


# ── сервис: ack done / fencing ──────────────────────────────────────────────

def test_ack_done_deploy_sets_starting_and_infra_ref(sm):
    with sm() as s:
        inst = _mk_instance(s, status="pending")
        _mk_job(s, inst.id, "deploy")
        s.commit()
        iid = inst.id
    with sm() as s:
        job = lease_next(s, lease_ttl_s=60, max_deploy_attempts=3)
        s.commit()
        jid, nonce = job.id, str(job.lease_nonce)
    with sm() as s:
        ack(s, job_id=jid, nonce=nonce, result="done",
            detail={"infra_ref": "railway:p:s"}, max_deploy_attempts=3)
        s.commit()
    with sm() as s:
        assert s.get(Job, jid).status == "done"
        inst = s.get(Instance, iid)
        assert inst.status == "starting"          # deploying → starting (ждём heartbeat)
        assert inst.infra_ref == "railway:p:s"
        assert inst.deployed_at is not None


def test_ack_wrong_nonce_raises_conflict(sm):
    with sm() as s:
        inst = _mk_instance(s)
        _mk_job(s, inst.id, "deploy")
        s.commit()
    with sm() as s:
        job = lease_next(s, lease_ttl_s=60, max_deploy_attempts=3)
        s.commit()
        jid = job.id
    with sm() as s, pytest.raises(LeaseConflict):
        ack(s, job_id=jid, nonce=str(uuid.uuid4()), result="done", max_deploy_attempts=3)


# ── сервис: attempts / терминал / компенсация ───────────────────────────────

def test_deploy_fails_terminally_after_max_and_enqueues_teardown(sm):
    with sm() as s:
        inst = _mk_instance(s, status="pending", infra_ref="railway:p:s")
        _mk_job(s, inst.id, "deploy")
        s.commit()
        iid = inst.id

    # max=2: две неудачи → terminal
    for expected_attempts, terminal_after in ((1, False), (2, True)):
        with sm() as s:
            job = lease_next(s, lease_ttl_s=60, max_deploy_attempts=2)
            s.commit()
            jid, nonce = job.id, str(job.lease_nonce)
        with sm() as s:
            ack(s, job_id=jid, nonce=nonce, result="failed", max_deploy_attempts=2)
            s.commit()
        with sm() as s:
            job = s.get(Job, jid)
            assert job.attempts == expected_attempts
            assert job.status == ("failed" if terminal_after else "pending")

    with sm() as s:
        assert s.get(Instance, iid).status == "failed_deploy"  # освобождает счёт
        # компенсация: teardown-job создан на тот же инстанс с infra_ref (OPS3)
        tds = s.execute(
            text("SELECT payload FROM jobs WHERE kind='teardown' AND instance_id=:i"),
            {"i": str(iid)},
        ).all()
        assert len(tds) == 1
        assert tds[0][0] == {"infra_ref": "railway:p:s"}  # прибираем реальный сервис


def test_ack_terminal_flag_fails_deploy_immediately(sm):
    with sm() as s:
        inst = _mk_instance(s, status="pending")
        _mk_job(s, inst.id, "deploy")
        s.commit()
        iid = inst.id
    with sm() as s:
        job = lease_next(s, lease_ttl_s=60, max_deploy_attempts=3)
        s.commit()
        jid, nonce = job.id, str(job.lease_nonce)
    with sm() as s:  # terminal=True → сразу failed, не дожидаясь 3 попыток (decrypt/no-start)
        ack(s, job_id=jid, nonce=nonce, result="failed", terminal=True, max_deploy_attempts=3)
        s.commit()
    with sm() as s:
        assert s.get(Job, jid).status == "failed"
        assert s.get(Job, jid).attempts == 1
        assert s.get(Instance, iid).status == "failed_deploy"


def test_teardown_never_terminal(sm):
    with sm() as s:
        inst = _mk_instance(s, status="running")
        _mk_job(s, inst.id, "teardown")
        s.commit()
    # много неудач — teardown всегда возвращается в очередь (OPS5), никогда не failed
    for _ in range(5):
        with sm() as s:
            job = lease_next(s, lease_ttl_s=60, max_deploy_attempts=2)
            s.commit()
            jid, nonce = job.id, str(job.lease_nonce)
        with sm() as s:
            ack(s, job_id=jid, nonce=nonce, result="failed", max_deploy_attempts=2)
            s.commit()
        with sm() as s:
            assert s.get(Job, jid).status == "pending"  # не терминален


def test_release_requeues_without_attempt(sm):
    with sm() as s:
        inst = _mk_instance(s, status="pending")
        _mk_job(s, inst.id, "deploy")
        s.commit()
    with sm() as s:
        job = lease_next(s, lease_ttl_s=60, max_deploy_attempts=3)
        s.commit()
        jid, nonce = job.id, str(job.lease_nonce)
    with sm() as s:  # инфра лежит: отпуск без штрафа (OPS16)
        ack(s, job_id=jid, nonce=nonce, result="release", max_deploy_attempts=3)
        s.commit()
    with sm() as s:
        job = s.get(Job, jid)
        assert job.status == "pending"
        assert job.attempts == 0  # release НЕ считается неудачей


def test_expired_lease_is_reclaimed(sm):
    with sm() as s:
        inst = _mk_instance(s, status="deploying")
        job = _mk_job(s, inst.id, "deploy", status="leased")
        job.lease_nonce = uuid.uuid4()
        job.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)  # уже протухла
        s.commit()
        jid = job.id
    with sm() as s:  # lease_next реклеймит протухшую (attempts++) и переарендует
        got = lease_next(s, lease_ttl_s=60, max_deploy_attempts=3)
        s.commit()
        assert got.id == jid
        assert got.attempts == 1
        assert got.status == "leased"


# ── БД-инварианты ───────────────────────────────────────────────────────────

def test_one_active_deploy_per_instance(sm):
    with sm() as s:
        inst = _mk_instance(s)
        _mk_job(s, inst.id, "deploy")
        s.commit()
        iid = inst.id
    with pytest.raises(IntegrityError), sm() as s:  # второй активный deploy на тот же инстанс
        _mk_job(s, iid, "deploy")
        s.commit()


def test_backtest_kind_rejected(sm):
    with sm() as s:
        inst = _mk_instance(s)
        s.commit()
        iid = inst.id
    with pytest.raises(IntegrityError), sm() as s:  # kind='backtest' зарезервирован (CHECK)
        s.add(Job(kind="backtest", instance_id=iid, status="pending"))
        s.commit()


# ── HTTP: авторизация + round-trip ──────────────────────────────────────────

def test_next_requires_orchestrator_principal(sm):
    c = TestClient(create_app())
    assert c.get("/v1/internal/jobs/next?wait=0").status_code == 401  # без токена
    with sm() as s:  # чужой принципал (instance) → 403
        raw = issue_token(s, principal="instance", subject_id="i1", scope="instance")
        s.commit()
    assert c.get("/v1/internal/jobs/next?wait=0", headers=_hdr(raw)).status_code == 403


def test_longpoll_204_when_empty(sm):
    c = TestClient(create_app())
    r = c.get("/v1/internal/jobs/next?wait=0", headers=_hdr(_orch_token(sm)))
    assert r.status_code == 204


def test_http_lease_and_ack_roundtrip(sm):
    with sm() as s:
        inst = _mk_instance(s, status="pending")
        _mk_job(s, inst.id, "deploy", payload={"image": "paper:v0", "name": "mfc-inst-x"})
        s.commit()
        iid = inst.id
    c = TestClient(create_app())
    h = _hdr(_orch_token(sm))

    r = c.get("/v1/internal/jobs/next?wait=0", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "deploy"
    assert body["payload"]["image"] == "paper:v0"

    r2 = c.post(
        f"/v1/internal/jobs/{body['id']}/ack",
        headers=h,
        json={"lease_nonce": body["lease_nonce"], "result": "done",
              "detail": {"infra_ref": "railway:p:s"}},
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["status"] == "done"
    with sm() as s:
        assert s.get(Instance, iid).status == "starting"


def test_http_ack_stale_nonce_409(sm):
    with sm() as s:
        inst = _mk_instance(s, status="pending")
        _mk_job(s, inst.id, "deploy")
        s.commit()
    c = TestClient(create_app())
    h = _hdr(_orch_token(sm))
    body = c.get("/v1/internal/jobs/next?wait=0", headers=h).json()
    r = c.post(
        f"/v1/internal/jobs/{body['id']}/ack",
        headers=h,
        json={"lease_nonce": str(uuid.uuid4()), "result": "done"},  # чужой nonce
    )
    assert r.status_code == 409
