"""Гвозди на схему биллинга Ф3 (миграция 0006): таблицы contracts/billing_periods/cashflows,
CHECK (fee/capital/enum/amount), FK, immutability ЗАКРЫТОГО периода (триггер). Нужен Postgres.

Чистка — фикстура `clean` (setup+teardown) через TRUNCATE ... CASCADE: TRUNCATE обходит row-триггер
immutability (иначе закрытый период не удалить), teardown не даёт billing-строкам утечь в другие файлы
(их FK на clients/exchange_accounts иначе ломает DELETE-чистку соседних тестов)."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import get_sessionmaker
from app.models import BillingPeriod, Cashflow, Contract
from tests.crm_helpers import ensure_parents


def _truncate() -> None:
    with get_sessionmaker()() as s:
        s.execute(text(
            "TRUNCATE billing_periods, cashflows, contracts, instances, "
            "exchange_accounts, clients CASCADE"
        ))
        s.commit()


@pytest.fixture
def clean(_migrated: None):
    _truncate()
    yield
    _truncate()  # teardown: убрать даже закрытый период (TRUNCATE минует триггер)


def _mk_contract_parents(s):
    cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
    c = Contract(client_id=cid)
    s.add(c)
    s.flush()
    return cid, aid, c.id


def test_billing_tables_exist(_migrated) -> None:
    with get_sessionmaker()() as s:
        for t in ("contracts", "billing_periods", "cashflows"):
            assert s.execute(text(f"SELECT to_regclass('{t}')")).scalar() is not None, t


def test_contract_defaults(clean) -> None:
    with get_sessionmaker()() as s:
        cid, _ = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        c = Contract(client_id=cid)
        s.add(c)
        s.commit()  # server_default'ы читаются после commit (expire_on_commit)
        assert c.fee_pct == Decimal("0.1500") and c.payment_model == "profit_hwm"
        assert c.capital == Decimal("1000.00") and c.billing_period == "month"
        assert c.high_water_mark is True and c.currency == "USDT" and c.status == "draft"


def test_contract_fee_pct_out_of_range(clean) -> None:
    with get_sessionmaker()() as s:
        cid, _ = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        s.add(Contract(client_id=cid, fee_pct=Decimal("1.5")))  # ≥1 нельзя
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_contract_capital_floor(clean) -> None:
    with get_sessionmaker()() as s:
        cid, _ = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        s.add(Contract(client_id=cid, capital=Decimal("100")))  # < floor 500
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_contract_enum_check(clean) -> None:
    with get_sessionmaker()() as s:
        cid, _ = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        s.add(Contract(client_id=cid, payment_model="ponzi"))  # не из списка
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_cashflow_kind_and_amount_checks(clean) -> None:
    with get_sessionmaker()() as s:
        _, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        s.add(Cashflow(account_id=aid, kind="bribe", amount=Decimal("10"),
                       ts=datetime.now(UTC), actor="op"))  # kind не из списка
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()
    with get_sessionmaker()() as s:
        _, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        s.add(Cashflow(account_id=aid, kind="deposit", amount=Decimal("0"),
                       ts=datetime.now(UTC), actor="op"))  # amount > 0
        with pytest.raises(IntegrityError):
            s.flush()
        s.rollback()


def test_billing_period_requires_parents(clean) -> None:
    with get_sessionmaker()() as s:
        s.add(BillingPeriod(
            account_id=uuid.uuid4(), client_id=uuid.uuid4(), contract_id=uuid.uuid4(),
            period_start=datetime.now(UTC), period_end=datetime.now(UTC),
            start_equity=Decimal("1000"),
        ))
        with pytest.raises(IntegrityError):  # FK на несуществующих родителей
            s.flush()
        s.rollback()


def test_open_period_closes_then_immutable(clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid, contract_id = _mk_contract_parents(s)
        bp = BillingPeriod(
            account_id=aid, client_id=cid, contract_id=contract_id,
            period_start=datetime.now(UTC) - timedelta(days=30),
            period_end=datetime.now(UTC), start_equity=Decimal("1000"), status="open",
        )
        s.add(bp)
        s.commit()
        bp_id = bp.id
    # open → закрыть: РАЗРЕШЕНО (OLD.status='open')
    with get_sessionmaker()() as s:
        s.execute(
            text("UPDATE billing_periods SET status='closed', commission=100 WHERE id=:i"),
            {"i": bp_id},
        )
        s.commit()
    # closed → UPDATE ЗАПРЕЩЁН (триггер immutability)
    with get_sessionmaker()() as s:
        with pytest.raises(DBAPIError):
            s.execute(text("UPDATE billing_periods SET commission=999 WHERE id=:i"), {"i": bp_id})
            s.commit()
        s.rollback()
    # closed → DELETE ЗАПРЕЩЁН
    with get_sessionmaker()() as s:
        with pytest.raises(DBAPIError):
            s.execute(text("DELETE FROM billing_periods WHERE id=:i"), {"i": bp_id})
            s.commit()
        s.rollback()
