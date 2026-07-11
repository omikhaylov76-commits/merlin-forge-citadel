"""Auth-механизм (ADR-0008v2): единый opaque-токен для всех принципалов.

issue/authenticate/revoke; скользящий TTL; проверка владения — на ВСЕХ ручках (SEC7),
не только в портале. Роль берём у пользователя (машинные токены роли не имеют).
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import ApiToken, User
from app.security import hash_token, new_token

_TTL = timedelta(hours=12)  # скользящий: продлевается при каждом использовании


def _now() -> datetime:
    return datetime.now(UTC)


def issue_token(session: Session, *, principal: str, subject_id: str, scope: str) -> str:
    raw = new_token()
    session.add(
        ApiToken(
            token_sha256=hash_token(raw),
            principal=principal,
            subject_id=subject_id,
            scope=scope,
            expires_at=_now() + _TTL,
        )
    )
    session.flush()
    return raw  # сырой токен возвращаем один раз; в БД только его SHA-256


def authenticate(session: Session, raw: str) -> ApiToken | None:
    tok = session.scalar(select(ApiToken).where(ApiToken.token_sha256 == hash_token(raw)))
    if tok is None or tok.revoked_at is not None:
        return None
    if tok.expires_at is not None and tok.expires_at < _now():
        return None
    tok.expires_at = _now() + _TTL  # скользящий TTL (персистится коммитом сессии)
    return tok


def get_token(
    authorization: str | None = Header(default=None),
    session: Session = Depends(get_session),
) -> ApiToken:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "требуется Bearer-токен")
    tok = authenticate(session, authorization.removeprefix("Bearer "))
    if tok is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "токен недействителен или отозван")
    return tok


def current_user(
    token: ApiToken = Depends(get_token),
    session: Session = Depends(get_session),
) -> User:
    if token.principal != "user":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "не пользовательский токен")
    user = session.get(User, uuid.UUID(token.subject_id))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "пользователь не найден")
    return user


def require_principal(*principals: str):
    # Машинные токены (instance/orchestrator/ensemble) роли не имеют — их пускаем по принципалу.
    # Пример: internal jobs API открыт только принципалу 'orchestrator' (ADR-0009, скоуп-токен).
    def dep(token: ApiToken = Depends(get_token)) -> ApiToken:
        if token.principal not in principals:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "принципал не разрешён")
        return token

    return dep


def require_role(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "роль не разрешена")
        return user

    return dep


def ensure_owns(user: User, resource_owner_id: str) -> None:
    # Владение: оператор видит любой ресурс; иначе — только свой (SEC7).
    if user.role == "operator":
        return
    if str(user.id) != str(resource_owner_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "чужой ресурс")
