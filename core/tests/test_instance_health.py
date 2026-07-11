"""Гвозди на свёртку stale-скан + инвариант ≤1 живой инстанс/счёт (MFC-003). Нужен Postgres."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.config import Settings
from app.db import get_sessionmaker
from app.instance_health import classify, scan_once
from app.models import Instance


@pytest.fixture
def sm(_migrated: None):
    m = get_sessionmaker()
    with m() as s:  # чистое дерево инстансов (audit_log append-only — не трогаем)
        s.execute(text("DELETE FROM instances"))
        s.commit()
    return m


def _mk(session, status="running", hb_age_s=10.0, account_id=None) -> Instance:
    hb = None if hb_age_s is None else datetime.now(UTC) - timedelta(seconds=hb_age_s)
    inst = Instance(
        client_id=uuid.uuid4(),
        account_id=account_id or uuid.uuid4(),
        bot_type_id=uuid.uuid4(),
        profile_id=uuid.uuid4(),
        status=status,
        health="ok",
        last_heartbeat_at=hb,
    )
    session.add(inst)
    return inst


def test_classify_boundaries() -> None:
    assert classify(10, 180, 600) == "ok"
    assert classify(181, 180, 600) == "stale"
    assert classify(601, 180, 600) == "dead"
    assert classify(180, 180, 600) == "ok"     # ровно порог stale — ещё ok (строгое >)
    assert classify(600, 180, 600) == "stale"  # ровно порог dead — ещё stale


def test_scan_flips_by_freshness(sm) -> None:
    with sm() as s:
        made = {
            "fresh": _mk(s, "running", 10),     # свежий → ok
            "stale": _mk(s, "running", 200),    # 200с → stale
            "dead": _mk(s, "running", 700),     # 700с → dead
            "never": _mk(s, "running", None),   # NULL heartbeat → пропуск
            "stopped": _mk(s, "stopped", 700),  # не живой статус → пропуск
        }
        s.commit()
        ids = {n: i.id for n, i in made.items()}

    assert scan_once(sm, 180, 600) == 2  # меняются только stale и dead

    with sm() as s:
        got = {n: s.get(Instance, i).health for n, i in ids.items()}
    assert got == {"fresh": "ok", "stale": "stale", "dead": "dead", "never": "ok", "stopped": "ok"}


def test_scan_writes_audit_and_is_idempotent(sm) -> None:
    with sm() as s:
        inst = _mk(s, "running", 700)  # → dead
        s.commit()
        iid = inst.id

    assert scan_once(sm, 180, 600) == 1
    assert scan_once(sm, 180, 600) == 0  # health уже dead → повторный проход ничего не меняет

    with sm() as s:
        rows = s.execute(
            text(
                "SELECT actor, before, after FROM audit_log "
                "WHERE action='instance_health' AND entity=:e"
            ),
            {"e": str(iid)},
        ).all()
    assert len(rows) == 1
    actor, before, after = rows[0]
    assert actor == "system:sentinel"
    assert before["health"] == "ok"
    assert after["health"] == "dead"


def test_one_live_instance_per_account(sm) -> None:
    acct = uuid.uuid4()
    with sm() as s:
        _mk(s, "running", 10, account_id=acct)
        s.commit()
    # второй ЖИВОЙ на тот же счёт → нарушение партиал-уникального индекса (OPS3/MON2)
    with pytest.raises(IntegrityError), sm() as s:
        _mk(s, "paused", 10, account_id=acct)
        s.commit()
    # терминальный статус на том же счёте — счёт свободен, вставка проходит
    with sm() as s:
        _mk(s, "stopped", 10, account_id=acct)
        s.commit()


def test_paused_and_stopping_are_scanned(sm) -> None:
    with sm() as s:
        paused = _mk(s, "paused", 200)      # → stale
        stopping = _mk(s, "stopping", 700)  # → dead
        s.commit()
        pid, sid = paused.id, stopping.id
    assert scan_once(sm, 180, 600) == 2
    with sm() as s:
        assert s.get(Instance, pid).health == "stale"
        assert s.get(Instance, sid).health == "dead"


def test_escalation_and_recovery(sm) -> None:
    with sm() as s:
        inst = _mk(s, "running", 200)  # → stale
        s.commit()
        iid = inst.id
    assert scan_once(sm, 180, 600) == 1  # ok → stale

    with sm() as s:  # heartbeat протух сильнее → stale → dead
        s.get(Instance, iid).last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=700)
        s.commit()
    assert scan_once(sm, 180, 600) == 1

    with sm() as s:  # свежий heartbeat → dead → ok (восстановление)
        s.get(Instance, iid).last_heartbeat_at = datetime.now(UTC)
        s.commit()
    assert scan_once(sm, 180, 600) == 1

    with sm() as s:
        assert s.get(Instance, iid).health == "ok"
        n = s.execute(
            text("SELECT count(*) FROM audit_log WHERE action='instance_health' AND entity=:e"),
            {"e": str(iid)},
        ).scalar()
    assert n == 3  # три перехода записаны (ok→stale→dead→ok)


def test_index_failed_deploy_frees_but_failed_occupies(sm) -> None:
    a = uuid.uuid4()
    with sm() as s:  # failed_deploy освобождает счёт → уживается с running
        _mk(s, "running", 10, account_id=a)
        _mk(s, "failed_deploy", 10, account_id=a)
        s.commit()
    b = uuid.uuid4()
    with sm() as s:
        _mk(s, "running", 10, account_id=b)
        s.commit()
    with pytest.raises(IntegrityError), sm() as s:  # failed занимает → коллизия с running
        _mk(s, "failed", 10, account_id=b)
        s.commit()


def test_inverted_thresholds_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(instance_stale_after_seconds=600, instance_dead_after_seconds=180)
