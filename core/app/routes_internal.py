"""Internal API шва S3 — аренда/ack jobs оркестратором (ADR-0009). Скоуп-токен `orchestrator`.

Ключевой инвариант SCL1: long-poll GET /internal/jobs/next НЕ держит БД-сессию на всё ожидание.
Поэтому аутентификация здесь — своей короткой сессией (не Depends(get_session), который живёт до
ответа), а опрос — цикл «короткая сессия → сон без коннекта». ack — обычный короткий запрос.
"""

import asyncio
import time
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import authenticate, require_principal
from app.config import Settings, get_settings
from app.db import get_session, get_sessionmaker
from app.jobs import LeaseConflict, ack, lease_next
from app.models import ApiToken, Job

router = APIRouter(prefix="/v1")

_POLL_INTERVAL_S = 0.5  # как часто щупать очередь внутри окна ?wait= (между попытками коннекта нет)


def _authenticate_orchestrator(authorization: str | None) -> str:
    """Аутентифицировать принципал `orchestrator` СВОЕЙ короткой сессией (не держим коннект, SCL1).

    Возвращает subject_id (актор для аудита). 401 — нет/плох токен; 403 — не тот принципал.
    """
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "требуется Bearer-токен")
    with get_sessionmaker()() as s:
        tok = authenticate(s, authorization.removeprefix("Bearer "))
        if tok is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен недействителен или отозван")
        if tok.principal != "orchestrator":
            raise HTTPException(status.HTTP_403_FORBIDDEN, "принципал не разрешён")
        subject = tok.subject_id
        s.commit()  # скользящий TTL токена персистится
    return subject


def _serialize(job: Job) -> dict:
    # Поверхность для оркестратора: что делать (kind/payload) + fencing-nonce для ack.
    return {
        "id": str(job.id),
        "kind": job.kind,
        "instance_id": str(job.instance_id),
        "payload": job.payload,
        "lease_nonce": str(job.lease_nonce),
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "attempts": job.attempts,
    }


def _lease_and_serialize(settings: Settings, actor: str) -> dict | None:
    """Синхронный тик аренды (короткая сессия). Гоняется в threadpool — синхронный БД-вызов не
    подвешивает event loop (как свёртка часового через to_thread, MFC-003). Коннект между тиками
    возвращается в пул (SCL1)."""
    sm = get_sessionmaker()
    with sm() as s:
        job = lease_next(
            s,
            lease_ttl_s=settings.job_lease_seconds,
            max_deploy_attempts=settings.job_max_deploy_attempts,
            actor=actor,
        )
        payload = _serialize(job) if job is not None else None
        s.commit()
    return payload


@router.get("/internal/jobs/next")
async def next_job(
    wait: int = 0,
    authorization: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> Response:
    """Арендовать следующий job (long-poll). 200 с job или 204, если за окно ?wait= пусто."""
    actor = await asyncio.to_thread(_authenticate_orchestrator, authorization)
    budget = min(max(wait, 0), settings.job_longpoll_max_wait_seconds)
    deadline = time.monotonic() + budget
    while True:
        payload = await asyncio.to_thread(_lease_and_serialize, settings, actor)
        if payload is not None:
            return JSONResponse(payload)
        if time.monotonic() >= deadline:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        await asyncio.sleep(_POLL_INTERVAL_S)


class AckIn(BaseModel):
    lease_nonce: str                 # fencing: должен совпасть с актуальной арендой (OPS2)
    result: str                      # done | failed | release
    detail: dict | None = None       # для deploy done — {"infra_ref": ...}; иначе диагностика
    terminal: bool = False           # failed+terminal → сразу failed без ретраев (decrypt/no-start)


@router.post("/internal/jobs/{job_id}/ack")
def ack_job(
    job_id: uuid.UUID,
    body: AckIn,
    token: ApiToken = Depends(require_principal("orchestrator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Завершить попытку по job. 409 — неактуальный fencing-nonce; 422 — неизвестный result."""
    if body.result not in ("done", "failed", "release"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "неизвестный result")
    try:
        job = ack(
            session,
            job_id=job_id,
            nonce=body.lease_nonce,
            result=body.result,
            detail=body.detail,
            terminal=body.terminal,
            max_deploy_attempts=settings.job_max_deploy_attempts,
            actor=token.subject_id,
        )
    except LeaseConflict:
        raise HTTPException(status.HTTP_409_CONFLICT, "неактуальный lease (fencing)") from None
    return {"id": str(job.id), "status": job.status, "attempts": job.attempts}
