"""Приём телеметрии бота — шов S4 (→), Контракт Бота v0. Токен принципала `instance`.

Картридж пушит heartbeat/equity/trades/events своим токеном; инстанс берётся ИЗ токена
(current_instance) — instance_id в URL нет, кросс-доступ невозможен (SEC7). Свободные поля
(symbol/note/detail) — недоверенный ввод: храним параметризованно (SQLAlchemy, без инъекций),
экранирование — на ВЫВОДЕ (console/portal), не здесь. Телеметрия идемпотентна: dedup через
ON CONFLICT DO NOTHING по констрейнтам миграции 0004. Аудита на телеметрию НЕТ (не действие
оператора/клиента, закон №4 — про них; иначе флуд). ts бота проверяется на перекос, received_at —
серверное (авторитетно). Батч ограничен (413 → бот дробит).
"""

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth import current_instance
from app.config import Settings, get_settings
from app.db import get_session
from app.models import EquityPoint, Event, Instance, Trade

router = APIRouter(prefix="/v1/telemetry")

_MAX_BATCH = 500  # синхронно с maxItems в contracts/*.schema.json; больше → 413, бот дробит


def _norm(ts: datetime) -> datetime:
    # Наивный ts трактуем как UTC (бот обязан слать ISO с зоной; это защита от рассинхрона типов).
    return ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)


def _check_skew(ts: datetime, now: datetime, skew_s: int) -> None:
    if abs((_norm(ts) - now).total_seconds()) > skew_s:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "ts вне окна приёма (|ts−now| слишком велик)"
        )


def _guard_batch(n: int) -> None:
    if n > _MAX_BATCH:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"батч > {_MAX_BATCH}")


# ── Pydantic-модели = зеркало contracts/*.schema.json (sync-гвоздь в test_telemetry) ──────────

class HeartbeatIn(BaseModel):
    status: Literal["running", "paused", "stopping", "error"]
    uptime_s: float = Field(ge=0)
    contract_version: str
    note: str | None = Field(default=None, max_length=500)


class EquityIn(BaseModel):
    ts: datetime
    equity: Decimal
    currency: Literal["USDT"]  # v0 — только USDT (MON9)
    working: Decimal | None = None
    cushion: Decimal | None = None


class TradeIn(BaseModel):
    ts: datetime
    exec_id: str = Field(max_length=128)
    symbol: str = Field(max_length=40)
    side: Literal["buy", "sell"]
    qty: Decimal = Field(gt=0)
    pnl: Decimal | None = None


class EventIn(BaseModel):
    ts: datetime
    kind: str = Field(max_length=40)
    detail: dict[str, Any] | None = None


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def heartbeat(
    body: HeartbeatIn,
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
) -> None:
    # Единственная функция heartbeat — освежить last_heartbeat_at (кормит stale-скан MFC-003).
    # contract_version в v1 только декларируется (enforcement Ф2); status бота — самооценка.
    inst.last_heartbeat_at = datetime.now(UTC)


@router.post("/equity", status_code=status.HTTP_202_ACCEPTED)
def equity(
    body: EquityIn,
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    _check_skew(body.ts, datetime.now(UTC), settings.telemetry_max_skew_seconds)
    stmt = (
        pg_insert(EquityPoint)
        .values(
            instance_id=inst.id, ts=_norm(body.ts), equity=body.equity,
            currency=body.currency, working=body.working, cushion=body.cushion,
        )
        .on_conflict_do_nothing(constraint="uq_equity_instance_ts")  # dedup (instance, ts)
    )
    session.execute(stmt)
    return {"received": 1}


@router.post("/trades", status_code=status.HTTP_202_ACCEPTED)
def trades(
    body: list[TradeIn],
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    _guard_batch(len(body))
    now = datetime.now(UTC)
    rows = []
    for t in body:
        _check_skew(t.ts, now, settings.telemetry_max_skew_seconds)
        rows.append({
            "instance_id": inst.id, "ts": _norm(t.ts), "exec_id": t.exec_id,
            "symbol": t.symbol, "side": t.side, "qty": t.qty, "pnl": t.pnl,
        })
    if rows:  # dedup по (instance, exec_id биржи) — повторная отправка идемпотентна (COH4)
        session.execute(
            pg_insert(Trade).values(rows).on_conflict_do_nothing(
                constraint="uq_trades_instance_exec"
            )
        )
    return {"received": len(rows)}


@router.post("/events", status_code=status.HTTP_202_ACCEPTED)
def events(
    body: list[EventIn],
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    _guard_batch(len(body))
    now = datetime.now(UTC)
    rows = []
    for e in body:
        _check_skew(e.ts, now, settings.telemetry_max_skew_seconds)
        rows.append({
            "instance_id": inst.id, "ts": _norm(e.ts), "kind": e.kind, "detail": e.detail,
        })
    if rows:  # dedup по (instance, ts, kind)
        session.execute(
            pg_insert(Event).values(rows).on_conflict_do_nothing(
                constraint="uq_events_instance_ts_kind"
            )
        )
    return {"received": len(rows)}
