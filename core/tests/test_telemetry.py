"""Гвозди на приём телеметрии (MFC-005, шов S4): heartbeat→last_heartbeat_at, dedup идемпотентность
equity/trades/events, ts-skew, лимит батча, auth (принципал/владение) + sync схема↔Pydantic.
ts строим от now() — тест не зависит от часов машины. Нужен Postgres."""

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import issue_token
from app.db import get_sessionmaker
from app.main import create_app
from app.models import Instance
from app.routes_telemetry import EquityIn, EventIn, HeartbeatIn, TradeIn

_CONTRACTS = Path(__file__).resolve().parents[2] / "contracts"


@pytest.fixture
def sm(_migrated: None):
    m = get_sessionmaker()
    with m() as s:
        for t in ("equity_points", "trades", "events", "commands", "jobs"):
            s.execute(text(f"DELETE FROM {t}"))
        s.execute(text("DELETE FROM instances"))
        s.execute(text("DELETE FROM api_tokens"))
        s.commit()
    return m


def _mk_instance_token(sm, status="running") -> tuple[uuid.UUID, str]:
    with sm() as s:
        inst = Instance(
            client_id=uuid.uuid4(), account_id=uuid.uuid4(), bot_type_id=uuid.uuid4(),
            profile_id=uuid.uuid4(), status=status, health="ok",
        )
        s.add(inst)
        s.flush()
        raw = issue_token(s, principal="instance", subject_id=str(inst.id), scope="instance")
        s.commit()
        return inst.id, raw


def _hdr(raw: str) -> dict:
    return {"Authorization": f"Bearer {raw}"}


def _iso(offset_s: float = 0) -> str:
    return (datetime.now(UTC) + timedelta(seconds=offset_s)).isoformat()


def _count(sm, table: str, iid: uuid.UUID) -> int:
    with sm() as s:
        return s.execute(
            text(f"SELECT count(*) FROM {table} WHERE instance_id=:i"), {"i": str(iid)}
        ).scalar()


# ── heartbeat ───────────────────────────────────────────────────────────────

def test_heartbeat_refreshes_last_heartbeat(sm):
    iid, tok = _mk_instance_token(sm)
    c = TestClient(create_app())
    r = c.post("/v1/telemetry/heartbeat", headers=_hdr(tok),
               json={"status": "running", "uptime_s": 12.5, "contract_version": "v0"})
    assert r.status_code == 204
    with sm() as s:
        assert s.get(Instance, iid).last_heartbeat_at is not None  # кормит stale-скан MFC-003


def test_first_heartbeat_moves_starting_to_running(sm):
    iid, tok = _mk_instance_token(sm, status="starting")
    c = TestClient(create_app())
    c.post("/v1/telemetry/heartbeat", headers=_hdr(tok),
           json={"status": "running", "uptime_s": 1, "contract_version": "v0"})
    with sm() as s:
        assert s.get(Instance, iid).status == "running"  # бот жив: starting→running


# ── dedup идемпотентность ─────────────────────────────────────────────────────

def test_equity_dedup_by_ts(sm):
    iid, tok = _mk_instance_token(sm)
    c = TestClient(create_app())
    body = {"ts": _iso(), "equity": 10000.5, "currency": "USDT"}
    assert c.post("/v1/telemetry/equity", headers=_hdr(tok), json=body).status_code == 202
    assert c.post("/v1/telemetry/equity", headers=_hdr(tok), json=body).status_code == 202  # повтор
    assert _count(sm, "equity_points", iid) == 1  # dedup (instance, ts)


def test_trades_dedup_by_exec_id(sm):
    iid, tok = _mk_instance_token(sm)
    c = TestClient(create_app())
    ts = _iso()
    batch = [
        {"ts": ts, "exec_id": "e1", "symbol": "BTCUSDT", "side": "buy", "qty": 0.1},
        {"ts": ts, "exec_id": "e2", "symbol": "BTCUSDT", "side": "sell", "qty": 0.1, "pnl": 5},
    ]
    assert c.post("/v1/telemetry/trades", headers=_hdr(tok), json=batch).status_code == 202
    # повтор e1/e2 + новый e3 (со-секундный e3 с тем же ts — dedup по exec_id, не по ts, COH4)
    batch2 = batch + [{"ts": ts, "exec_id": "e3", "symbol": "ETHUSDT", "side": "buy", "qty": 1}]
    assert c.post("/v1/telemetry/trades", headers=_hdr(tok), json=batch2).status_code == 202
    assert _count(sm, "trades", iid) == 3  # e1,e2,e3 — дублей нет


def test_events_dedup_by_ts_kind(sm):
    iid, tok = _mk_instance_token(sm)
    c = TestClient(create_app())
    ts = _iso()
    b1 = [{"ts": ts, "kind": "entry_filled", "detail": {"symbol": "BTCUSDT"}}]
    # b2: тот же (ts, kind) → dedup; другой kind → пройдёт
    b2 = [{"ts": ts, "kind": "entry_filled", "detail": {"symbol": "ETHUSDT"}},
          {"ts": ts, "kind": "sl_moved", "detail": {"to": 1}}]
    assert c.post("/v1/telemetry/events", headers=_hdr(tok), json=b1).status_code == 202
    assert c.post("/v1/telemetry/events", headers=_hdr(tok), json=b2).status_code == 202
    assert _count(sm, "events", iid) == 2  # entry_filled(1) + sl_moved


# ── валидация ────────────────────────────────────────────────────────────────

def test_equity_rejects_stale_ts(sm):
    _, tok = _mk_instance_token(sm)
    c = TestClient(create_app())
    body = {"ts": _iso(-100 * 86400), "equity": 100, "currency": "USDT"}  # 100 суток назад
    assert c.post("/v1/telemetry/equity", headers=_hdr(tok), json=body).status_code == 422


def test_equity_rejects_non_usdt(sm):
    _, tok = _mk_instance_token(sm)
    c = TestClient(create_app())
    body = {"ts": _iso(), "equity": 100, "currency": "BTC"}  # v0 — только USDT (MON9)
    assert c.post("/v1/telemetry/equity", headers=_hdr(tok), json=body).status_code == 422


def test_trades_batch_over_limit_413(sm):
    _, tok = _mk_instance_token(sm)
    c = TestClient(create_app())
    ts = _iso()
    one = {"ts": ts, "symbol": "X", "side": "buy", "qty": 1}
    big = [{**one, "exec_id": f"e{i}"} for i in range(501)]
    assert c.post("/v1/telemetry/trades", headers=_hdr(tok), json=big).status_code == 413


# ── auth (принципал / владение) ──────────────────────────────────────────────

def test_non_instance_principal_403(sm):
    with sm() as s:
        raw = issue_token(s, principal="orchestrator", subject_id="o1", scope="orchestrator")
        s.commit()
    c = TestClient(create_app())
    r = c.post("/v1/telemetry/heartbeat", headers=_hdr(raw),
               json={"status": "running", "uptime_s": 1, "contract_version": "v0"})
    assert r.status_code == 403  # не токен инстанса


def test_unknown_instance_404(sm):
    with sm() as s:  # токен инстанса, которого нет в таблице
        raw = issue_token(s, principal="instance", subject_id=str(uuid.uuid4()), scope="instance")
        s.commit()
    c = TestClient(create_app())
    r = c.post("/v1/telemetry/heartbeat", headers=_hdr(raw),
               json={"status": "running", "uptime_s": 1, "contract_version": "v0"})
    assert r.status_code == 404


# ── sync схема↔Pydantic (schema-first: правка схемы без модели уронит это) ────

@pytest.mark.parametrize(
    "schema_name,model,is_array",
    [
        ("telemetry-heartbeat", HeartbeatIn, False),
        ("telemetry-equity", EquityIn, False),
        ("telemetry-trades", TradeIn, True),
        ("telemetry-events", EventIn, True),
    ],
)
def test_schema_examples_accepted_by_pydantic(schema_name, model, is_array):
    schema = json.loads((_CONTRACTS / f"{schema_name}.schema.json").read_text(encoding="utf-8"))
    for ex in schema["examples"]:
        items = ex if is_array else [ex]
        for item in items:
            model.model_validate(item)  # пример из схемы принимается моделью ядра
