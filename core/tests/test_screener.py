"""Гвозди на скринер (С7-2б, шов S4): enqueue (оператор) → команда screener_run с payload{run_id,
params} → deliver боту → push результата (токен инстанса, владение) → readout оператора. Нужен PG.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import issue_token
from app.db import get_sessionmaker
from app.main import create_app
from app.models import Command, Instance, ScreenerRun
from tests.crm_helpers import ensure_parents


@pytest.fixture
def clean(_migrated: None):
    with get_sessionmaker()() as s:
        for t in ("screener_findings", "screener_runs", "commands"):
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


def _instance_token(iid: uuid.UUID) -> str:
    with get_sessionmaker()() as s:
        raw = issue_token(s, principal="instance", subject_id=str(iid), scope="instance")
        s.commit()
        return raw


def test_screener_full_flow(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = _mk_instance()

    # 1) оператор ставит прогон с параметрами (частично дефолтными)
    r = c.post(f"/v1/instances/{iid}/screener/runs", headers=op,
               json={"k": 2.0, "universe_max": 80})
    assert r.status_code == 201, r.text
    run_id = r.json()["run_id"]
    assert r.json()["status"] == "queued"

    # создались ScreenerRun + Command(screener_run) с payload{run_id,params}
    with get_sessionmaker()() as s:
        run = s.get(ScreenerRun, uuid.UUID(run_id))
        assert run.status == "queued" and run.params["k"] == 2.0
        assert run.params["min_age_days"] == 180 and run.params["tfs"] == ["4h", "1h"]  # дефолты
        cmd = s.scalars(select_cmd(iid)).first()
        assert cmd.kind == "screener_run" and cmd.payload["run_id"] == run_id
        assert cmd.payload["params"]["universe_max"] == 80

    # 2) бот забирает команду long-poll'ом — получает kind + payload
    itok = {"Authorization": f"Bearer {_instance_token(iid)}"}
    r = c.get("/v1/commands/next?wait=0", headers=itok)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["cmd"] == "screener_run"
    assert body["payload"]["run_id"] == run_id and body["payload"]["params"]["k"] == 2.0

    # 3) бот пушит результат (running → потом done с findings+summary)
    r = c.post(f"/v1/screener/runs/{run_id}/results", headers=itok, json={"status": "running"})
    assert r.status_code == 200 and r.json()["status"] == "running"

    findings = [
        {"symbol": "HOMEUSDT", "impulse_ratio": 3.8, "score": 44, "selected": True,
         "setups": [{"tf": "4h", "status": "forming"}]},
        {"symbol": "CROUSDT", "impulse_ratio": 1.55, "score": 72, "selected": True, "setups": []},
    ]
    r = c.post(f"/v1/screener/runs/{run_id}/results", headers=itok,
               json={"status": "done", "summary": {"passed": 76, "selected": 2},
                     "findings": findings})
    assert r.status_code == 200 and r.json()["status"] == "done"

    # 4) оператор читает прогон — статус done + строки
    r = c.get(f"/v1/screener/runs/{run_id}", headers=op)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["status"] == "done" and out["summary"]["selected"] == 2
    syms = {f["symbol"] for f in out["findings"]}
    assert syms == {"HOMEUSDT", "CROUSDT"}

    # список прогонов инстанса
    r = c.get(f"/v1/instances/{iid}/screener/runs", headers=op)
    assert r.status_code == 200 and len(r.json()) == 1 and r.json()[0]["run_id"] == run_id


def test_push_replace_semantics(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = _mk_instance()
    run_id = c.post(f"/v1/instances/{iid}/screener/runs", headers=op, json={}).json()["run_id"]
    itok = {"Authorization": f"Bearer {_instance_token(iid)}"}

    c.post(f"/v1/screener/runs/{run_id}/results", headers=itok,
           json={"status": "running", "findings": [{"symbol": "AAA"}, {"symbol": "BBB"}]})
    # повторный пуш заменяет строки целиком (не дублирует)
    c.post(f"/v1/screener/runs/{run_id}/results", headers=itok,
           json={"status": "done", "findings": [{"symbol": "CCC"}]})
    out = c.get(f"/v1/screener/runs/{run_id}", headers=op).json()
    assert [f["symbol"] for f in out["findings"]] == ["CCC"]


def test_push_ownership_404(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid_a = _mk_instance()
    iid_b = _mk_instance()
    run_id = c.post(f"/v1/instances/{iid_a}/screener/runs", headers=op, json={}).json()["run_id"]
    # инстанс B пушит в прогон инстанса A → 404 (владение, SEC7)
    tok_b = {"Authorization": f"Bearer {_instance_token(iid_b)}"}
    r = c.post(f"/v1/screener/runs/{run_id}/results", headers=tok_b, json={"status": "done"})
    assert r.status_code == 404


def test_enqueue_unknown_instance_404(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    r = c.post(f"/v1/instances/{uuid.uuid4()}/screener/runs", headers=op, json={})
    assert r.status_code == 404


def test_enqueue_requires_operator(clean, users):
    c = TestClient(create_app())
    iid = _mk_instance()
    itok = {"Authorization": f"Bearer {_instance_token(iid)}"}  # токен инстанса, не оператора
    r = c.post(f"/v1/instances/{iid}/screener/runs", headers=itok, json={})
    assert r.status_code in (401, 403)


def select_cmd(iid):
    from sqlalchemy import select
    return select(Command).where(Command.instance_id == iid)
