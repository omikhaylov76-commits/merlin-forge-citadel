"""Роутер «Разведка-стол» (S7): настройки дозора (скаута) + кнопка «Сканировать сейчас».

Ядро = ИСТОЧНИК ИСТИНЫ (Q4 Куратора): хранит desired-пороги (scout_settings) + журнал (audit_log,
кто/когда/что→что) и доставляет их картриджу командой `dozor_apply` (паттерн screener_run); картридж
применяет env-оверрайдами и рестартит ТОЛЬКО скаут. `scan_now` — команда «сканировать сейчас»
(картридж пишет триггер в scout_control вендора). Только операторский токен (закон №5). Пороги — это
ОТБОР скаута (какие монеты смотреть), НЕ торговля: ничего не торгует. Изменение — audit (№4).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import require_role
from app.db import get_session
from app.models import AuditLog, Command, Instance, ScoutSettings, User

router = APIRouter(prefix="/v1")

# Дефолты = ФАКТ Галахада: start.sh поверх vendor (list=50, rps=1), остальное — дефолты vendor
# scout/config.py. Нет строки scout_settings → отдаём это (совпадает с тем, что бежит на скауте).
SCOUT_DEFAULTS: dict = {
    "min_age_days": 180,          # SCOUT_MIN_AGE_DAYS
    "min_turnover_usd": 5_000_000,  # SCOUT_MIN_TURNOVER_USD
    "max_spread_pct": 0.15,       # SCOUT_MAX_SPREAD_PCT
    "min_history_bars": 300,      # SCOUT_MIN_HISTORY_BARS
    "min_score": 35,              # SCOUT_MIN_SCORE
    "universe_max": 300,          # SCOUT_UNIVERSE_MAX
    "list_max": 50,               # SCOUT_LIST_MAX (start.sh поверх vendor 200)
    "tfs": ["4h", "1h"],          # SCOUT_TFS (что сканим)
    "primary_tf": "4h",           # SCOUT_TF (primary; "1h" → часовой автоскан)
    "fresh_bars": 72,             # SCOUT_FRESH_BARS
    "scan_bars": 300,             # SCOUT_SCAN_BARS
    "cal_bars": 1000,             # SCOUT_CAL_BARS (эксперт)
    "cal_utc_hour": 5,            # SCOUT_CAL_UTC_HOUR (05:00 UTC = 08:00 МСК)
    "rps": 1,                     # SCOUT_RPS (start.sh поверх vendor 3; эксперт)
}

_TF = {"4h", "1h"}


class DozorSettings(BaseModel):
    """Пороги дозора (валидируются). Границы — здравые, чтобы кривой ввод не убил скаут."""

    min_age_days: int = Field(ge=0, le=100_000)
    min_turnover_usd: int = Field(ge=0, le=10**12)
    max_spread_pct: float = Field(gt=0, le=100)
    min_history_bars: int = Field(ge=1, le=100_000)
    min_score: int = Field(ge=0, le=1000)
    universe_max: int = Field(ge=1, le=5000)
    list_max: int = Field(ge=1, le=5000)
    tfs: list[str] = Field(min_length=1)
    primary_tf: str
    fresh_bars: int = Field(ge=1, le=100_000)
    scan_bars: int = Field(ge=1, le=100_000)
    cal_bars: int = Field(ge=1, le=1_000_000)
    cal_utc_hour: int = Field(ge=0, le=23)
    rps: int = Field(ge=1, le=10)

    @field_validator("tfs")
    @classmethod
    def _tfs_ok(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in _TF]
        if bad:
            raise ValueError(f"недопустимые ТФ: {bad}")
        return list(dict.fromkeys(v))  # дедуп, порядок сохранён

    @field_validator("primary_tf")
    @classmethod
    def _primary_tf_ok(cls, v: str) -> str:
        if v not in _TF:
            raise ValueError("primary_tf ∈ {4h,1h}")
        return v

    @model_validator(mode="after")
    def _primary_in_tfs(self) -> DozorSettings:
        if self.primary_tf not in self.tfs:
            raise ValueError("primary_tf должен быть среди tfs")
        return self


def _apply_status(session: Session, instance_id: uuid.UUID) -> dict:
    """Статус последней команды dozor_apply — для строки дозора («применяется…/расхождение»)."""
    cmd = session.execute(
        select(Command)
        .where(Command.instance_id == instance_id, Command.kind == "dozor_apply")
        .order_by(Command.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    if cmd is None:
        return {"status": "none"}
    return {
        "status": cmd.status,  # queued|delivered|acked|failed
        "at": cmd.created_at.isoformat() if cmd.created_at else None,
    }


def _require_instance(session: Session, instance_id: uuid.UUID) -> Instance:
    inst = session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такого инстанса")
    return inst


@router.get("/instances/{instance_id}/scout/settings")
def get_scout_settings(
    instance_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Живые настройки дозора (desired поверх дефолтов) + статус применения. Чтение — без аудита."""
    _require_instance(session, instance_id)
    row = session.get(ScoutSettings, instance_id)
    settings = {**SCOUT_DEFAULTS, **(row.desired if row else {})}
    return {
        "settings": settings,
        "defaults": SCOUT_DEFAULTS,
        "apply": _apply_status(session, instance_id),
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


@router.put("/instances/{instance_id}/scout/settings")
def put_scout_settings(
    instance_id: uuid.UUID,
    body: DozorSettings,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Применить пороги: desired (ядро=истина) + журнал + команда картриджу dozor_apply."""
    _require_instance(session, instance_id)
    new = body.model_dump()
    old_row = session.get(ScoutSettings, instance_id)
    before = {**SCOUT_DEFAULTS, **(old_row.desired if old_row else {})}

    session.execute(
        pg_insert(ScoutSettings)
        .values(instance_id=instance_id, desired=new, updated_by=operator.id)
        .on_conflict_do_update(
            index_elements=[ScoutSettings.instance_id],
            set_={"desired": new, "updated_by": operator.id, "updated_at": func.now()},
        )
    )
    session.add(
        Command(
            instance_id=instance_id, kind="dozor_apply", status="queued",
            payload={"settings": new},
        )
    )
    write_audit(
        session,
        actor=str(operator.id),
        action="scout_settings_changed",
        entity=str(instance_id),
        before=before,
        after=new,
    )
    return {"settings": new, "apply": {"status": "queued"}}


@router.post("/instances/{instance_id}/scout/scan-now", status_code=status.HTTP_201_CREATED)
def scan_now(
    instance_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Кнопка «Сканировать сейчас»: команда scan_now (картридж пишет триггер в scout_control)."""
    _require_instance(session, instance_id)
    cmd = Command(instance_id=instance_id, kind="scan_now", status="queued", payload={})
    session.add(cmd)
    session.flush()  # получить cmd.id для ответа
    write_audit(
        session, actor=str(operator.id), action="scout_scan_now", entity=str(instance_id)
    )
    return {"status": "queued", "command_id": str(cmd.id)}


@router.get("/instances/{instance_id}/scout/settings/journal")
def scout_settings_journal(
    instance_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Журнал изменений порогов (из audit_log: кто/когда/что→что). Свежие сверху."""
    rows = (
        session.execute(
            select(AuditLog)
            .where(
                AuditLog.action == "scout_settings_changed",
                AuditLog.entity == str(instance_id),
            )
            .order_by(AuditLog.ts.desc())
            .limit(50)
        )
        .scalars()
        .all()
    )
    return [
        {
            "ts": r.ts.isoformat() if r.ts else None,
            "actor": r.actor,
            "before": r.before,
            "after": r.after,
        }
        for r in rows
    ]
