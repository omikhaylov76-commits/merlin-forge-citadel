"""Операторский API биллинг-lifecycle счёта (MFC-F3-3): активация (baseline MON3) / терминация.

Только оператор (RBAC). Логика/гарды — в app.periods, аудит там же.
Активация вводит АВТОРИТЕТНЫЙ start_equity (MON3: не телеметрия, вводит Оператор/сверка). Деньги.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_session
from app.models import ExchangeAccount, User
from app.periods import activate_billing, terminate_billing

router = APIRouter(prefix="/v1")


class ActivateBillingIn(BaseModel):
    contract_id: UUID
    # авторитетный baseline (MON3), деньги до цента, положительный, разумный потолок
    start_equity: Decimal = Field(gt=0, le=1_000_000_000, decimal_places=2)


@router.post("/exchange-accounts/{account_id}/activate-billing",
             status_code=status.HTTP_201_CREATED)
def activate_billing_endpoint(
    account_id: UUID,
    body: ActivateBillingIn,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    if session.get(ExchangeAccount, account_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "счёт не найден")
    try:
        bp = activate_billing(
            session, account_id, body.contract_id, body.start_equity,
            str(operator.id), datetime.now(UTC),
        )
    except ValueError as e:  # гарды активации (уже активирован / договор / baseline) → 409
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return {"account_id": str(account_id), "period_id": str(bp.id),
            "period_start": bp.period_start.isoformat(), "start_equity": str(bp.start_equity)}


@router.post("/exchange-accounts/{account_id}/terminate-billing")
def terminate_billing_endpoint(
    account_id: UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    if session.get(ExchangeAccount, account_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "счёт не найден")
    try:
        terminate_billing(session, account_id, str(operator.id), datetime.now(UTC))
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from None
    return {"account_id": str(account_id), "billing_terminated": True}
