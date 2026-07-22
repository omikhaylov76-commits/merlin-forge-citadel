"""Гвозди на «Разведка-стол» ядро (S7): readout настроек дозора (дефолты→desired), применение
(desired + команда dozor_apply + журнал audit), валидация порогов, scan_now-команда, журнал, RBAC
(клиент 403). Ядро=истина (Q4). Пороги — отбор скаута, не торговля. Нужен PG."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.auth import issue_token
from app.db import get_sessionmaker
from app.main import create_app
from app.models import Command, Instance
from tests.crm_helpers import ensure_parents


@pytest.fixture
def clean(_migrated: None):
    with get_sessionmaker()() as s:
        for t in ("scout_settings", "commands"):
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
    return {
        "min_age_days": 365, "min_turnover_usd": 10_000_000, "max_spread_pct": 0.2,
        "min_history_bars": 400, "min_score": 40, "universe_max": 250, "list_max": 40,
        "tfs": ["4h", "1h"], "primary_tf": "1h", "fresh_bars": 48, "scan_bars": 300,
        "cal_bars": 1000, "cal_utc_hour": 6, "rps": 2,
    }


def test_scout_settings_defaults_then_apply(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = str(_mk_instance())

    # readout без строки → дефолты (совпадают с тем, что бежит на представителе)
    r = c.get(f"/v1/instances/{iid}/scout/settings", headers=op)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["settings"]["min_age_days"] == 180 and body["settings"]["list_max"] == 50
    assert body["apply"]["status"] == "none"

    # применить новые пороги → desired сохранён + команда dozor_apply + журнал
    new = _valid_settings()
    p = c.put(f"/v1/instances/{iid}/scout/settings", headers=op, json=new)
    assert p.status_code == 200, p.text
    assert p.json()["settings"]["primary_tf"] == "1h"
    assert p.json()["apply"]["status"] == "queued"

    # команда dozor_apply поставлена с payload.settings
    with get_sessionmaker()() as s:
        cmd = s.query(Command).filter_by(instance_id=uuid.UUID(iid), kind="dozor_apply").one()
        assert cmd.status == "queued" and cmd.payload["settings"]["primary_tf"] == "1h"

    # readout теперь отражает desired + apply queued
    r2 = c.get(f"/v1/instances/{iid}/scout/settings", headers=op).json()
    assert r2["settings"]["min_age_days"] == 365 and r2["settings"]["list_max"] == 40
    assert r2["apply"]["status"] == "queued"

    # журнал: одно изменение (что→что), из audit_log
    j = c.get(f"/v1/instances/{iid}/scout/settings/journal", headers=op).json()
    assert len(j) == 1
    assert j[0]["before"]["min_age_days"] == 180 and j[0]["after"]["min_age_days"] == 365


def test_scout_settings_validation(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = str(_mk_instance())

    # primary_tf не среди tfs → 422
    bad = {**_valid_settings(), "tfs": ["4h"], "primary_tf": "1h"}
    assert c.put(f"/v1/instances/{iid}/scout/settings", headers=op, json=bad).status_code == 422
    # недопустимый ТФ → 422
    bad2 = {**_valid_settings(), "tfs": ["15m"], "primary_tf": "15m"}
    assert c.put(f"/v1/instances/{iid}/scout/settings", headers=op, json=bad2).status_code == 422
    # rps вне диапазона → 422
    bad3 = {**_valid_settings(), "rps": 99}
    assert c.put(f"/v1/instances/{iid}/scout/settings", headers=op, json=bad3).status_code == 422


def _instance_token(iid: uuid.UUID) -> str:
    with get_sessionmaker()() as s:
        raw = issue_token(s, principal="instance", subject_id=str(iid), scope="instance")
        s.commit()
        return raw


def test_scout_settings_self_instance_token(clean, users):
    """Картридж (instance-токен) читает СВОИ настройки через /scout/settings/self."""
    c = TestClient(create_app())
    iid = _mk_instance()
    op = _login(c, "op@mfc.local", "op-pass")
    ih = {"Authorization": f"Bearer {_instance_token(iid)}"}

    r = c.get("/v1/scout/settings/self", headers=ih)
    assert r.status_code == 200, r.text
    assert r.json()["settings"]["min_age_days"] == 180  # дефолты, пока не менялись

    c.put(f"/v1/instances/{iid}/scout/settings", headers=op, json=_valid_settings())
    r2 = c.get("/v1/scout/settings/self", headers=ih).json()
    assert r2["settings"]["primary_tf"] == "1h" and r2["settings"]["list_max"] == 40


def test_scan_now_enqueues_command(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = str(_mk_instance())
    r = c.post(f"/v1/instances/{iid}/scout/scan-now", headers=op)
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "queued"
    with get_sessionmaker()() as s:
        cmd = s.query(Command).filter_by(instance_id=uuid.UUID(iid), kind="scan_now").one()
        assert cmd.status == "queued"


def test_warm_apply_enqueues_command(clean, users):
    """F-warm-button (ADR-0022): оператор → команда warm_apply с нормализованными монетами."""
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = str(_mk_instance())
    r = c.post(f"/v1/instances/{iid}/scout/warm-apply", headers=op,
               json={"coins": ["1inchusdt", "epicusdt"]})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "queued"
    with get_sessionmaker()() as s:
        cmd = s.query(Command).filter_by(instance_id=uuid.UUID(iid), kind="warm_apply").one()
        assert cmd.status == "queued"
        assert cmd.payload["coins"] == ["1INCHUSDT", "EPICUSDT"]  # upper/strip нормализация


def test_warm_apply_empty_coins_422(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    iid = str(_mk_instance())
    r = c.post(f"/v1/instances/{iid}/scout/warm-apply", headers=op, json={"coins": []})
    assert r.status_code == 422


def test_warm_apply_rbac_client_forbidden(clean, users):
    """F-warm-button — портал клиента команду НЕ видит (Закон 5): client → 403."""
    c = TestClient(create_app())
    cli = _login(c, "a@mfc.local", "a-pass")
    iid = str(_mk_instance())
    r = c.post(f"/v1/instances/{iid}/scout/warm-apply", headers=cli, json={"coins": ["BTCUSDT"]})
    assert r.status_code == 403


def test_scout_settings_rbac_client_forbidden(clean, users):
    c = TestClient(create_app())
    cli = _login(c, "a@mfc.local", "a-pass")
    iid = str(_mk_instance())
    assert c.get(f"/v1/instances/{iid}/scout/settings", headers=cli).status_code == 403
    put = c.put(f"/v1/instances/{iid}/scout/settings", headers=cli, json=_valid_settings())
    assert put.status_code == 403
    assert c.post(f"/v1/instances/{iid}/scout/scan-now", headers=cli).status_code == 403


def test_scout_settings_unknown_instance_404(clean, users):
    c = TestClient(create_app())
    op = _login(c, "op@mfc.local", "op-pass")
    assert c.get(f"/v1/instances/{uuid.uuid4()}/scout/settings", headers=op).status_code == 404
