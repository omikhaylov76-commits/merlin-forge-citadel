"""Эталонные тесты движка биллинга HWM (ADR-0011, закон №8, #27).

Чистые тесты формулы = эталон Оператора (перенос убытка, новые пики, депозит/вывод). Интеграция
close_period = снапшот fee_pct, аудит, перенос HWM между периодами. Деньги — Decimal. Нужен Postgres
для интеграции; чистые тесты — без БД."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text

from app.billing import close_period, compute_period
from app.db import get_sessionmaker
from app.models import AuditLog, BillingPeriod, Cashflow, Contract
from tests.crm_helpers import ensure_parents


def D(x) -> Decimal:
    return Decimal(str(x))


# ── ЧИСТАЯ формула (эталон #27, без БД) ───────────────────────────────────────

def test_ref_loss_carry() -> None:
    # start=10000; м1 7000 (−3000)→ком.0; м2 7000→15000 (+8000)→база 5000, ком.=fee×5000
    fee = D("0.15")
    m1 = compute_period(start_equity=D(10000), end_equity=D(7000), net_deposits=D(0),
                        hwm_prev=D(0), cum_profit_prev=D(0), fee_pct=fee)
    assert m1["period_net_trading"] == D("-3000.00")
    assert m1["cum_profit"] == D("-3000.00")
    assert m1["commission"] == D("0.00")
    assert m1["hwm"] == D("0.00")  # пик не опускается ниже 0
    m2 = compute_period(start_equity=D(7000), end_equity=D(15000), net_deposits=D(0),
                        hwm_prev=m1["hwm"], cum_profit_prev=m1["cum_profit"], fee_pct=fee)
    assert m2["cum_profit"] == D("5000.00")       # перенос убытка: 8000 − 3000
    assert m2["commission"] == D("750.00")        # 0.15 × 5000
    assert m2["hwm"] == D("5000.00")


def test_ref_new_peaks_only() -> None:
    # cum достигает 10000 → комиссия с 10000; затем +3000 → комиссия с 3000 (только новые вершины)
    fee = D("0.15")
    p1 = compute_period(start_equity=D(10000), end_equity=D(20000), net_deposits=D(0),
                        hwm_prev=D(0), cum_profit_prev=D(0), fee_pct=fee)
    assert p1["cum_profit"] == D("10000.00") and p1["commission"] == D("1500.00")
    assert p1["hwm"] == D("10000.00")
    p2 = compute_period(start_equity=D(20000), end_equity=D(23000), net_deposits=D(0),
                        hwm_prev=p1["hwm"], cum_profit_prev=p1["cum_profit"], fee_pct=fee)
    assert p2["cum_profit"] == D("13000.00") and p2["commission"] == D("450.00")  # 0.15×3000
    assert p2["hwm"] == D("13000.00")


def test_below_peak_no_commission() -> None:
    # cum ниже пика → 0, пик держится
    fee = D("0.15")
    r = compute_period(start_equity=D(23000), end_equity=D(21000), net_deposits=D(0),
                       hwm_prev=D(13000), cum_profit_prev=D(13000), fee_pct=fee)
    assert r["cum_profit"] == D("11000.00") and r["commission"] == D("0.00")
    assert r["hwm"] == D("13000.00")  # держится


def test_deposit_not_profit() -> None:
    # депозит 5000 в период, торговли 0 → end=15000; налог 0, планка (в equity) выше на депозит
    r = compute_period(start_equity=D(10000), end_equity=D(15000), net_deposits=D(5000),
                       hwm_prev=D(0), cum_profit_prev=D(0), fee_pct=D("0.15"))
    assert r["period_net_trading"] == D("0.00")   # 15000 − 10000 − 5000
    assert r["commission"] == D("0.00")


def test_withdrawal_not_loss() -> None:
    # торговля +2000 (10000→12000), затем вывод 5000 → end=7000; net_deposits=−5000
    r = compute_period(start_equity=D(10000), end_equity=D(7000), net_deposits=D(-5000),
                       hwm_prev=D(0), cum_profit_prev=D(0), fee_pct=D("0.15"))
    assert r["period_net_trading"] == D("2000.00")  # 7000 − 10000 − (−5000)
    assert r["commission"] == D("300.00")           # 0.15 × 2000 (вывод не убыток)


# ── ИНТЕГРАЦИЯ close_period (Postgres) ────────────────────────────────────────

def _truncate() -> None:
    with get_sessionmaker()() as s:
        s.execute(text(
            "TRUNCATE billing_periods, cashflows, contracts, instances, "
            "exchange_accounts, clients, audit_log CASCADE"
        ))
        s.commit()


@pytest.fixture
def clean(_migrated: None):
    _truncate()
    yield
    _truncate()


def _open_period(s, cid, aid, contract_id, start_equity, start, end):
    bp = BillingPeriod(account_id=aid, client_id=cid, contract_id=contract_id,
                       period_start=start, period_end=end, start_equity=start_equity, status="open")
    s.add(bp)
    s.flush()
    return bp.id


def test_close_period_computes_snapshots_audits(clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        contract = Contract(client_id=cid, fee_pct=D("0.15"))
        s.add(contract)
        s.flush()
        start = datetime.now(UTC) - timedelta(days=30)
        pid = _open_period(s, cid, aid, contract.id, D("10000"), start, datetime.now(UTC))
        s.commit()
    with get_sessionmaker()() as s:
        bp = close_period(s, pid, end_equity=D("12000"), actor="operator:test")
        s.commit()
    with get_sessionmaker()() as s:
        bp = s.get(BillingPeriod, pid)
        assert bp.status == "closed" and bp.commission == D("300.00")  # 0.15×2000
        assert bp.hwm == D("2000.00") and bp.cum_profit == D("2000.00")
        assert bp.fee_pct == D("0.1500")  # снапшот
        audit = s.execute(
            select(AuditLog).where(AuditLog.action == "commission_calculated",
                                   AuditLog.entity == str(pid))
        ).scalar_one()
        assert audit.after["commission"] == "300.00"


def test_fee_pct_snapshot_survives_contract_change(clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        contract = Contract(client_id=cid, fee_pct=D("0.15"))
        s.add(contract)
        s.flush()
        csecid = contract.id
        pid = _open_period(s, cid, aid, contract.id, D("10000"),
                           datetime.now(UTC) - timedelta(days=30), datetime.now(UTC))
        s.commit()
    with get_sessionmaker()() as s:
        close_period(s, pid, end_equity=D("12000"), actor="op")
        s.commit()
    # тариф договора меняется ПОСЛЕ закрытия — закрытый период держит снапшот 0.15
    with get_sessionmaker()() as s:
        s.execute(text("UPDATE contracts SET fee_pct=0.30 WHERE id=:i"), {"i": csecid})
        s.commit()
    with get_sessionmaker()() as s:
        bp = s.get(BillingPeriod, pid)
        assert bp.fee_pct == D("0.1500") and bp.commission == D("300.00")


def test_two_periods_carry_hwm_and_deposit(clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        contract = Contract(client_id=cid, fee_pct=D("0.15"))
        s.add(contract)
        s.flush()
        t0 = datetime.now(UTC) - timedelta(days=60)
        t1 = datetime.now(UTC) - timedelta(days=30)
        t2 = datetime.now(UTC)
        # период 1: 10000 → 7000 (убыток −3000)
        p1 = _open_period(s, cid, aid, contract.id, D("10000"), t0, t1)
        # период 2: старт 7000; депозит 1000; торговля +8000 → end = 7000+8000+1000 = 16000
        p2 = _open_period(s, cid, aid, contract.id, D("7000"), t1, t2)
        s.add(Cashflow(account_id=aid, kind="deposit", amount=D("1000"),
                       ts=t1 + timedelta(days=1), actor="op"))
        s.commit()
    with get_sessionmaker()() as s:
        close_period(s, p1, end_equity=D("7000"), actor="op")
        s.commit()
    with get_sessionmaker()() as s:
        close_period(s, p2, end_equity=D("16000"), actor="op")
        s.commit()
    with get_sessionmaker()() as s:
        bp2 = s.get(BillingPeriod, p2)
        # net_deposits=1000 → period_net_trading = 16000−7000−1000 = 8000; cum = −3000+8000 = 5000
        assert bp2.period_net_trading == D("8000.00")
        assert bp2.net_deposits == D("1000.00")
        assert bp2.cum_profit == D("5000.00")     # перенос убытка периода 1
        assert bp2.commission == D("750.00")       # 0.15 × 5000 (депозит не облагается)


def test_close_rejects_already_closed(clean) -> None:
    with get_sessionmaker()() as s:
        cid, aid = ensure_parents(s, uuid.uuid4(), uuid.uuid4())
        contract = Contract(client_id=cid)
        s.add(contract)
        s.flush()
        pid = _open_period(s, cid, aid, contract.id, D("1000"),
                           datetime.now(UTC) - timedelta(days=30), datetime.now(UTC))
        s.commit()
    with get_sessionmaker()() as s:
        close_period(s, pid, end_equity=D("1100"), actor="op")
        s.commit()
    with get_sessionmaker()() as s:
        with pytest.raises(ValueError):
            close_period(s, pid, end_equity=D("1200"), actor="op")
