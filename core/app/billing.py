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
) -> dict:
    """Формула ADR-0011 (v1, hurdle/mgmt=0). net_deposits = Σ деп. − Σ выводов за период (<0 ок).
    Возвращает period_net_trading / cum_profit / commission / hwm (все Decimal, до цента).
    hurdle/mgmt в v1 НЕ реализованы (гейт в close_period), корректная семантика — будущая версия."""
    period_net_trading = _q(end_equity - start_equity - net_deposits)
    cum_profit = _q(cum_profit_prev + period_net_trading)
    taxable = cum_profit - hwm_prev                         # прибыль сверх исторического пика
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


def _prior_period(session: Session, account_id, before: datetime):
    """Непосредственно предшествующий период счёта (по period_end, БЕЗ фильтра статуса — ловим
    незакрытый предыдущий). None — текущий период первый для счёта."""
    return session.execute(
        select(BillingPeriod)
        .where(BillingPeriod.account_id == account_id, BillingPeriod.period_end <= before)
        .order_by(BillingPeriod.period_end.desc())
        .limit(1)
    ).scalar_one_or_none()


def close_period(session: Session, period_id, end_equity: Decimal, actor: str) -> BillingPeriod:
    """Закрыть ОТКРЫТЫЙ период: снапшот fee_pct → расчёт → immutable-леджер + аудит-событие.
    end_equity — авторитетный (реальные деньги — сверка с биржей, MON3; в тестах — засеян).
    Инварианты (деньги): период под FOR UPDATE; закрывать СТРОГО ПО ПОРЯДКУ (предыдущий закрыт и
    примыкает); v1 — только payment_model=profit_hwm, hurdle/mgmt=0 (иначе тихий недосчёт)."""
    bp = session.execute(
        select(BillingPeriod).where(BillingPeriod.id == period_id).with_for_update()
    ).scalar_one_or_none()
    if bp is None:
        raise ValueError(f"billing_period {period_id} не найден")
    if bp.status != "open":
        raise ValueError(f"billing_period {period_id} уже закрыт (immutable)")
    contract = session.get(Contract, bp.contract_id)
    if contract is None:
        raise ValueError(f"contract {bp.contract_id} не найден")
    # v1-гейт: неподдержанные условия НЕ считаем молча (недосчёт комиссии/mgmt-fee = потеря денег).
    if contract.payment_model != "profit_hwm":
        raise ValueError(f"v1: payment_model={contract.payment_model} не реализован")
    if contract.hurdle_pct != 0 or contract.mgmt_fee_pct != 0:
        raise ValueError("v1: hurdle_pct и mgmt_fee_pct должны быть 0 (не реализованы)")
    # Порядок: более раннего НЕзакрытого периода счёта быть не должно (иначе рвётся цепочка HWM).
    earlier_open = session.execute(
        select(BillingPeriod.id).where(
            BillingPeriod.account_id == bp.account_id,
            BillingPeriod.status == "open",
            BillingPeriod.period_start < bp.period_start,
        ).limit(1)
    ).scalar_one_or_none()
    if earlier_open is not None:
        raise ValueError("есть более ранний незакрытый период — закрывать по порядку")
    # Состояние — из НЕПОСРЕДСТВЕННО предшествующего периода; он обязан быть закрыт и примыкать.
    prior = _prior_period(session, bp.account_id, bp.period_start)
    if prior is None:
        hwm_prev, cum_prev = Decimal("0"), Decimal("0")
    else:
        if prior.status != "closed":
            raise ValueError("предыдущий период не закрыт — закрывать по порядку")
        if prior.period_end != bp.period_start:
            raise ValueError("разрыв периодов: предыдущий не примыкает к текущему")
        hwm_prev = prior.hwm
        cum_prev = prior.cum_profit if prior.cum_profit is not None else Decimal("0")
    end_equity = _q(Decimal(str(end_equity)))  # безопасная нормализация (float на входе → мусор)
    nd = net_deposits(session, bp.account_id, bp.period_start, bp.period_end)
    r = compute_period(
        start_equity=bp.start_equity,
        end_equity=end_equity,
        net_deposits=nd,
        hwm_prev=hwm_prev,
        cum_profit_prev=cum_prev,
        fee_pct=contract.fee_pct,
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
