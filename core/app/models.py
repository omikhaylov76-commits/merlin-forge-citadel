"""ORM-модели ядра. Миграция 0001 — фундамент auth/аудита (НЕ весь домен, YAGNI).

Комментарий «зачем» на таблицах — закон №7. Ключи — UUID (не последовательные: перебор id
закрыт, SEC7). Роль — строка+CHECK, НЕ нативный ENUM (его больно расширять).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
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
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # password_hash — argon2; totp_secret — TOTP-заготовка, включить до go-live (шаг 3)
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


class Instance(Base):
    __tablename__ = "instances"
    __table_args__ = (
        CheckConstraint("health IN ('ok','stale','dead')", name="ck_instances_health"),
        CheckConstraint(
            "status IN ('pending','deploying','starting','running','paused',"
            "'stopping','stopped','failed','failed_deploy','stopping_failed')",
            name="ck_instances_status",
        ),
        {
            "comment": "Инстанс бота: status=намерение, health=свежесть heartbeat (flows). "
            "FK на clients/accounts/bot_types/profiles отложены — ADR-0013 (родители в Ф2/Ф3/Ф5)."
        },
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Ссылки на родителей — UUID БЕЗ FK-constraint (родители появятся со своими фичами, ADR-0013)
    client_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    account_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    bot_type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # жизненный цикл (flows)
    # health производно от свежести heartbeat; ставит свёртка часового (instance_health)
    health: Mapped[str] = mapped_column(String(8), nullable=False, server_default="ok")
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True  # NULL, пока бот не прислал первый heartbeat
    )
    # infra_ref — ссылка Railway; ставит оркестратор при деплое
    infra_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ensemble_id — труба ансамблей (ADR-0006), в v1 не наполняется
    ensemble_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    deployed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Job(Base):
    """Задача инфры (deploy/teardown) — контракт-таблица шва S3 (ADR-0009).

    core — единственный писатель; оркестратор арендует через internal API (long-poll+lease+fencing),
    таблицу напрямую НЕ читает (закон №3). Идемпотентность deploy — партиал-уникальный индекс
    (≤1 активный deploy на инстанс). Fencing: ack принимает держатель актуального lease_nonce.
    kind='backtest' зарезервирован под Ф5 — CHECK его не пускает (явная ошибка-заглушка).
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint("kind IN ('deploy','teardown')", name="ck_jobs_kind"),
        CheckConstraint(
            "status IN ('pending','leased','done','failed')", name="ck_jobs_status"
        ),
        {"comment": "Очередь задач инфры (шов S3, ADR-0009); писатель — только core."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # instance_id — реальный FK: родитель (instances) существует с 0002. Отложенные FK (ADR-0013)
    # касались лишь ещё-не-созданных родителей — здесь ссылочная целостность уместна.
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    # attempts++ на неуспешной попытке deploy; 3 → failed (без бесконечных ретраев, S3).
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # lease: аренда с истечением; протух → job возвращается в очередь (attempts++ по контракту ack).
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # fencing-токен: выдан при аренде, нужен на ack — устаревший держатель job не завершит (OPS2).
    lease_nonce: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # payload: вход задачи (deploy: image/env/name); result: последний detail от ack.
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


# ── Телеметрия бота (шов S4, недоверенный ввод — храним параметризованно, экранируем на выводе).
# ts — время бота (проверяется |ts−now|<48ч на приёме); received_at — серверное, авторитетно. ──

class EquityPoint(Base):
    """Точка кривой equity (телеметрия S4). equity строго в USDT (MON9). Dedup по (instance, ts)."""

    __tablename__ = "equity_points"
    __table_args__ = (
        UniqueConstraint("instance_id", "ts", name="uq_equity_instance_ts"),
        {"comment": "Кривая equity бота (S4); received_at авторитетно; dedup (instance, ts)."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    equity: Mapped[Decimal] = mapped_column(Numeric, nullable=False)  # деньги — Numeric, не float
    currency: Mapped[str] = mapped_column(String(8), nullable=False)  # v0 — USDT
    working: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    cushion: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class Trade(Base):
    """Сделка бота (телеметрия S4). Dedup по (instance, exec_id) — не по ts (со-секундные, COH4)."""

    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("instance_id", "exec_id", name="uq_trades_instance_exec"),
        CheckConstraint("side IN ('buy','sell')", name="ck_trades_side"),
        {"comment": "Сделки бота (S4); dedup по (instance, exec_id биржи), идемпотентно (COH4)."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    exec_id: Mapped[str] = mapped_column(String(128), nullable=False)  # ключ идемпотентности
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)    # недоверенный ввод
    side: Mapped[str] = mapped_column(String(4), nullable=False)
    qty: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    pnl: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)


class Event(Base):
    """Событие бота (телеметрия S4). Dedup по (instance, ts, kind). detail — недоверенный ввод."""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("instance_id", "ts", "kind", name="uq_events_instance_ts_kind"),
        {"comment": "События бота (S4); dedup (instance, ts, kind); detail — недоверенный JSON."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=False
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class Command(Base):
    """Команда боту (S4←, ADR-0002/0005). cmd_id = id. Канон: pause/resume/stop_close (start нет).

    Доставка — long-poll (как jobs); ack идемпотентен по cmd_id. stop_close «липкий» пока instance
    в stopping (OPS1). Каждая команда и её ack — строка audit_log (закон №4).
    """

    __tablename__ = "commands"
    __table_args__ = (
        CheckConstraint("kind IN ('pause','resume','stop_close')", name="ck_commands_kind"),
        CheckConstraint(
            "status IN ('queued','delivered','acked','failed')", name="ck_commands_status"
        ),
        {"comment": "Очередь команд боту (S4←, ADR-0005); канон pause/resume/stop_close."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # detail от бота на ack
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
