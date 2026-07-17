"""engine_state (карточка бота S7): приём (токен инстанса) → replace → readout (оператор). PG."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import issue_token
from app.db import get_sessionmaker
from app.main import create_app
from app.models import Instance
from tests.crm_helpers import ensure_parents


@pytest.fixture
def clean(_migrated: None):
    with get_sessionmaker()() as s:
        s.execute(text("DELETE FROM engine_states"))
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


def _itok(iid: uuid.UUID) -> dict:
    with get_sessionmaker()() as s:
        raw = issue_token(s, principal="instance", subject_id=str(iid), scope="instance")
        s.commit()
        return {"Authorization": f"Bearer {raw}"}


STATE = {
    "status": {"state": "running", "kill_switch": False},
    "capital": {"equity": 20000, "open_count": 1},
    "positions": [
        {"symbol": "BTCUSDT", "side": "Buy", "size": 0.1, "avg_px": 60000, "live_pnl": 12}
    ],
    "orders": [], "trades": [], "events": [],
}


def test_ingest_and_readout(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = _mk_instance()
    itok = _itok(iid)

    # до пуша → state=None
    r = c.get(f"/v1/instances/{iid}/engine-state", headers=op)
    assert r.status_code == 200 and r.json()["state"] is None

    # картридж пушит (токен инстанса) → 202
    assert c.post("/v1/telemetry/engine-state", headers=itok, json=STATE).status_code == 202

    # readout оператора
    r = c.get(f"/v1/instances/{iid}/engine-state", headers=op)
    assert r.status_code == 200
    st = r.json()["state"]
    assert st["capital"]["equity"] == 20000 and st["positions"][0]["symbol"] == "BTCUSDT"
    assert r.json()["received_at"] is not None


def test_replace_keeps_last(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = _mk_instance()
    itok = _itok(iid)
    c.post("/v1/telemetry/engine-state", headers=itok, json={"capital": {"equity": 1}})
    c.post("/v1/telemetry/engine-state", headers=itok, json={"capital": {"equity": 2}})
    st = c.get(f"/v1/instances/{iid}/engine-state", headers=op).json()["state"]
    assert st["capital"]["equity"] == 2  # один ряд, последний


def test_readout_requires_operator(clean, users):
    c = TestClient(create_app())
    iid = _mk_instance()
    itok = _itok(iid)  # токен инстанса, не оператора
    r = c.get(f"/v1/instances/{iid}/engine-state", headers=itok)
    assert r.status_code in (401, 403)


def test_ingest_list_cap_413(clean, users):
    c = TestClient(create_app())
    iid = _mk_instance()
    itok = _itok(iid)
    big = {"positions": [{"symbol": "X", "size": 1} for _ in range(501)]}
    assert c.post("/v1/telemetry/engine-state", headers=itok, json=big).status_code == 413
