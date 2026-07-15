"""Жизненный цикл расчётных периодов биллинга (MFC-F3-3, ратифицировано #30/#31).

- activate_billing — операторская активация счёта (baseline MON3) → ПЕРВЫЙ период.
- generate_due_periods — свёртка часового: СЛЕДУЮЩИЙ период после закрытия предыдущего.
- terminate_billing — операторская терминация (генерация останавливается; пауза ≠ терминация).

Границы месяца UTC, бит-в-bit (start==prev.end), no backdating, валюта из договора. Деньги: ревью.
"""

import logging
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.billing import v1_unsupported_reason
from app.models import AuditLog, BillingPeriod, Contract, ExchangeAccount

logger = logging.getLogger("mfc.periods")


def _month_start(dt: datetime) -> datetime:
    if dt.tzinfo is None:  # naive → astimezone принял бы за локаль и сдвинул границу месяца
        raise ValueError("datetime должен быть tz-aware (UTC)")
    return dt.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _next_month(ms: datetime) -> datetime:
    # ms — начало месяца; вернуть начало следующего (перенос года на декабре).
    if ms.month == 12:
        return ms.replace(year=ms.year + 1, month=1)
    return ms.replace(month=ms.month + 1)


def _signed_contract(session: Session, client_id):
    return session.execute(
        select(Contract).where(Contract.client_id == client_id, Contract.status == "signed")
    ).scalar_one_or_none()


def _last_period(session: Session, account_id):
    return session.execute(
        select(BillingPeriod)
        .where(BillingPeriod.account_id == account_id)
        .order_by(BillingPeriod.period_end.desc())
        .limit(1)
    ).scalar_one_or_none()


def _active_billing_accounts(session: Session):
    """Счета с активным биллингом (activated и не terminated) — на них работает генератор."""
    return session.execute(
        select(ExchangeAccount).where(
            ExchangeAccount.billing_activated_at.is_not(None),
            ExchangeAccount.billing_terminated_at.is_(None),
        )
    ).scalars().all()


def _blocked_reason(prev: BillingPeriod, contract: Contract | None) -> str | None:
    """ЕДИНЫЙ источник решения: почему DUE-счёт (prev закрыт, месяц истёк) не даёт период.
    None → период создаётся. Иначе счёт застрял (pending). Порядок причин важен (аудит)."""
    if prev.end_equity is None:  # аномалия: период закрыт без авторитетного equity
        return "closed_without_equity"
    if contract is None:  # нет подписанного договора → биллинг застрял
        return "no_signed_contract"
    if contract.currency != prev.currency:  # смена валюты договора → терминация+новый счёт
        return "currency_changed"
    return None


def _skip_payload(prev: BillingPeriod, contract: Contract | None, reason: str) -> dict:
    payload = {"reason": reason, "pending_period_start": prev.period_end.isoformat()}
    if reason == "currency_changed":  # контекст расхождения — оператору сразу видно, что чинить
        payload["prev_currency"] = prev.currency
        payload["contract_currency"] = contract.currency if contract else None
    return payload


def _last_skip_audit(session: Session, entity: str):
    return session.execute(
        select(AuditLog)
        .where(AuditLog.action == "period_generation_skipped", AuditLog.entity == entity)
        .order_by(AuditLog.ts.desc())
        .limit(1)
    ).scalar_one_or_none()


def _record_skip(session: Session, account: ExchangeAccount, prev: BillingPeriod,
                 contract: Contract | None, reason: str) -> None:
    """Зафиксировать застрявший счёт: WARNING-лог (реалтайм) + audit-событие (дюрабельный след).
    Дедуп: один audit на (счёт, граница pending, причина) — часовой не спамит одинаковой строкой
    каждый тик, пока счёт застрял; смена причины/границы → новая строка (значимое событие)."""
    payload = _skip_payload(prev, contract, reason)
    logger.warning("счёт %s: биллинг застрял (%s), период с %s не создан",
                   account.id, reason, payload["pending_period_start"])
    last = _last_skip_audit(session, str(account.id))
    if last is not None and last.after \
            and last.after.get("reason") == reason \
            and last.after.get("pending_period_start") == payload["pending_period_start"]:
        return  # уже зафиксировано для этой границы+причины
    write_audit(session, actor="system:period-generator",
                action="period_generation_skipped", entity=str(account.id), after=payload)


def activate_billing(session: Session, account_id, contract_id, start_equity, actor: str, now):
    """Активация биллинга счёта (операторская, baseline MON3). Создаёт ПЕРВЫЙ период календарного
    месяца [начало, +1мес) со start_equity=baseline, валюта из договора. Гарды: договор signed и
    v1-совместим; счёт клиента договора; start_equity>0; идемпотентность (повтор→ошибка)."""
    account = session.get(ExchangeAccount, account_id)
    if account is None:
        raise ValueError("счёт не найден")
    if account.billing_activated_at is not None:
        raise ValueError("биллинг счёта уже активирован")
    contract = session.get(Contract, contract_id)
    if contract is None:
        raise ValueError("договор не найден")
    if contract.status != "signed":
        raise ValueError("договор не подписан (signed)")
    if contract.client_id != account.client_id:
        raise ValueError("договор принадлежит другому клиенту")
    reason = v1_unsupported_reason(
        payment_model=contract.payment_model, hurdle_pct=contract.hurdle_pct,
        mgmt_fee_pct=contract.mgmt_fee_pct, billing_period=contract.billing_period,
        high_water_mark=contract.high_water_mark,
    )
    if reason is not None:
        raise ValueError(f"v1: {reason}")
    start_equity = Decimal(str(start_equity))
    if start_equity <= 0:
        raise ValueError("start_equity должен быть > 0 (авторитетный baseline)")
    ps = _month_start(now)
    bp = BillingPeriod(
        account_id=account_id, client_id=account.client_id, contract_id=contract_id,
        period_start=ps, period_end=_next_month(ps), start_equity=start_equity,
        currency=contract.currency, status="open",
    )
    session.add(bp)
    account.billing_activated_at = now
    session.flush()
    write_audit(session, actor=actor, action="billing_activated", entity=str(account_id),
                after={"start_equity": str(start_equity), "contract_id": str(contract_id),
                       "period_start": ps.isoformat(), "source": "operator_baseline"})
    return bp


def terminate_billing(session: Session, account_id, actor: str, now):
    """Терминация биллинга счёта: генерация периодов останавливается. Текущий открытый период —
    финальный (закрывается авторитетным equity как обычно). Пауза ≠ терминация."""
    account = session.get(ExchangeAccount, account_id)
    if account is None:
        raise ValueError("счёт не найден")
    if account.billing_activated_at is None:
        raise ValueError("биллинг счёта не активирован")
    if account.billing_terminated_at is not None:
        raise ValueError("биллинг счёта уже терминирован")
    account.billing_terminated_at = now
    session.flush()
    write_audit(session, actor=actor, action="billing_terminated", entity=str(account_id),
                after={"terminated_at": now.isoformat()})
    return account


def generate_due_periods(session: Session, now: datetime) -> list:
    """Активным (не терминированным) счетам, чей ПОСЛЕДНИЙ период ЗАКРЫТ и истёк (period_end<=now) →
    создать СЛЕДУЮЩИЙ период [prev.end, +1мес), start_equity=prev.end_equity, валюта из подписанного
    договора клиента. Пауза НЕ пропускает; терминация останавливает; bit-в-bit (start==prev.end);
    no backdating; предыдущий открыт / нет equity/договора / смена валюты → не создаём (pending)."""
    created = []
    for account in _active_billing_accounts(session):
        prev = _last_period(session, account.id)
        if prev is None or prev.status != "closed" or prev.period_end > now:
            continue  # нет периода / предыдущий открыт / месяц не истёк → pending (норма, без шума)
        contract = _signed_contract(session, account.client_id)
        reason = _blocked_reason(prev, contract)
        if reason is not None:  # DUE, но застрял → видимость (audit+WARNING), период не создаём
            _record_skip(session, account, prev, contract, reason)
            continue
        ps = prev.period_end  # bit-в-bit: старт нового == конец предыдущего
        try:
            with session.begin_nested():  # savepoint: сбой одного счёта не роняет весь батч
                bp = BillingPeriod(
                    account_id=account.id, client_id=account.client_id, contract_id=contract.id,
                    period_start=ps, period_end=_next_month(ps), start_equity=prev.end_equity,
                    currency=contract.currency, status="open",
                )
                session.add(bp)
                session.flush()
            created.append(bp)
        except (IntegrityError, OperationalError):  # DB-сбой (гонка) → изолируем счёт, не батч
            logger.warning("счёт %s: создание периода не удалось (DB)", account.id, exc_info=True)
    return created


def stuck_billing_accounts(session: Session, now: datetime) -> list[dict]:
    """Readout операторской видимости (#32): активные счета, чей следующий период ДОЛЖЕН был
    сгенериться (prev закрыт, месяц истёк), но застрял (нет equity/договора/смена валюты).
    Только чтение, без эффектов; решение о «застрял» общее с генератором (_blocked_reason)."""
    stuck = []
    for account in _active_billing_accounts(session):
        prev = _last_period(session, account.id)
        if prev is None or prev.status != "closed" or prev.period_end > now:
            continue  # не due (норма) — не «застрял»
        contract = _signed_contract(session, account.client_id)
        reason = _blocked_reason(prev, contract)
        if reason is None:
            continue  # следующий период создаётся штатно — не застрял
        stuck.append({
            "account_id": str(account.id), "client_id": str(account.client_id),
            "exchange": account.exchange, "label": account.label,
            **_skip_payload(prev, contract, reason),
        })
    return stuck


def generate_periods_once(sessionmaker_, now: datetime | None = None) -> int:
    """Свёртка для часового: сессия → генерация → коммит. Возвращает число созданных."""
    now = now or datetime.now(UTC)
    with sessionmaker_() as session:
        n = len(generate_due_periods(session, now))
        session.commit()
    return n
