"""CRM-API оператора (Ф3, MFC-F3-2): CRUD clients / exchange_accounts / contracts.

Только оператор (RBAC, ADR-0008v2). Каждое write-действие → строка аудита (закон №4). Договор —
типизированные условия биллинга; v1-гейт при СОЗДАНИИ и ПОДПИСАНИИ (#29 п.2): поддержан только
payment_model=profit_hwm, hurdle=0, mgmt=0 — иначе fail-loud (нельзя подписать неподдержанный).
Деньги-write (contracts) — под независимым ревью (#29). Ключи биржи тут НЕ вводим (шифр отдельно).
"""

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_role
from app.db import get_session
from app.models import Client, Contract, ExchangeAccount, User

router = APIRouter(prefix="/v1")


# ── clients ───────────────────────────────────────────────────────────────────

class ClientIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contacts: str | None = None
    contract_ref: str | None = None
    fee_pct_default: Decimal | None = Field(default=None, ge=0, lt=1)


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
    client_id: str,
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
    client_id: str
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
                entity=str(acc.id), after={"client_id": body.client_id, "exchange": body.exchange})
    return {"id": str(acc.id), "client_id": body.client_id, "exchange": acc.exchange}


@router.get("/clients/{client_id}/exchange-accounts")
def list_accounts(
    client_id: str,
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
    client_id: str
    payment_model: Literal["profit_hwm", "capital_fixed", "hybrid", "subscription"] = "profit_hwm"
    fee_pct: Decimal = Field(default=Decimal("0.15"), ge=0, lt=1)
    high_water_mark: bool = True
    mgmt_fee_pct: Decimal = Field(default=Decimal("0"), ge=0)
    hurdle_pct: Decimal = Field(default=Decimal("0"), ge=0)
    billing_period: Literal["month", "quarter"] = "month"
    capital: Decimal = Field(default=Decimal("1000"), ge=500)
    withdrawal_notice_days: int = Field(default=3, ge=0)
    currency: Literal["USDT", "USDC"] = "USDT"
    status: Literal["draft", "signed", "suspended"] = "draft"


def _validate_v1(payment_model: str, hurdle_pct: Decimal, mgmt_fee_pct: Decimal) -> None:
    # #29 п.2: нельзя подписать неподдержанный договор → fail-loud уже на создании/подписании.
    if payment_model != "profit_hwm":
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"v1: payment_model={payment_model} не поддержан"
        )
    if hurdle_pct != 0 or mgmt_fee_pct != 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "v1: hurdle_pct и mgmt_fee_pct должны быть 0"
        )


@router.post("/contracts", status_code=status.HTTP_201_CREATED)
def create_contract(
    body: ContractIn,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    if session.get(Client, body.client_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "клиент не найден")
    _validate_v1(body.payment_model, body.hurdle_pct, body.mgmt_fee_pct)  # гейт уже при создании
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
                after={"client_id": body.client_id, "fee_pct": str(body.fee_pct),
                       "status": body.status})
    return {"id": str(c.id), "client_id": body.client_id, "status": c.status,
            "fee_pct": str(c.fee_pct)}


@router.get("/contracts/{contract_id}")
def get_contract(
    contract_id: str,
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
    contract_id: str,
    body: ContractStatusIn,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    c = session.get(Contract, contract_id)
    if c is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "договор не найден")
    if body.status == "signed":
        _validate_v1(c.payment_model, c.hurdle_pct, c.mgmt_fee_pct)  # дубль-гейт подписания (#29)
    before = c.status
    c.status = body.status
    write_audit(session, actor=str(operator.id), action="contract_status_changed",
                entity=str(c.id), before={"status": before}, after={"status": body.status})
    session.flush()
    return {"id": str(c.id), "status": c.status}
