"""Гвозди на генератор расчётных периodов (MFC-F3-3, #30/#31): активация (baseline MON3 + гарды),
генератор (bit-в-bit цепочка, pending, терминация, идемпотентность), API. Деньги. Нужен Postgres."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.billing import close_period
from app.db import get_sessionmaker
from app.main import create_app
from app.models import AuditLog, Contract, ExchangeAccount
from app.periods import (
    _month_start,
    _next_month,
    activate_billing,
    generate_due_periods,
    terminate_billing,
)
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
    _truncate()


def _signed_setup(s, currency="USDT"):
    """client + account + signed v1-договор; вернуть (client_id, account_id, contract_id)."""
    cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
    contract = Contract(client_id=cid, status="signed", currency=currency)
    s.add(contract)
    s.flush()
    return cid, aid, contract.id


# ── помощники месяца ──────────────────────────────────────────────────────────

def test_month_helpers() -> None:
    mid = datetime(2026, 7, 15, 13, 30, tzinfo=UTC)
    assert _month_start(mid) == datetime(2026, 7, 1, tzinfo=UTC)
    assert _next_month(datetime(2026, 7, 1, tzinfo=UTC)) == datetime(2026, 8, 1, tzinfo=UTC)
    assert _next_month(datetime(2026, 12, 1, tzinfo=UTC)) == datetime(2027, 1, 1, tzinfo=UTC)


# ── активация ─────────────────────────────────────────────────────────────────

def test_activate_creates_first_period(clean) -> None:
    now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        bp = activate_billing(s, aid, kid, Decimal("10000"), "op", now)
        s.commit()
        assert bp.period_start == datetime(2026, 7, 1, tzinfo=UTC)
        assert bp.period_end == datetime(2026, 8, 1, tzinfo=UTC)
        assert bp.start_equity == Decimal("10000.00") and bp.currency == "USDT"
        acc = s.get(ExchangeAccount, aid)
        assert acc.billing_activated_at == now
        audit = s.execute(
            select(AuditLog).where(AuditLog.action == "billing_activated",
                                   AuditLog.entity == str(aid))
        ).scalar_one()
        assert audit.after["source"] == "operator_baseline"


def test_activate_rejects_unsigned_contract(clean) -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    with get_sessionmaker()() as s:
        cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        draft = Contract(client_id=cid, status="draft")
        s.add(draft)
        s.flush()
        with pytest.raises(ValueError):
            activate_billing(s, aid, draft.id, Decimal("1000"), "op", now)


def test_activate_rejects_wrong_client(clean) -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    with get_sessionmaker()() as s:
        _, aid, kid = _signed_setup(s)          # счёт клиента A + договор A
        cid_b, _ = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        contract_b = Contract(client_id=cid_b, status="signed")  # договор клиента B
        s.add(contract_b)
        s.flush()
        with pytest.raises(ValueError):          # счёт A + договор B → атрибуция
            activate_billing(s, aid, contract_b.id, Decimal("1000"), "op", now)


def test_activate_rejects_v1_incompatible(clean) -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    with get_sessionmaker()() as s:
        cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        bad = Contract(client_id=cid, status="signed", billing_period="quarter")  # прямой обход API
        s.add(bad)
        s.flush()
        with pytest.raises(ValueError):
            activate_billing(s, aid, bad.id, Decimal("1000"), "op", now)


def test_activate_rejects_nonpositive_baseline_and_double(clean) -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        with pytest.raises(ValueError):
            activate_billing(s, aid, kid, Decimal("0"), "op", now)  # baseline > 0
        activate_billing(s, aid, kid, Decimal("1000"), "op", now)
        s.commit()
        with pytest.raises(ValueError):                              # повторная активация
            activate_billing(s, aid, kid, Decimal("2000"), "op", now)


# ── генератор ─────────────────────────────────────────────────────────────────

def _activate(s, aid, kid, equity, month):
    now = datetime(2026, month, 15, tzinfo=UTC)
    return activate_billing(s, aid, kid, Decimal(equity), "op", now)


def test_generate_next_after_close_bit_exact(clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        bp1 = _activate(s, aid, kid, "10000", 7)       # период [2026-07, 2026-08)
        s.commit()
        p1 = bp1.id
    with get_sessionmaker()() as s:                    # закрыть июль +2000
        close_period(s, p1, end_equity=Decimal("12000"), actor="op")
        s.commit()
    with get_sessionmaker()() as s:                    # now в августе → генерируем август
        created = generate_due_periods(s, datetime(2026, 8, 5, tzinfo=UTC))
        s.commit()
        assert len(created) == 1
        bp2 = created[0]
        assert bp2.period_start == datetime(2026, 8, 1, tzinfo=UTC)   # bit-в-bit == prev.end
        assert bp2.start_equity == Decimal("12000.00")               # = prev.end_equity
        assert bp2.currency == "USDT" and bp2.status == "open"


def test_generate_skips_open_prev(clean) -> None:
    # предыдущий период НЕ закрыт → следующий не создаётся (pending)
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        _activate(s, aid, kid, "10000", 7)
        s.commit()
    with get_sessionmaker()() as s:
        assert generate_due_periods(s, datetime(2026, 8, 5, tzinfo=UTC)) == []


def test_generate_skips_future_month(clean) -> None:
    # период закрыт, но месяц ещё не истёк (now до period_end) → не создаём
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        p1 = _activate(s, aid, kid, "10000", 7).id
        s.commit()
    with get_sessionmaker()() as s:
        close_period(s, p1, end_equity=Decimal("11000"), actor="op")
        s.commit()
    with get_sessionmaker()() as s:                    # now всё ещё в июле
        assert generate_due_periods(s, datetime(2026, 7, 20, tzinfo=UTC)) == []


def test_generate_stops_on_termination(clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        p1 = _activate(s, aid, kid, "10000", 7).id
        s.commit()
    with get_sessionmaker()() as s:
        close_period(s, p1, end_equity=Decimal("11000"), actor="op")
        terminate_billing(s, aid, "op", datetime(2026, 7, 31, tzinfo=UTC))
        s.commit()
    with get_sessionmaker()() as s:                    # терминирован → генерации нет
        assert generate_due_periods(s, datetime(2026, 8, 5, tzinfo=UTC)) == []


def test_generate_idempotent(clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        p1 = _activate(s, aid, kid, "10000", 7).id
        s.commit()
    with get_sessionmaker()() as s:
        close_period(s, p1, end_equity=Decimal("12000"), actor="op")
        s.commit()
    with get_sessionmaker()() as s:
        assert len(generate_due_periods(s, datetime(2026, 8, 5, tzinfo=UTC))) == 1
        s.commit()
    with get_sessionmaker()() as s:                    # повтор: последний период открыт → 0
        assert generate_due_periods(s, datetime(2026, 8, 6, tzinfo=UTC)) == []


def test_terminate_guards(clean) -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        with pytest.raises(ValueError):                # не активирован
            terminate_billing(s, aid, "op", now)
        activate_billing(s, aid, kid, Decimal("1000"), "op", now)
        terminate_billing(s, aid, "op", now)
        s.commit()
        with pytest.raises(ValueError):                # повторная терминация
            terminate_billing(s, aid, "op", now)


# ── API ───────────────────────────────────────────────────────────────────────

def _login(c, email, pw) -> dict:
    r = c.post("/v1/auth/login", json={"email": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_activate_endpoint(users, clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        s.commit()
    c = TestClient(create_app())
    h = _login(c, "op@mfc.local", "op-pass")
    body = {"contract_id": str(kid), "start_equity": "10000"}
    r = c.post(f"/v1/exchange-accounts/{aid}/activate-billing", headers=h, json=body)
    assert r.status_code == 201, r.text
    assert c.post(f"/v1/exchange-accounts/{aid}/activate-billing", headers=h,
                  json=body).status_code == 409  # повтор
    # RBAC
    hcl = _login(c, "a@mfc.local", "a-pass")
    assert c.post(f"/v1/exchange-accounts/{aid}/activate-billing", headers=hcl,
                  json=body).status_code == 403
    assert c.post(f"/v1/exchange-accounts/{aid}/activate-billing", json=body).status_code == 401


def test_activate_endpoint_baseline_and_404(users, clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        s.commit()
    c = TestClient(create_app())
    h = _login(c, "op@mfc.local", "op-pass")
    # start_equity <= 0 → 422 (Pydantic gt=0)
    assert c.post(f"/v1/exchange-accounts/{aid}/activate-billing", headers=h,
                  json={"contract_id": str(kid), "start_equity": "0"}).status_code == 422
    # неизвестный счёт → 404
    assert c.post(f"/v1/exchange-accounts/{uuid.uuid4()}/activate-billing", headers=h,
                  json={"contract_id": str(kid), "start_equity": "1000"}).status_code == 404


def test_terminate_endpoint(users, clean) -> None:
    now = datetime(2026, 7, 15, tzinfo=UTC)
    with get_sessionmaker()() as s:
        cid, aid, kid = _signed_setup(s)
        activate_billing(s, aid, kid, Decimal("1000"), "op", now)
        s.commit()
    c = TestClient(create_app())
    h = _login(c, "op@mfc.local", "op-pass")
    r = c.post(f"/v1/exchange-accounts/{aid}/terminate-billing", headers=h)
    assert r.status_code == 200, r.text
    with get_sessionmaker()() as s:
        assert s.get(ExchangeAccount, aid).billing_terminated_at is not None
