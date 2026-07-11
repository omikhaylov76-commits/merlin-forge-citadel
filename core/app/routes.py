"""HTTP-ручки ядра (шаг 3). Каждое изменяющее действие — строка в audit_log (закон №4).
Владение проверяется на всех ручках, где есть чей-то ресурс (SEC7)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import current_user, ensure_owns, get_token, issue_token, require_role
from app.config import Settings, get_settings
from app.db import get_session
from app.models import ApiToken, Instance, Job, User
from app.security import DUMMY_PASSWORD_HASH, verify_password

router = APIRouter(prefix="/v1")


class LoginIn(BaseModel):
    email: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, session: Session = Depends(get_session)) -> dict:
    email = body.email.strip().lower()  # #2: регистронезависимый логин (store+query .lower())
    user = session.scalar(select(User).where(User.email == email))
    # #1: argon2 тратим ВСЕГДА (dummy-хэш, если юзера нет) — константное время, без enumeration
    ok = verify_password(body.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if user is None or not ok:
        write_audit(session, actor=email[:128], action="login_failed")  # видимость брутфорса
        session.commit()  # аудит неудачи должен пережить 401 (get_session откатывает исключения)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "неверные учётные данные")
    # TOTP — заготовка, в v1 выключен (включить до go-live: user.totp_secret + verify_totp).
    raw = issue_token(session, principal="user", subject_id=str(user.id), scope=f"role:{user.role}")
    write_audit(session, actor=str(user.id), action="login")
    return {"token": raw, "token_type": "bearer"}


@router.get("/auth/me")
def me(user: User = Depends(current_user)) -> dict:
    return {"id": str(user.id), "role": user.role, "email": user.email}


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(token: ApiToken = Depends(get_token), session: Session = Depends(get_session)) -> None:
    token.revoked_at = datetime.now(UTC)  # отзыв мгновенный (ADR-0008v2)
    write_audit(session, actor=token.subject_id, action="logout")


@router.get("/admin/ping")
def admin_ping(_: User = Depends(require_role("operator"))) -> dict:
    return {"pong": True}  # RBAC-демо: только оператор


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    user: User = Depends(current_user),
    session: Session = Depends(get_session),
) -> dict:
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такого пользователя") from None
    ensure_owns(user, user_id)  # свой профиль или оператор; иначе 403
    target = session.get(User, uid)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такого пользователя")
    return {"id": str(target.id), "role": target.role, "email": target.email}


# ── Инстансы: продюсеры jobs (шов S1→S3). Деплой из консоли НЕ зовёт Railway напрямую —
# только создаёт instance + job, а исполняет оркестратор (seams S1/S3, ADR-0009). ──────────

# Статусы, из которых оператор может свернуть инстанс (teardown). Только реально достижимые:
# pending/deploying исключены (deploy в полёте — гонка с оркестратором; провал деплоя убирает
# компенсация в ack, OPS3); терминальные stopped/failed_deploy сворачивать нечего.
_TEARDOWNABLE = ("starting", "running", "paused", "stopping")


class CreateInstanceIn(BaseModel):
    client_id: uuid.UUID
    account_id: uuid.UUID
    bot_type_id: uuid.UUID
    profile_id: uuid.UUID
    image: str                          # образ картриджа бота (для paper-bot — его образ)
    env: dict[str, str] | None = None   # доп. переменные окружения бота (без секретов в v1)


@router.post("/instances", status_code=status.HTTP_201_CREATED)
def create_instance(
    body: CreateInstanceIn,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    """Оператор заводит инстанс: строка instances(pending) + deploy-job. Railway тут не зовётся."""
    inst = Instance(
        client_id=body.client_id,
        account_id=body.account_id,
        bot_type_id=body.bot_type_id,
        profile_id=body.profile_id,
        status="pending",
        health="ok",
    )
    session.add(inst)
    try:
        session.flush()  # id + проверка партиал-уникальности «≤1 живой инстанс на счёт» (OPS3)
    except IntegrityError:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "на этом счёте уже есть живой инстанс"
        ) from None
    # Токен инстанса (принципал 'instance', скоуп — свой инстанс): им картридж шлёт телеметрию и
    # берёт команды (шов S4). Выдаётся ОДИН раз здесь и уезжает в env деплоя (Контракт: секреты
    # передаются при старте). Это платформенный токен, не ключ биржи (тот — конверт, ADR-0010).
    instance_token = issue_token(
        session, principal="instance", subject_id=str(inst.id), scope="instance"
    )
    # Имя сервиса детерминировано от id — оркестратор ищет по нему «усынови или упади» (S3/S5).
    # env по Контракту Бота v0 (MF_*). Токен — только в payload ядра/оркестратора, не в логах.
    payload = {
        "image": body.image,
        "name": f"mfc-inst-{inst.id}",
        "env": {
            "MF_INSTANCE_ID": str(inst.id),
            "MF_INSTANCE_TOKEN": instance_token,
            "MF_CORE_URL": settings.core_public_url,
            **(body.env or {}),
        },
    }
    job = Job(kind="deploy", instance_id=inst.id, status="pending", payload=payload)
    session.add(job)
    session.flush()
    write_audit(
        session, actor=str(operator.id), action="instance_created", entity=str(inst.id),
        after={"status": "pending", "account_id": str(body.account_id)},
    )
    write_audit(session, actor=str(operator.id), action="deploy_enqueued", entity=str(job.id))
    return {"id": str(inst.id), "status": inst.status, "deploy_job_id": str(job.id)}


@router.post("/instances/{instance_id}/teardown", status_code=status.HTTP_202_ACCEPTED)
def teardown_instance(
    instance_id: uuid.UUID,
    operator: User = Depends(require_role("operator")),
    session: Session = Depends(get_session),
) -> dict:
    """Оператор сворачивает инстанс: teardown-job. Исполнение (destroy) — оркестратор (OPS5)."""
    inst = session.get(Instance, instance_id)
    if inst is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "нет такого инстанса")
    if inst.status not in _TEARDOWNABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"инстанс в статусе '{inst.status}' не сворачивается"
        )
    # Идемпотентность: активный teardown уже в очереди — второй не плодим.
    active = session.scalar(
        select(Job).where(
            Job.instance_id == instance_id,
            Job.kind == "teardown",
            Job.status.in_(("pending", "leased")),
        )
    )
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "teardown уже в очереди")
    payload = {"infra_ref": inst.infra_ref} if inst.infra_ref else {}
    job = Job(kind="teardown", instance_id=instance_id, status="pending", payload=payload)
    session.add(job)
    session.flush()
    write_audit(
        session, actor=str(operator.id), action="teardown_requested", entity=str(instance_id)
    )
    return {"id": str(instance_id), "teardown_job_id": str(job.id), "status": inst.status}
