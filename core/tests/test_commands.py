"""Гвозди на команды боту (MFC-005, шов S4←, ADR-0005): enqueue→deliver→ack, липкий stop_close,
ошибка stop_close (не гасим), идемпотентность ack, владение (чужая команда 404), auth. Нужен PG."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import issue_token
from app.db import get_sessionmaker
from app.main import create_app
from app.models import Instance


@pytest.fixture
def clean(_migrated: None):
    with get_sessionmaker()() as s:
        for t in ("commands", "jobs", "equity_points", "trades", "events"):
            s.execute(text(f"DELETE FROM {t}"))
        s.execute(text("DELETE FROM instances"))
        s.commit()


def _login(c: TestClient, email: str, pw: str) -> dict:
    r = c.post("/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _hdr(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


def _mk_instance(status="running") -> uuid.UUID:
    with get_sessionmaker()() as s:
        inst = Instance(
            client_id=uuid.uuid4(), account_id=uuid.uuid4(), bot_type_id=uuid.uuid4(),
            profile_id=uuid.uuid4(), status=status, health="ok",
        )
        s.add(inst)
        s.commit()
        return inst.id


def _instance_token(iid: uuid.UUID) -> str:
    with get_sessionmaker()() as s:
        raw = issue_token(s, principal="instance", subject_id=str(iid), scope="instance")
        s.commit()
        return raw


def _enqueue(c, iid, oph, kind) -> str:
    r = c.post(f"/v1/instances/{iid}/commands", headers=oph, json={"kind": kind})
    assert r.status_code == 201, r.text
    return r.json()["cmd_id"]


def _status(iid) -> str:
    with get_sessionmaker()() as s:
        return s.get(Instance, iid).status


# ── enqueue (продюсер оператора) ─────────────────────────────────────────────

def test_enqueue_requires_operator(users, clean):
    iid = _mk_instance()
    c = TestClient(create_app())
    r = c.post(f"/v1/instances/{iid}/commands", headers=_login(c, "a@mfc.local", "a-pass"),
               json={"kind": "pause"})
    assert r.status_code == 403  # клиент не командует


def test_enqueue_terminal_instance_409(users, clean):
    iid = _mk_instance("stopped")
    c = TestClient(create_app())
    r = c.post(f"/v1/instances/{iid}/commands", headers=_login(c, "op@mfc.local", "op-pass"),
               json={"kind": "pause"})
    assert r.status_code == 409  # погашенному команда не ставится


# ── deliver + ack ────────────────────────────────────────────────────────────

def test_pause_deliver_ack_sets_paused(users, clean):
    iid = _mk_instance("running")
    c = TestClient(create_app())
    cmd_id = _enqueue(c, iid, _login(c, "op@mfc.local", "op-pass"), "pause")
    ih = _hdr(_instance_token(iid))
    got = c.get("/v1/commands/next?wait=0", headers=ih).json()
    assert got == {"cmd": "pause", "cmd_id": cmd_id}
    r = c.post(f"/v1/commands/{cmd_id}/ack", headers=ih, json={"result": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "acked"
    assert _status(iid) == "paused"


def test_next_empty_returns_none(users, clean):
    iid = _mk_instance()
    c = TestClient(create_app())
    assert c.get("/v1/commands/next?wait=0", headers=_hdr(_instance_token(iid))).json() == {
        "cmd": "none", "cmd_id": None
    }


def test_stop_close_sticky_then_stopped(users, clean):
    iid = _mk_instance("running")
    c = TestClient(create_app())
    cmd_id = _enqueue(c, iid, _login(c, "op@mfc.local", "op-pass"), "stop_close")
    ih = _hdr(_instance_token(iid))
    # первая выдача → инстанс в stopping
    assert c.get("/v1/commands/next?wait=0", headers=ih).json()["cmd"] == "stop_close"
    assert _status(iid) == "stopping"
    # липкость (OPS1): повторный опрос снова отдаёт stop_close, а не none
    assert c.get("/v1/commands/next?wait=0", headers=ih).json() == {
        "cmd": "stop_close", "cmd_id": cmd_id
    }
    # ack ok → погашен
    c.post(f"/v1/commands/{cmd_id}/ack", headers=ih, json={"result": "ok"})
    assert _status(iid) == "stopped"
    # больше не stopping → очередь пуста
    assert c.get("/v1/commands/next?wait=0", headers=ih).json()["cmd"] == "none"


def test_stop_close_error_stays_stopping(users, clean):
    iid = _mk_instance("running")
    c = TestClient(create_app())
    cmd_id = _enqueue(c, iid, _login(c, "op@mfc.local", "op-pass"), "stop_close")
    ih = _hdr(_instance_token(iid))
    c.get("/v1/commands/next?wait=0", headers=ih)  # deliver → stopping
    r = c.post(f"/v1/commands/{cmd_id}/ack", headers=ih,
               json={"result": "error", "detail": {"reason": "позиции не закрылись"}})
    assert r.json()["status"] == "failed"
    assert _status(iid) == "stopping"  # НЕ гасим — ручное закрытие (flows Б)


def test_ack_idempotent(users, clean):
    iid = _mk_instance("running")
    c = TestClient(create_app())
    cmd_id = _enqueue(c, iid, _login(c, "op@mfc.local", "op-pass"), "pause")
    ih = _hdr(_instance_token(iid))
    c.get("/v1/commands/next?wait=0", headers=ih)
    first = c.post(f"/v1/commands/{cmd_id}/ack", headers=ih, json={"result": "ok"})
    assert first.status_code == 200
    # повторный ack — идемпотентно тот же результат
    r = c.post(f"/v1/commands/{cmd_id}/ack", headers=ih, json={"result": "ok"})
    assert r.status_code == 200 and r.json()["status"] == "acked"


def test_ack_foreign_command_404(users, clean):
    iid_a, iid_b = _mk_instance("running"), _mk_instance("running")
    c = TestClient(create_app())
    cmd_id = _enqueue(c, iid_a, _login(c, "op@mfc.local", "op-pass"), "pause")
    # токеном инстанса B ack'аем команду инстанса A → 404 (владение, SEC7)
    r = c.post(f"/v1/commands/{cmd_id}/ack", headers=_hdr(_instance_token(iid_b)),
               json={"result": "ok"})
    assert r.status_code == 404


def test_next_non_instance_principal_403(users, clean):
    with get_sessionmaker()() as s:
        raw = issue_token(s, principal="orchestrator", subject_id="o1", scope="orchestrator")
        s.commit()
    c = TestClient(create_app())
    assert c.get("/v1/commands/next?wait=0", headers=_hdr(raw)).status_code == 403
