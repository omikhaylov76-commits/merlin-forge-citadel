"""Операторский API агрегатов флота (#36) — Обзор консоли. Только чтение (readout).

Деньги/агрегаты считает ядро; фронт отображает (#32). Аудит не нужен (состояние не меняется).
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_role
from app.db import get_session
from app.fleet import fleet_instances, fleet_overview
from app.models import EngineState, ScoutSnapshot, SignalJournalEvent, User

router = APIRouter(prefix="/v1")


@router.get("/fleet/overview")
def fleet_overview_endpoint(
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    now = datetime.now(UTC)
    return {"as_of": now.isoformat(), **fleet_overview(session)}


@router.get("/fleet/instances")
def fleet_instances_endpoint(
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> list[dict]:
    return fleet_instances(session)


@router.get("/instances/{instance_id}/engine-state")
def instance_engine_state_endpoint(
    instance_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Последнее движковое состояние инстанса (карточка бота S7). payload как есть (недоверенный,
    экранируется на выводе консоли) + серверный received_at. Нет данных → state=None."""
    es = session.get(EngineState, instance_id)
    if es is None:
        return {"instance_id": str(instance_id), "state": None, "received_at": None}
    return {
        "instance_id": str(instance_id),
        "received_at": es.received_at.isoformat() if es.received_at else None,
        "state": es.payload,
    }


@router.get("/instances/{instance_id}/scout")
def instance_scout_endpoint(
    instance_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Снимки сетапов скаута инстанса (readout, ADR-0016). payload как есть + серверный received_at.
    Свободные поля (symbol/producer) — экранируются на ВЫВОДЕ (консоль #53), не здесь."""
    rows = session.execute(
        select(ScoutSnapshot)
        .where(ScoutSnapshot.instance_id == instance_id)
        .order_by(ScoutSnapshot.symbol, ScoutSnapshot.tf)
    ).scalars().all()
    return [{**r.payload, "received_at": r.received_at.isoformat()} for r in rows]


@router.get("/instances/{instance_id}/signal-journal")
def instance_signal_journal_endpoint(
    instance_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    limit: int = 200,
) -> list[dict]:
    """Лента событий Сигнального журнала инстанса (порция №3, read-only). Новые сверху по seq.
    data/setup_id/symbol — недоверенный ввод, экранируется на ВЫВОДЕ консоли (не здесь)."""
    rows = session.execute(
        select(SignalJournalEvent)
        .where(SignalJournalEvent.instance_id == instance_id)
        .order_by(SignalJournalEvent.seq.desc())
        .limit(min(max(limit, 1), 1000))
    ).scalars().all()
    return [{
        "seq": r.seq, "core": r.core, "ts": r.ts.isoformat(), "setup_id": r.setup_id,
        "kind": r.kind, "src": {"table": r.src_table, "id": r.src_id}, "data": r.data,
        "received_at": r.received_at.isoformat() if r.received_at else None,
    } for r in rows]
