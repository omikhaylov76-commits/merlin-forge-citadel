"""CRM-API оператора (Ф3, MFC-F3-2): CRUD clients / exchange_accounts / contracts.

Только оператор (RBAC, ADR-0008v2). Каждое write-действие → строка аудита (закон №4). Договор —
типизированные условия биллинга; v1-гейт при СОЗДАНИИ и ПОДПИСАНИИ (#29 п.2): единая проверка
billing.v1_unsupported_reason (profit_hwm + HWM + месяц + hurdle/mgmt=0) — иначе fail-loud 422.
Деньги-write (contracts) — под независимым ревью (#29). Ключи биржи тут НЕ вводим (шифр отдельно).
"""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_role
from app.billing import v1_unsupported_reason
from app.db import get_session
from app.models import Client, Contract, ExchangeAccount, User

router = APIRouter(prefix="/v1")

# Допустимые переходы статуса договора (стейт-машина). signed→draft запрещён (сначала suspend).
_STATUS_TRANSITIONS = {
    "draft": {"signed", "suspended"},
    "signed": {"suspended"},
    "suspended": {"signed", "draft"},
}


# ── clients ───────────────────────────────────────────────────────────────────

class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contacts: str | None = None
    contract_ref: str | None = None
    fee_pct_default: Decimal | None = Field(default=None, ge=0, lt=1, decimal_places=4)


@router.post("/clients", status_code=status.HTTP_201_CREATED)
def create_client(
    body: ClientIn,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    client = Client(
        name=body.name, contacts=body.contacts, contract_ref=body.contract_ref,
        fee_pct_default=body.fee_pct_default,
    )
    session.add(client)
    session.flush()
    write_audit(session, actor=str(operator.id), action="client_created", entity=str(client.id),
                after={"name": body.name})
    return {"id": str(client.id), "name": client.name, "is_active": client.is_active}


@router.get("/clients")
def list_clients(
    _: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = session.execute(select(Client).order_by(Client.created_at)).scalars().all()
    return [{"id": str(c.id), "name": c.name, "is_active": c.is_active} for c in rows]


@router.get("/clients/{client_id}")
def get_client(
    client_id: UUID,
    _: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    c = session.get(Client, client_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "клиент не найден")
    return {
        "id": str(c.id), "name": c.name, "contacts": c.contacts, "contract_ref": c.contract_ref,
        "fee_pct_default": (str(c.fee_pct_default) if c.fee_pct_default is not None else None),
        "is_active": c.is_active,
    }


# ── exchange_accounts ─────────────────────────────────────────────────────────

class ExchangeAccountIn(BaseModel):
    client_id: UUID
    exchange: Literal["bybit", "okx", "bitget"]
    label: str | None = Field(default=None, max_length=255)


@router.post("/exchange-accounts", status_code=status.HTTP_201_CREATED)
def create_exchange_account(
    body: ExchangeAccountIn,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    if session.get(Client, body.client_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "клиент не найден")
    # Ключи биржи здесь НЕ принимаем: key_ciphertext — отдельный шифр-путь (ADR-0004), не API.
    acc = ExchangeAccount(client_id=body.client_id, exchange=body.exchange, label=body.label)
    session.add(acc)
    session.flush()
    write_audit(session, actor=str(operator.id), action="exchange_account_created",
                entity=str(acc.id), after={"client_id": str(body.client_id),
                                           "exchange": body.exchange})
    return {"id": str(acc.id), "client_id": str(body.client_id), "exchange": acc.exchange}


@router.get("/clients/{client_id}/exchange-accounts")
def list_accounts(
    client_id: UUID,
    _: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> list[dict]:
    rows = session.execute(
        select(ExchangeAccount).where(ExchangeAccount.client_id == client_id)
    ).scalars().all()
    return [{"id": str(a.id), "exchange": a.exchange, "label": a.label,
             "is_active": a.is_active} for a in rows]


# ── contracts (деньги-write: v1-гейт + независимое ревью) ──────────────────────

class ContractIn(BaseModel):
    client_id: UUID
    payment_model: Literal["profit_hwm", "capital_fixed", "hybrid", "subscription"] = "profit_hwm"
    fee_pct: Decimal = Field(default=Decimal("0.15"), ge=0, lt=1, decimal_places=4)
    high_water_mark: bool = True
    mgmt_fee_pct: Decimal = Field(default=Decimal("0"), ge=0, lt=10, decimal_places=4)
    hurdle_pct: Decimal = Field(default=Decimal("0"), ge=0, lt=10, decimal_places=4)
    billing_period: Literal["month", "quarter"] = "month"
    capital: Decimal = Field(default=Decimal("1000"), ge=500, le=1_000_000_000, decimal_places=2)
    withdrawal_notice_days: int = Field(default=3, ge=0, le=3650)
    currency: Literal["USDT", "USDC"] = "USDT"
    status: Literal["draft", "signed", "suspended"] = "draft"


def _gate_v1(payment_model, hurdle_pct, mgmt_fee_pct, billing_period, high_water_mark) -> None:
    # #29 п.2: единая проверка (та же, что у движка) — нельзя ПОДПИСАТЬ неподдержанный договор.
    reason = v1_unsupported_reason(
        payment_model=payment_model, hurdle_pct=hurdle_pct, mgmt_fee_pct=mgmt_fee_pct,
        billing_period=billing_period, high_water_mark=high_water_mark,
    )
    if reason is not None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"v1: {reason}")


def _one_signed_per_client(session: Session, client_id, exclude_id=None) -> None:
    # ≤1 подписанный договор на клиента — иначе снапшот fee_pct в период неоднозначен (деньги).
    q = select(Contract.id).where(
        Contract.client_id == client_id, Contract.status == "signed"
    )
    if exclude_id is not None:
        q = q.where(Contract.id != exclude_id)
    if session.execute(q.limit(1)).scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "у клиента уже есть подписанный договор")


@router.post("/contracts", status_code=status.HTTP_201_CREATED)
def create_contract(
    body: ContractIn,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    client = session.get(Client, body.client_id)
    if client is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "клиент не найден")
    if not client.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "клиент отключён (is_active=false)")
    _gate_v1(body.payment_model, body.hurdle_pct, body.mgmt_fee_pct, body.billing_period,
             body.high_water_mark)  # гейт уже при создании
    if body.status == "signed":
        _one_signed_per_client(session, body.client_id)
    c = Contract(
        client_id=body.client_id, payment_model=body.payment_model, fee_pct=body.fee_pct,
        high_water_mark=body.high_water_mark, mgmt_fee_pct=body.mgmt_fee_pct,
        hurdle_pct=body.hurdle_pct, billing_period=body.billing_period, capital=body.capital,
        withdrawal_notice_days=body.withdrawal_notice_days, currency=body.currency,
        status=body.status,
    )
    session.add(c)
    try:
        session.flush()
    except IntegrityError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "нарушен инвариант договора") from None
    write_audit(session, actor=str(operator.id), action="contract_created", entity=str(c.id),
                after={"client_id": str(body.client_id), "fee_pct": str(body.fee_pct),
                       "status": body.status})
    return {"id": str(c.id), "client_id": str(body.client_id), "status": c.status,
            "fee_pct": str(c.fee_pct)}


@router.get("/contracts/{contract_id}")
def get_contract(
    contract_id: UUID,
    _: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    c = session.get(Contract, contract_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "договор не найден")
    return {
        "id": str(c.id), "client_id": str(c.client_id), "payment_model": c.payment_model,
        "fee_pct": str(c.fee_pct), "high_water_mark": c.high_water_mark,
        "mgmt_fee_pct": str(c.mgmt_fee_pct), "hurdle_pct": str(c.hurdle_pct),
        "billing_period": c.billing_period, "capital": str(c.capital),
        "withdrawal_notice_days": c.withdrawal_notice_days, "currency": c.currency,
        "status": c.status,
    }


class ContractStatusIn(BaseModel):
    status: Literal["draft", "signed", "suspended"]


@router.patch("/contracts/{contract_id}/status")
def set_contract_status(
    contract_id: UUID,
    body: ContractStatusIn,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    c = session.get(Contract, contract_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "договор не найден")
    if body.status == c.status:
        return {"id": str(c.id), "status": c.status}  # no-op
    if body.status not in _STATUS_TRANSITIONS.get(c.status, set()):
        raise HTTPException(status.HTTP_409_CONFLICT,
                            f"недопустимый переход {c.status}→{body.status}")
    if body.status == "signed":
        client = session.get(Client, c.client_id)
        if client is not None and not client.is_active:  # NEW-1: не подписать отключённому клиенту
            raise HTTPException(status.HTTP_409_CONFLICT, "клиент отключён (is_active=false)")
        _gate_v1(c.payment_model, c.hurdle_pct, c.mgmt_fee_pct, c.billing_period,
                 c.high_water_mark)  # дубль-гейт подписания (#29)
        _one_signed_per_client(session, c.client_id, exclude_id=c.id)
    before = c.status
    c.status = body.status
    write_audit(session, actor=str(operator.id), action="contract_status_changed",
                entity=str(c.id), before={"status": before}, after={"status": body.status})
    try:
        session.flush()
    except IntegrityError:  # гонка partial-unique «≤1 signed/клиент» — backstop БД
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "у клиента уже есть подписанный договор") from None
    return {"id": str(c.id), "status": c.status}
