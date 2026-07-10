"""ORM-модели ядра. Миграция 0001 — фундамент auth/аудита (НЕ весь домен, YAGNI).

Комментарий «зачем» на таблицах — закон №7. Ключи — UUID (не последовательные: перебор id
закрыт, SEC7). Роль — строка+CHECK, НЕ нативный ENUM (его больно расширять).
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('operator','client')", name="ck_users_role"),
        {"comment": "Оператор и клиенты; роль строка+CHECK, не ENUM (расширять легко)."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    # password_hash — argon2 (шаг 3); totp_secret — TOTP-заготовка, включим до go-live (шаг 3)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    totp_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ApiToken(Base):
    __tablename__ = "api_tokens"
    __table_args__ = (
        CheckConstraint(
            "principal IN ('user','instance','orchestrator','ensemble')", name="ck_tokens_principal"
        ),
        {"comment": "Opaque-токены (ADR-0008v2): в БД хэш SHA-256, не токен; отзыв = revoked_at."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    token_sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    principal: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)  # к кому привязан
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        {"comment": "Аудит действий (закон №4); append-only на уровне БД (триггер в миграции)."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)  # кто (user id / principal)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity: Mapped[str | None] = mapped_column(String(128), nullable=True)
    before: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    after: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
