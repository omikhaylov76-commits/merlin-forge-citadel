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
from sqlalchemy import tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.auth import current_instance
from app.config import Settings, get_settings
from app.db import get_session
from app.models import EngineState, EquityPoint, Event, Instance, ScoutSnapshot, Trade

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


def _check_future_skew(ts: datetime, now: datetime, skew_s: int) -> None:
    """Для ЖУРНАЛОВ (trades/events): прошлое легально — journal-sync движка бэкфиллит историю
    с биржи в свежую БД (редеплой/новый Postgres), и её честные старые ts валидны (дедуп по
    exec_id делает повтор идемпотентным). Запрещаем только будущее за окном (кривые часы бота).
    Живой урок 2026-07-21: строгий skew ронял 422 весь бэкфилл-батч Борса на свежей БД."""
    if (_norm(ts) - now).total_seconds() > skew_s:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "ts из будущего (часы бота врут)"
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


# ── scout-снимок (5-й канал, ADR-0016): ПОЛНОЕ Pydantic-зеркало scout-схемы.
# extra="forbid" — sync-гвоздь: поле в схеме, но не в модели (напр. data_upto), уронит sync-тест. ──

class ScoutLevelIn(BaseModel):
    model_config = {"extra": "forbid"}
    role: Literal["A", "B", "entry_0382", "entry_05", "entry_0618", "stop"]
    price: float = Field(gt=0)


class ScoutKlineIn(BaseModel):
    model_config = {"extra": "forbid", "populate_by_name": True}
    time: int
    o: float
    h: float
    low: float = Field(alias="l")  # 'l' в схеме; alias — ruff E741 (неоднозначное имя)
    c: float
    v: float = Field(ge=0)


class ScoutOrderIn(BaseModel):
    model_config = {"extra": "forbid"}
    order_id: str = Field(max_length=80)
    side: str = Field(max_length=8)     # недоверенный; casing нормализует продюсер
    type: str = Field(max_length=16)
    px: float
    qty: float = Field(gt=0)
    status: str = Field(max_length=24)


class ScoutPositionIn(BaseModel):
    model_config = {"extra": "forbid"}
    side: str = Field(max_length=8)
    avg_px: float
    size: float
    live_pnl: float


class ScoutConfigMismatchIn(BaseModel):
    model_config = {"extra": "forbid"}
    flag: bool
    details: dict[str, Any] | None = None


class ScoutEngineIn(BaseModel):
    """ПРАВДА ДВИЖКА per-coin (S8 единая Разведка): факты warm.classify той же функции, что
    решает постановку. Снимок скаута, не живой тик (дисклеймер — на консоли)."""

    model_config = {"extra": "forbid"}
    kind: Literal["PENDING", "OPEN"] | None  # обязателен И nullable: null = активного сетапа нет
    auto_eligible: bool
    reanchored: bool
    in_universe: bool          # монета в рабочем наборе движка (F-lookahead «мимо списка»)
    side: str | None = Field(default=None, max_length=8)
    age_bars: int | None = Field(default=None, ge=0)
    entries: dict[str, float] | None = None       # {"0.382"/"0.5"/"0.618": цена}
    stop: float | None = Field(default=None, gt=0)
    targets: dict[str, float] | None = None
    est_risk_pct: float | None = None


class ScoutSnapshotIn(BaseModel):
    """Один снимок сетапа per (symbol, tf). Инстанс — из токена (SEC7), в теле его НЕТ."""

    model_config = {"extra": "forbid"}
    symbol: str = Field(max_length=40)              # недоверенный ввод
    tf: Literal["4h", "1h"]
    state: Literal["forming", "tracking", "ready"]
    score: float
    bars_since_anchor: int | None = Field(default=None, ge=0)
    levels: list[ScoutLevelIn] | None = None
    klines_tf: Literal["4h", "1h", "15m", "5m"] | None = None
    klines: list[ScoutKlineIn] | None = None        # кап ≤500 — в ручке (413), не в модели
    orders: list[ScoutOrderIn] | None = None
    position: ScoutPositionIn | None = None
    scan_ts: datetime
    orders_ts: datetime
    data_upto: datetime
    detector_version: str = Field(max_length=40)
    config_fingerprint: str = Field(max_length=80)
    config_mismatch: ScoutConfigMismatchIn
    producer: str = Field(max_length=40)
    # S8/F-scout-snap: levels — реальная сетка сделки движка (warm-реплей) для held-символа,
    # не оценка скаута. Аддитивное поле; None = обычный скаут-снимок.
    verified: bool | None = None
    # S8 единая Разведка: правда движка per-coin (факты warm.classify). None = не посчитана
    # («неизвестно», не «не берёт») — старые картриджи/не-4h находки шлют без ключа.
    engine: ScoutEngineIn | None = None


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
def heartbeat(
    body: HeartbeatIn,
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
) -> None:
    # heartbeat освежает last_heartbeat_at (кормит stale-скан MFC-003). contract_version в v1 только
    # декларируется (enforcement Ф2). Первый heartbeat подтверждает «бот жив»: starting→running.
    inst.last_heartbeat_at = datetime.now(UTC)
    if inst.status == "starting":
        inst.status = "running"


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


_ENGINE_LIST_CAP = 500  # анти-раздувание списков engine_state (позиции/ордера/хвосты)


@router.post("/engine-state", status_code=status.HTTP_202_ACCEPTED)
def engine_state(
    body: dict[str, Any],
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
) -> dict:
    """Приём компакта движкового состояния (карточка бота S7). Replace: ряд на инстанс (upsert).
    payload недоверенный — только храним (экранируется на выводе); секретов картридж не кладёт."""
    for key in ("positions", "orders", "trades", "events"):
        v = body.get(key)
        if isinstance(v, list) and len(v) > _ENGINE_LIST_CAP:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{key}: слишком длинный")
    stk = body.get("stack")  # S8: стек-dict — кап items отдельно (цикл выше ловит только list-поля)
    items = stk.get("items") if isinstance(stk, dict) else None
    if isinstance(items, list) and len(items) > _ENGINE_LIST_CAP:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            "stack.items: слишком длинный")
    now = datetime.now(UTC)
    stmt = (
        pg_insert(EngineState)
        .values(instance_id=inst.id, payload=body, received_at=now)
        .on_conflict_do_update(
            index_elements=["instance_id"], set_={"payload": body, "received_at": now}
        )
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
        _check_future_skew(t.ts, now, settings.telemetry_max_skew_seconds)
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
        _check_future_skew(e.ts, now, settings.telemetry_max_skew_seconds)
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


@router.post("/scout", status_code=status.HTTP_202_ACCEPTED)
def scout(
    body: list[ScoutSnapshotIn],
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
) -> dict:
    # Капы: ≤500 снимков/запрос и ≤500 свечей/снимок → 413 (бот дробит). ts-skew к scan_ts НЕ
    # применяем: сетап мог сформироваться часами раньше (scan_ts законно «старый»).
    _guard_batch(len(body))
    for s in body:
        if s.klines is not None and len(s.klines) > _MAX_BATCH:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"свечей в снимке > {_MAX_BATCH}"
            )
    now = datetime.now(UTC)
    keys = {(s.symbol, s.tf) for s in body}
    for s in body:
        payload = s.model_dump(mode="json", by_alias=True)  # весь снимок как есть (l вместо low)
        session.execute(
            pg_insert(ScoutSnapshot)
            .values(
                instance_id=inst.id, symbol=s.symbol, tf=s.tf, payload=payload,
                scan_ts=_norm(s.scan_ts), orders_ts=_norm(s.orders_ts),
            )
            .on_conflict_do_update(                          # upsert по (instance, symbol, tf)
                constraint="uq_scout_instance_symbol_tf",
                set_={
                    "payload": payload, "scan_ts": _norm(s.scan_ts),
                    "orders_ts": _norm(s.orders_ts), "received_at": now,
                },
            )
        )
    # REPLACE: удалить пары инстанса, выпавшие из присланного набора (сетап умер → строки нет).
    # Пустой набор (все сетапы исчезли) → удаляем все снимки инстанса. Иначе канбан копит трупы.
    q = session.query(ScoutSnapshot).filter(ScoutSnapshot.instance_id == inst.id)
    if keys:
        q = q.filter(tuple_(ScoutSnapshot.symbol, ScoutSnapshot.tf).notin_(list(keys)))
    q.delete(synchronize_session=False)
    return {"received": len(body)}
