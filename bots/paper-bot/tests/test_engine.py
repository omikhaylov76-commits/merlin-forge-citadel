"""Гвозди на PaperEngine: детерминизм, честные семантики ADR-0005 (pause держит позицию, stop_close
закрывает), валидность payload'ов против contracts/*.schema.json. БД/сеть не нужны."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from app.engine import PaperEngine

_CONTRACTS = Path(__file__).resolve().parents[3] / "contracts"
_NOW = datetime(2026, 7, 11, 12, 0, 0, tzinfo=UTC)


def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(
        json.loads((_CONTRACTS / f"{name}.schema.json").read_text(encoding="utf-8"))
    )


def test_determinism_same_seed_same_stream():
    a, b = PaperEngine(seed=7), PaperEngine(seed=7)
    for _ in range(20):
        ta, tb = a.tick(_NOW), b.tick(_NOW)
        assert ta == tb  # тот же сид → тот же поток (equity + сделки)
    assert a.position == b.position


def test_running_opens_positions():
    e = PaperEngine(seed=7)
    for _ in range(30):
        e.tick(_NOW)
    assert e.position > 0  # за 30 оборотов движок набрал позицию (иначе нечего держать в паузе)


def test_pause_holds_position_and_stops_entries():
    e = PaperEngine(seed=7)
    for _ in range(30):
        e.tick(_NOW)
    held = e.position
    assert held > 0
    e.pause()
    assert e.heartbeat_status() == "paused"
    for _ in range(30):
        t = e.tick(_NOW)
        assert t.trades == []  # НЕТ новых входов в паузе
    assert e.position == held  # позиция ДЕРЖИТСЯ (ADR-0005 честно)


def test_resume_reenables_entries():
    e = PaperEngine(seed=7)
    e.pause()
    e.resume()
    assert e.state == "running"
    seen = any(e.tick(_NOW).trades for _ in range(50))
    assert seen  # после resume входы снова возможны


def test_stop_close_closes_position_and_emits_kill_switch():
    e = PaperEngine(seed=7)
    for _ in range(30):
        e.tick(_NOW)
    assert e.position > 0
    out = e.stop_close(_NOW)
    assert e.position == Decimal("0")  # позиция ЗАКРЫТА
    assert e.state == "stopped"        # встали
    assert any(ev["kind"] == "kill_switch" for ev in out.events)
    assert out.trades and out.trades[0]["side"] == "sell"  # закрывающая сделка


def test_stop_close_is_idempotent():
    # MINOR 2: ретрай stop_close (сбой пуша до ack) должен вернуть ТОТ ЖЕ tick — филл/kill_switch
    # переэмитятся с тем же exec_id/ts (дедуп ядра безопасен), а не потеряются.
    e = PaperEngine(seed=7)
    for _ in range(20):
        e.tick(_NOW)
    first = e.stop_close(_NOW)
    second = e.stop_close(_NOW)
    assert second == first
    assert e.position == Decimal("0")
    if first.trades:
        assert second.trades[0]["exec_id"] == first.trades[0]["exec_id"]


def test_payloads_conform_to_schemas():
    e = PaperEngine(seed=7)
    eq_v = _validator("telemetry-equity")
    tr_v = _validator("telemetry-trades")
    ev_v = _validator("telemetry-events")
    for _ in range(40):
        t = e.tick(_NOW)
        eq_v.validate(t.equity)
        tr_v.validate(t.trades)  # массив сделок целиком
        ev_v.validate(t.events)
    out = e.stop_close(_NOW)  # закрывающие сделки + событие тоже валидны
    eq_v.validate(out.equity)
    tr_v.validate(out.trades)
    ev_v.validate(out.events)


def test_never_reports_when_stopped():
    e = PaperEngine(seed=7)
    e.stop_close(_NOW)
    # stopped не входит в разрешённые Контрактом статусы heartbeat — картридж выйдет, а не рапортует
    assert e.state == "stopped"
    with pytest.raises(ValidationError):
        _validator("telemetry-heartbeat").validate(
            {"status": "stopped", "uptime_s": 1, "contract_version": "v0"}
        )
