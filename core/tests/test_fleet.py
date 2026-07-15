"""Агрегаты флота для Обзора (#36): боты по статусу, AUM (последняя equity), closed-период
net+комиссия, клиенты. Readout, деньги в ядре. Нужен Postgres (DISTINCT ON)."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.billing import close_period
from app.db import get_sessionmaker
from app.fleet import fleet_instances, fleet_overview
from app.main import create_app
from app.models import Contract, EquityPoint, Instance
from app.periods import activate_billing
from tests.crm_helpers import ensure_parents


def _truncate() -> None:
    with get_sessionmaker()() as s:
        s.execute(text(
            "TRUNCATE billing_periods, cashflows, contracts, equity_points, instances, "
            "exchange_accounts, clients CASCADE"
        ))
        s.commit()


@pytest.fixture
def clean(_migrated: None):
    _truncate()
    yield
    _truncate()


def _instance(s, cid, aid, status) -> uuid.UUID:
    inst = Instance(
        client_id=cid, account_id=aid, bot_type_id=uuid.uuid4(),
        profile_id=uuid.uuid4(), status=status, health="ok",
    )
    s.add(inst)
    s.flush()
    return inst.id


def _equity(s, iid, eq, ts) -> None:
    s.add(EquityPoint(instance_id=iid, ts=ts, equity=Decimal(eq), currency="USDT"))


def test_overview_bots_clients_aum(clean) -> None:
    with get_sessionmaker()() as s:
        # один клиент, ТРИ счёта (партиал-индекс ≤1 живой инстанс на счёт, ADR-0013)
        cid, a1 = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        _, a2 = ensure_parents(s, cid, uuid.uuid4())
        _, a3 = ensure_parents(s, cid, uuid.uuid4())
        i1 = _instance(s, cid, a1, "running")
        i2 = _instance(s, cid, a2, "running")
        i3 = _instance(s, cid, a3, "paused")
        # AUM = сумма ПОСЛЕДНЕЙ equity по каждому инстансу
        _equity(s, i1, "1000", datetime(2026, 7, 1, tzinfo=UTC))
        _equity(s, i1, "1500", datetime(2026, 7, 2, tzinfo=UTC))  # последняя i1 = 1500
        _equity(s, i2, "2000", datetime(2026, 7, 2, tzinfo=UTC))
        _equity(s, i3, "500", datetime(2026, 7, 2, tzinfo=UTC))
        s.commit()
        ov = fleet_overview(s)
    assert ov["bots"] == {"running": 2, "paused": 1, "total": 3}
    assert ov["clients"] == 1
    assert Decimal(ov["aum"]) == Decimal("4000")  # 1500+2000+500 (старая точка i1=1000 не в счёт)
    assert ov["currency"] == "USDT"


def test_aum_excludes_inactive(clean) -> None:
    # #40 ш.2: stopped/остановленный инстанс с equity НЕ попадает в AUM (деньги возвращены клиенту).
    with get_sessionmaker()() as s:
        cid, a1 = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        _, a2 = ensure_parents(s, cid, uuid.uuid4())
        i_run = _instance(s, cid, a1, "running")
        i_stop = _instance(s, cid, a2, "stopped")
        _equity(s, i_run, "1000", datetime(2026, 7, 2, tzinfo=UTC))
        _equity(s, i_stop, "9999", datetime(2026, 7, 2, tzinfo=UTC))  # остановлен → не в AUM
        s.commit()
        ov = fleet_overview(s)
    assert Decimal(ov["aum"]) == Decimal("1000")  # только running; stopped исключён


def test_overview_empty(clean) -> None:
    with get_sessionmaker()() as s:
        ov = fleet_overview(s)
    assert ov["bots"] == {"running": 0, "paused": 0, "total": 0}
    assert Decimal(ov["aum"]) == 0
    assert Decimal(ov["pnl_net_closed"]) == 0
    assert ov["open_periods"] == 0


def test_overview_billing_rollup(clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        contract = Contract(client_id=cid, status="signed", fee_pct=Decimal("0.15"))
        s.add(contract)
        s.flush()
        pid = activate_billing(
            s, aid, contract.id, Decimal("10000"), "op", datetime(2020, 1, 15, tzinfo=UTC)
        ).id
        s.commit()
    with get_sessionmaker()() as s:  # закрыть период: +2000 net
        close_period(s, pid, end_equity=Decimal("12000"), actor="op")
        s.commit()
    with get_sessionmaker()() as s:
        ov = fleet_overview(s)
    assert Decimal(ov["pnl_net_closed"]) == Decimal("2000.00")
    assert Decimal(ov["commission_accrued"]) >= 0  # 0.15 × прибыль над HWM
    assert ov["open_periods"] == 0


# ── API ───────────────────────────────────────────────────────────────────────
def _login(c, email, pw) -> dict:
    r = c.post("/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_fleet_overview_endpoint(users, clean) -> None:
    c = TestClient(create_app())
    h = _login(c, "op@mfc.local", "op-pass")
    r = c.get("/v1/fleet/overview", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert "as_of" in body and "bots" in body and "aum" in body


def test_fleet_instances_list(clean) -> None:
    # Список инстансов: клиент присоединён, ПОСЛЕДНЯЯ equity, health; без телеметрии → equity None.
    with get_sessionmaker()() as s:
        cid, a1 = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        _, a2 = ensure_parents(s, cid, uuid.uuid4())
        i1 = _instance(s, cid, a1, "running")
        i2 = _instance(s, cid, a2, "paused")
        _equity(s, i1, "1000", datetime(2026, 7, 1, tzinfo=UTC))
        _equity(s, i1, "1500", datetime(2026, 7, 2, tzinfo=UTC))  # последняя i1 = 1500
        s.commit()
        rows = fleet_instances(s)
    by_id = {r["id"]: r for r in rows}
    assert len(rows) == 2
    assert by_id[str(i1)]["status"] == "running" and by_id[str(i1)]["health"] == "ok"
    assert Decimal(by_id[str(i1)]["equity"]) == Decimal("1500")  # последняя точка, не 1000
    assert by_id[str(i2)]["equity"] is None  # нет телеметрии → equity None
    assert all(r["client"] for r in rows)  # имя клиента присоединено (JOIN)


def test_fleet_instances_endpoint(users, clean) -> None:
    c = TestClient(create_app())
    h = _login(c, "op@mfc.local", "op-pass")
    r = c.get("/v1/fleet/instances", headers=h)
    assert r.status_code == 200, r.text
    assert isinstance(r.json(), list)
    # RBAC: клиент → 403, без токена → 401
    hcl = _login(c, "a@mfc.local", "a-pass")
    assert c.get("/v1/fleet/overview", headers=hcl).status_code == 403
    assert c.get("/v1/fleet/overview").status_code == 401
