"""Скринер по параметрам (С7-2б) — операторский запуск + приём результатов картриджа + readout.

Поток: оператор POST /instances/{id}/screener/runs {params} → создаётся ScreenerRun(queued) +
Command(kind=screener_run, payload={run_id,params}) → картридж берёт команду (S4←), гоняет скринер
ОТДЕЛЬНЫМ процессом → POST /screener/runs/{run_id}/results (токен инстанса): findings+summary+status
→ консоль читает GET /screener/runs/{run_id}. Владение — по инстансу токена (SEC7).
Каждое операторское write — строка audit_log (закон №4). Телеметрия картриджа (push) не аудитится.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import current_instance, require_role
from app.db import get_session
from app.models import Command, Instance, ScreenerFinding, ScreenerRun, User

router = APIRouter(prefix="/v1")

_MAX_FINDINGS = 500  # кап на число строк результата в пуше (анти-раздувание)


class ScreenerParamsIn(BaseModel):
    """Параметры прогона (форма консоли). Дефолты — приказ Куратора (180дн/$5M/×1.5/14дн/оба ТФ)."""

    min_age_days: int = Field(180, ge=0, le=100_000)
    min_turnover_usd: int = Field(5_000_000, ge=0, le=100_000_000_000)
    k: float = Field(1.5, gt=0, le=1000)
    days: int = Field(14, ge=1, le=365)
    universe_max: int = Field(150, ge=1, le=1000)
    tfs: list[str] = Field(default_factory=lambda: ["4h", "1h"])


@router.post("/instances/{instance_id}/screener/runs", status_code=status.HTTP_201_CREATED)
def enqueue_screener_run(
    instance_id: uuid.UUID,
    params: ScreenerParamsIn,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Оператор запускает прогон скринера на инстансе-исполнителе (представитель, напр. Галахад)."""
    inst = session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такого инстанса")

    p = params.model_dump()
    run = ScreenerRun(instance_id=instance_id, params=p, status="queued")
    session.add(run)
    session.flush()  # получить run.id для payload команды
    cmd = Command(
        instance_id=instance_id, kind="screener_run", status="queued",
        payload={"run_id": str(run.id), "params": p},
    )
    session.add(cmd)
    write_audit(
        session, actor=str(operator.id), action="screener_run_enqueued", entity=str(run.id),
        after={"instance_id": str(instance_id), "params": p},
    )
    return {"run_id": str(run.id), "status": run.status}


class ScreenerResultsIn(BaseModel):
    """Пуш картриджа: статус прогона + (опц.) воронка/счётчики + строки результата."""

    status: str = Field(pattern="^(running|done|error)$")
    summary: dict | None = None
    findings: list[dict] | None = None


@router.post("/screener/runs/{run_id}/results")
def push_screener_results(
    run_id: uuid.UUID,
    body: ScreenerResultsIn,
    inst: Instance = Depends(current_instance),
    session: Session = Depends(get_session),
) -> dict:
    """Картридж пушит результат прогона (токен инстанса). Владение: прогон ЭТОГО инстанса."""
    run = session.get(ScreenerRun, run_id)
    if run is None or run.instance_id != inst.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такого прогона")  # SEC7 (владение)
    if body.findings is not None and len(body.findings) > _MAX_FINDINGS:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "слишком много строк")

    if body.findings is not None:  # replace-семантика: заменяем строки прогона целиком
        session.execute(delete(ScreenerFinding).where(ScreenerFinding.run_id == run_id))
        for f in body.findings:
            sym = str(f.get("symbol") or "?")[:40]
            session.add(ScreenerFinding(run_id=run_id, symbol=sym, data=f))
    run.status = body.status
    if body.summary is not None:
        run.summary = body.summary
    run.updated_at = func.now()
    return {"run_id": str(run_id), "status": run.status}


def _run_dict(run: ScreenerRun) -> dict:
    return {
        "run_id": str(run.id), "instance_id": str(run.instance_id), "status": run.status,
        "params": run.params, "summary": run.summary,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
    }


@router.get("/instances/{instance_id}/screener/runs")
def list_screener_runs(
    instance_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> list[dict]:
    """Последние прогоны инстанса (для истории/выбора на экране Скринер)."""
    runs = session.scalars(
        select(ScreenerRun).where(ScreenerRun.instance_id == instance_id)
        .order_by(ScreenerRun.created_at.desc()).limit(20)
    ).all()
    return [_run_dict(r) for r in runs]


@router.get("/screener/runs/{run_id}")
def get_screener_run(
    run_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Прогон + строки результата (статус подбора + таблица монет для консоли)."""
    run = session.get(ScreenerRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такого прогона")
    rows = session.scalars(
        select(ScreenerFinding).where(ScreenerFinding.run_id == run_id)
    ).all()
    out = _run_dict(run)
    out["findings"] = [r.data for r in rows]
    return out
