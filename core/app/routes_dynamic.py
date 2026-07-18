"""Роутер «Динамика» (S8 «Динамо-близнец», ADR-0020): критерии динамической вселенной на инстанс.

Ядро = ИСТОЧНИК ИСТИНЫ: хранит desired-критерии отбора монет из печки (min_score/stack_max/
fresh_bars) + журнал (audit_log, кто/когда/что→что). Картридж забирает их своим `/self` (boot +
периодический re-fetch) и применяет ЖИВЬЁМ: провайдер читает файл-критерии в каждом `_recompute`,
БЕЗ рестарта (ADR-0020 D1; провайдер — foreground-адаптер, рестарт = смерть контейнера). Поэтому
команды `dynamic_apply` (в отличие от дозора) НЕТ — живое применение обеспечивает re-fetch.

Скоуп канала — ДВИЖКОВЫЙ: что бот БЕРЁТ из печки (какие сетапы вооружает). Дозор-скоуп (что скаут
СМОТРИТ: капитализация/оборот/возраст) — отдельный канал 0018, не смешиваем (ADR-0018 п.3 зеркально).
Только операторский токен (закон №5: портал управляет лишь PAUSE/STOP_CLOSE). Изменение — audit (№4).
Ничего не торгует: критерии — это ОТБОР, дефолт off у флота (DYNAMIC_ENABLED). Дефолты канала =
зеркало генных дефолтов картриджа (ядро молчит/недоступно ≡ ядро с дефолтами — одно поведение).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import current_instance, require_role
from app.db import get_session
from app.models import DynamicSettings as DynamicSettingsRow
from app.models import Instance, User

router = APIRouter(prefix="/v1")

# Дефолты = ГЕННЫЕ дефолты картриджа (app/config.py: dynamic_min_score=0 / dynamic_stack_max=10 /
# dynamic_fresh_bars=0). Нет строки dynamic_settings → отдаём это (== поведению Борса без настроек
# от Оператора): min_score/fresh_bars=0 — без доп-фильтра поверх дозорного порога печки; кап 10.
DYNAMIC_DEFAULTS: dict = {
    "min_score": 0,     # DYNAMIC_MIN_SCORE — доп-порог отбора ПОВЕРХ дозорного (0 = без доп-фильтра)
    "stack_max": 10,    # DYNAMIC_STACK_MAX — предохранитель: макс монет в работе
    "fresh_bars": 0,    # DYNAMIC_FRESH_BARS — свежесть ≤ N баров (0 = без фильтра)
}


class DynamicSettings(BaseModel):
    """Критерии динамической вселенной (валидируются). Границы здравые: кривой ввод не должен ни
    убить провайдера, ни снять предохранитель стека (верхний кап stack_max ОБЯЗАТЕЛЕН)."""

    min_score: int = Field(ge=0, le=1000)     # скор сетапа (как дозорный min_score по шкале)
    stack_max: int = Field(ge=1, le=100)      # предохранитель: 1..100 (100000 НЕ пройдёт — кап есть)
    fresh_bars: int = Field(ge=0, le=100_000)  # 0 = без фильтра свежести


def _require_instance(session: Session, instance_id: uuid.UUID) -> Instance:
    inst = session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такого инстанса")
    return inst


@router.get("/instances/{instance_id}/dynamic/settings")
def get_dynamic_settings(
    instance_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Живые критерии динамики (desired поверх дефолтов) для панели. Чтение — без аудита."""
    _require_instance(session, instance_id)
    row = session.get(DynamicSettingsRow, instance_id)
    settings = {**DYNAMIC_DEFAULTS, **(row.desired if row else {})}
    return {
        "settings": settings,
        "defaults": DYNAMIC_DEFAULTS,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


@router.get("/dynamic/settings/self")
def get_dynamic_settings_self(
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
) -> dict:
    """Картридж читает СВОИ критерии динамики (instance-токен, паттерн /scout/settings/self). Ядро =
    durable-истина; провайдер забирает на boot + периодически (re-fetch), применяет живьём. Страж
    скоупа: отдаём ТОЛЬКО движко-критерии отбора — дозор/риск каналом НЕ ходят (их путь — свои каналы)."""
    row = session.get(DynamicSettingsRow, inst.id)
    return {"settings": {**DYNAMIC_DEFAULTS, **(row.desired if row else {})}}


@router.put("/instances/{instance_id}/dynamic/settings")
def put_dynamic_settings(
    instance_id: uuid.UUID,
    body: DynamicSettings,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Применить критерии: desired (ядро=истина) + журнал audit. Команды НЕТ (живое применение —
    через re-fetch картриджа, ADR-0020 D1/D2). Картридж подхватит за ~интервал re-fetch (минуты)."""
    _require_instance(session, instance_id)
    new = body.model_dump()
    old_row = session.get(DynamicSettingsRow, instance_id)
    before = {**DYNAMIC_DEFAULTS, **(old_row.desired if old_row else {})}

    session.execute(
        pg_insert(DynamicSettingsRow)
        .values(instance_id=instance_id, desired=new, updated_by=operator.id)
        .on_conflict_do_update(
            index_elements=[DynamicSettingsRow.instance_id],
            set_={"desired": new, "updated_by": operator.id, "updated_at": func.now()},
        )
    )
    write_audit(
        session,
        actor=str(operator.id),
        action="dynamic_settings_changed",
        entity=str(instance_id),
        before=before,
        after=new,
    )
    return {"settings": new}
