"""HTTP-ручки ядра (шаг 3). Каждое изменяющее действие — строка в audit_log (закон №4).
Владение проверяется на всех ручках, где есть чей-то ресурс (SEC7)."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import write_audit
from app.auth import current_user, ensure_owns, get_token, issue_token, require_role
from app.db import get_session
from app.models import ApiToken, User
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
