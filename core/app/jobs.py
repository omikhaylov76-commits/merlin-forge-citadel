"""Сервис jobs — аренда и завершение задач инфры (шов S3, ADR-0009).

core — единственный писатель таблицы `jobs`; оркестратор арендует их через internal API
(long-poll+lease+fencing), таблицу напрямую НЕ читает (закон №3). Функции здесь синхронны и
принимают открытую сессию — тестируются без HTTP; endpoint (routes_internal) держит их короткими,
чтобы long-poll не удерживал коннект (SCL1).

Инварианты (ADR-0009 v2):
- Single-claim: аренда берёт старейший pending через FOR UPDATE SKIP LOCKED — две реплики
  оркестратора одну job не задваивают.
- Fencing (OPS2): аренда выдаёт свежий lease_nonce; ack принимает только держателя актуального
  nonce актуальной аренды — отставший процесс (lease перевыдан) чужую job не завершит.
- Реклейм (seams:64): протухшая аренда (lease_expires_at < now) возвращается в очередь; для
  deploy это неуспешная попытка (attempts++), для teardown — просто перезапуск (OPS5).
- Терминальность: deploy на 3-й неудаче → failed + instance=failed_deploy + teardown-компенсация
  (OPS3). teardown НЕ терминален пока сервис жив (OPS5) — вечный requeue. release (инфра лежит,
  OPS16) — requeue БЕЗ attempts++.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.models import Instance, Job

# Статусы инстанса, из которых teardown уводит в stopping (живые/приостановленные).
# failed_deploy НЕ трогаем: компенсационный teardown прибирает ресурсы, статус остаётся терминален.
_TEARDOWN_FROM = ("starting", "running", "paused")


class LeaseConflict(Exception):
    """ack пришёл с неактуальным fencing-nonce или на не-арендованную job (устаревший держатель)."""


def _now() -> datetime:
    return datetime.now(UTC)


def lease_next(
    session: Session, *, lease_ttl_s: float, max_deploy_attempts: int, actor: str = "orchestrator"
) -> Job | None:
    """Арендовать старейший pending job. Возвращает job (арендованный) или None.

    Сначала реклеймит протухшие аренды, затем claim'ит один pending через SKIP LOCKED.
    Переход статуса инстанса на аренде: deploy pending→deploying, teardown живой→stopping.
    """
    now = _now()
    _reclaim_expired(session, now=now, max_deploy_attempts=max_deploy_attempts)

    job = session.execute(
        select(Job)
        .where(Job.status == "pending")
        .order_by(Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(1)
    ).scalar_one_or_none()
    if job is None:
        return None

    job.status = "leased"
    job.lease_nonce = uuid.uuid4()
    job.lease_expires_at = now + timedelta(seconds=lease_ttl_s)

    inst = session.get(Instance, job.instance_id)
    if inst is not None:
        if job.kind == "deploy" and inst.status == "pending":
            inst.status = "deploying"
        elif job.kind == "teardown" and inst.status in _TEARDOWN_FROM:
            inst.status = "stopping"

    write_audit(
        session,
        actor=actor,
        action="job_leased",
        entity=str(job.id),
        after={"kind": job.kind, "instance_id": str(job.instance_id), "attempts": job.attempts},
    )
    return job


def ack(
    session: Session,
    *,
    job_id: uuid.UUID,
    nonce: str,
    result: str,
    detail: dict | None = None,
    terminal: bool = False,
    max_deploy_attempts: int,
    actor: str = "orchestrator",
) -> Job:
    """Завершить попытку по job. result: done | failed | release.

    Fencing: только держатель актуального lease_nonce актуальной аренды (иначе LeaseConflict → 409).
    done — успех; failed — неуспешная попытка (attempts++, терминал по правилам); release — отпуск
    без штрафа (инфра недоступна, OPS16); terminal=True при failed форсирует терминал сразу (без
    ретраев: расшифровка ключа/бот-не-стартовал, seams:63/65).
    """
    job = session.get(Job, job_id, with_for_update=True)
    if job is None or job.status != "leased" or str(job.lease_nonce) != str(nonce):
        # не нашли / уже завершена / чужой nonce — устаревший держатель job не двигает (OPS2)
        raise LeaseConflict()

    inst = session.get(Instance, job.instance_id)
    if result == "done":
        _complete(job, inst, detail)
    elif result == "release":
        _release(job)  # отпуск без attempts++ (OPS16)
    elif result == "failed":
        _fail_attempt(
            session, job, inst, max_deploy_attempts=max_deploy_attempts, terminal=terminal
        )
    else:
        raise ValueError(f"неизвестный result: {result!r}")

    job.result = detail
    write_audit(
        session,
        actor=actor,
        action="job_ack",
        entity=str(job.id),
        after={"result": result, "status": job.status, "attempts": job.attempts},
    )
    return job


def _complete(job: Job, inst: Instance | None, detail: dict | None) -> None:
    job.status = "done"
    _clear_lease(job)
    if inst is None:
        return
    if job.kind == "deploy":
        # infra_ref сообщает оркестратор в detail; deploying→starting (ждём 1-й heartbeat бота, S4).
        if inst.status == "deploying":
            inst.status = "starting"
        inst.deployed_at = _now()
        infra_ref = detail.get("infra_ref") if detail else None
        if infra_ref:
            inst.infra_ref = infra_ref
    elif job.kind == "teardown":
        inst.infra_ref = None
        if inst.status == "stopping":
            inst.status = "stopped"


def _release(job: Job) -> None:
    # Инфра недоступна: возвращаем в очередь без штрафа по attempts (OPS16).
    job.status = "pending"
    _clear_lease(job)


def _fail_attempt(
    session: Session, job: Job, inst: Instance | None, *, max_deploy_attempts: int, terminal: bool
) -> None:
    job.attempts += 1
    _clear_lease(job)
    if job.kind == "teardown":
        # teardown не терминален пока сервис жив (OPS5): всегда в очередь, бесконечный backoff.
        job.status = "pending"
        return
    # deploy: терминал по флагу (no-retry) ИЛИ по исчерпанию попыток; иначе requeue.
    if terminal or job.attempts >= max_deploy_attempts:
        job.status = "failed"
        if inst is not None and inst.status in ("pending", "deploying", "starting"):
            inst.status = "failed_deploy"  # освобождает счёт (партиал-индекс instances)
        _enqueue_teardown_compensation(session, job.instance_id, inst)
    else:
        job.status = "pending"


def _enqueue_teardown_compensation(
    session: Session, instance_id: uuid.UUID, inst: Instance | None
) -> None:
    # OPS3: провал деплоя ОБЯЗАН прибрать частичные ресурсы (сервис/схема/роль). Если infra_ref
    # успели проставить — есть что убирать; иначе no-op teardown (destroy идемпотентен, 404=успех).
    payload = {"infra_ref": inst.infra_ref} if (inst is not None and inst.infra_ref) else {}
    session.add(Job(kind="teardown", instance_id=instance_id, status="pending", payload=payload))
    write_audit(
        session, actor="system:core", action="teardown_compensation", entity=str(instance_id)
    )


def _reclaim_expired(session: Session, *, now: datetime, max_deploy_attempts: int) -> int:
    """Протухшие аренды → назад в очередь (зависший/умерший оркестратор). Возвращает число."""
    expired = session.scalars(
        select(Job)
        .where(Job.status == "leased", Job.lease_expires_at < now)
        .with_for_update(skip_locked=True)
    ).all()
    for job in expired:
        inst = session.get(Instance, job.instance_id)
        # истечение аренды = неуспешная попытка (attempts++, seams:64), НЕ release.
        _fail_attempt(session, job, inst, max_deploy_attempts=max_deploy_attempts, terminal=False)
        write_audit(
            session,
            actor="system:core",
            action="job_lease_expired",
            entity=str(job.id),
            after={"attempts": job.attempts, "status": job.status},
        )
    return len(expired)


def _clear_lease(job: Job) -> None:
    job.lease_nonce = None
    job.lease_expires_at = None
