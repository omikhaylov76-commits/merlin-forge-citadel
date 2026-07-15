"""Операторский API агрегатов флота (#36) — Обзор консоли. Только чтение (readout).

Деньги/агрегаты считает ядро; фронт отображает (#32). Аудит не нужен (состояние не меняется).
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_session
from app.fleet import fleet_overview
from app.models import User

router = APIRouter(prefix="/v1")


@router.get("/fleet/overview")
def fleet_overview_endpoint(
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    now = datetime.now(UTC)
    return {"as_of": now.isoformat(), **fleet_overview(session)}
