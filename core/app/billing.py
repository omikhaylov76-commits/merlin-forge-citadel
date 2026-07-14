"""Движок биллинга HWM (ADR-0011, финализирована #27).

Две части:
- `compute_period` — ЧИСТАЯ формула (профит-пространство), эталонные тесты Оператора (#27).
- `close_period` — оркестрация: снапшот fee_pct → расчёт → immutable-леджер + аудит.

Модель (ADR-0011): period_net_trading = end_equity − start_equity − net_deposits (потоки клиента НЕ
прибыль/убыток); cum_profit накапливается; комиссия только с прибыли ВЫШЕ пика (перенос убытка);
HWM = max(пик, cum_profit), вниз не идёт. fee_pct — снапшот в период. Деньги — считаем в Decimal.
"""

from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.models import BillingPeriod, Cashflow, Contract

CENTS = Decimal("0.01")


def _q(x: Decimal) -> Decimal:
    # Деньги — до цента, банковское округление не берём (HALF_UP предсказуемее для сверки).
    return Decimal(x).quantize(CENTS, rounding=ROUND_HALF_UP)


def compute_period(
    *,
    start_equity: Decimal,
    end_equity: Decimal,
    net_deposits: Decimal,
    hwm_prev: Decimal,
    cum_profit_prev: Decimal,
    fee_pct: Decimal,
    hurdle_amount: Decimal = Decimal("0"),
) -> dict:
    """Формула ADR-0011. net_deposits = Σ депозитов − Σ выводов за период (может быть <0).
    Возвращает period_net_trading / cum_profit / commission / hwm (все Decimal, до цента)."""
    period_net_trading = _q(end_equity - start_equity - net_deposits)
    cum_profit = _q(cum_profit_prev + period_net_trading)
    taxable = cum_profit - hwm_prev - hurdle_amount        # прибыль сверх пика (и над hurdle)
    commission = _q(fee_pct * taxable) if taxable > 0 else Decimal("0.00")
    hwm = cum_profit if cum_profit > hwm_prev else hwm_prev  # пик вниз не идёт
    return {
        "period_net_trading": period_net_trading,
        "cum_profit": cum_profit,
        "commission": commission,
        "hwm": _q(hwm),
    }


def net_deposits(session: Session, account_id, start: datetime, end: datetime) -> Decimal:
    """Σ депозитов − Σ выводов по счёту в окне [start, end). Потоки в период относим к нему."""
    rows = session.execute(
        select(Cashflow).where(
            Cashflow.account_id == account_id, Cashflow.ts >= start, Cashflow.ts < end
        )
    ).scalars().all()
    total = Decimal("0")
    for cf in rows:
        total += cf.amount if cf.kind == "deposit" else -cf.amount
    return _q(total)


def _prior_state(session: Session, account_id, before: datetime) -> tuple[Decimal, Decimal]:
    """HWM и cum_profit из ПОСЛЕДНЕГО закрытого периода счёта (до `before`). Нет — старт с нуля."""
    row = session.execute(
        select(BillingPeriod)
        .where(
            BillingPeriod.account_id == account_id,
            BillingPeriod.status == "closed",
            BillingPeriod.period_end <= before,
        )
        .order_by(BillingPeriod.period_end.desc())
        .limit(1)
    ).scalar_one_or_none()
    if row is None:
        return Decimal("0"), Decimal("0")
    return row.hwm, (row.cum_profit or Decimal("0"))


def close_period(session: Session, period_id, end_equity: Decimal, actor: str) -> BillingPeriod:
    """Закрыть ОТКРЫТЫЙ период: снапшот fee_pct → расчёт → immutable-леджер + аудит-событие.
    end_equity — авторитетный (реальные деньги — сверка с биржей, MON3; в тестах — засеян)."""
    bp = session.get(BillingPeriod, period_id)
    if bp is None:
        raise ValueError(f"billing_period {period_id} не найден")
    if bp.status != "open":
        raise ValueError(f"billing_period {period_id} уже закрыт (immutable)")
    contract = session.get(Contract, bp.contract_id)
    if contract is None:
        raise ValueError(f"contract {bp.contract_id} не найден")
    end_equity = _q(Decimal(end_equity))
    # hurdle: доля от капитала (v1 hurdle_pct=0 → 0); заложено, не активно.
    hurdle_amount = (
        _q(contract.hurdle_pct * contract.capital) if contract.hurdle_pct else Decimal("0")
    )
    nd = net_deposits(session, bp.account_id, bp.period_start, bp.period_end)
    hwm_prev, cum_prev = _prior_state(session, bp.account_id, bp.period_start)
    r = compute_period(
        start_equity=bp.start_equity,
        end_equity=end_equity,
        net_deposits=nd,
        hwm_prev=hwm_prev,
        cum_profit_prev=cum_prev,
        fee_pct=contract.fee_pct,
        hurdle_amount=hurdle_amount,
    )
    bp.end_equity = end_equity
    bp.net_deposits = nd
    bp.period_net_trading = r["period_net_trading"]
    bp.cum_profit = r["cum_profit"]
    bp.hwm = r["hwm"]
    bp.fee_pct = contract.fee_pct  # СНАПШОТ тарифа в период (не задним числом)
    bp.commission = r["commission"]
    bp.status = "closed"
    bp.closed_at = datetime.now(UTC)
    # Аудит (закон №4): расчёт комиссии — событие; триггер будущих алертов «комиссия рассчитана».
    write_audit(
        session,
        actor=actor,
        action="commission_calculated",
        entity=str(bp.id),
        after={
            "commission": str(r["commission"]),
            "hwm": str(r["hwm"]),
            "cum_profit": str(r["cum_profit"]),
            "fee_pct": str(contract.fee_pct),
            "net_deposits": str(nd),
        },
    )
    session.flush()  # UPDATE open→closed проходит (триггер блокирует лишь OLD.status='closed')
    return bp
