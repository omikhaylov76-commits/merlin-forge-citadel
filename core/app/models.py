"""ORM-модели ядра. Миграция 0001 — фундамент auth/аудита (НЕ весь домен, YAGNI).

Комментарий «зачем» на таблицах — закон №7. Ключи — UUID (не последовательные: перебор id
закрыт, SEC7). Роль — строка+CHECK, НЕ нативный ENUM (его больно расширять).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
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


class Client(Base):
    __tablename__ = "clients"
    __table_args__ = (
        CheckConstraint(
            "fee_pct_default >= 0 AND fee_pct_default < 1", name="ck_clients_fee_pct_default"
        ),
        {
            "comment": "Клиент managed-счёта (Ф3, CRM). fee_pct_default — тариф-дефолт (MON8), "
            "снапшот в период при закрытии. is_active — мягкое отключение без удаления."
        },
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    contacts: Mapped[str | None] = mapped_column(Text, nullable=True)  # e-mail/телега/заметки
    contract_ref: Mapped[str | None] = mapped_column(Text, nullable=True)  # ссылка на договор
    # тариф-дефолт как доля (0.2 = 20%); NULL пока не задан; CHECK 0<=x<1 (не берём >100%)
    fee_pct_default: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    # связь с учёткой для портала; UUID без FK (FK включим в Ф4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExchangeAccount(Base):
    __tablename__ = "exchange_accounts"
    __table_args__ = (
        CheckConstraint(
            "exchange IN ('bybit','okx','bitget')", name="ck_exchange_accounts_exchange"
        ),
        {
            "comment": "Биржевой счёт клиента (Ф3). key_ciphertext — шифр ключей, ADR-0004/0010; "
            "NULL пока нет; расшифровка только в оркестраторе, в лог/ответ НИКОГДА."
        },
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    exchange: Mapped[str] = mapped_column(String(16), nullable=False)  # bybit|okx|bitget (+CHECK)
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)  # человекочитаемая метка
    key_ciphertext: Mapped[str | None] = mapped_column(Text, nullable=True)  # СЕКРЕТ: не в лог
    perms_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    # billing-lifecycle (MFC-F3-3): активация = старт биллинга; терминация останавливает генератор
    billing_activated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    billing_terminated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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
            "FK client_id/account_id включены в Ф3 (0005); bot_type_id/profile_id — Ф5 (ADR-0013)."
        },
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # client_id/account_id — FK в Ф3; bot_type_id/profile_id — UUID без FK (ADR-0013, Ф5)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchange_accounts.id", ondelete="RESTRICT"), nullable=False
    )
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


class SignalJournalEvent(Base):
    """Событие Сигнального журнала (Этап 1 переката 1-to-N, порция №3). Товарная запись решения
    ядра-характера для повтора на клиентском счёте (диспетчер Этапа 2 читает и повторяет; сам
    журнал торговлю НЕ меняет — наблюдатель). Append-only; dedup по натуральному ключу движка
    (instance, src_table, src_id) — см. UniqueConstraint ниже; seq — порядок повтора, НЕ ключ.
    core/setup_id/kind — конверт; data — поля по kind (недоверенный JSON). Ведение-детали
    (reanchor/…) — вариант C (ADR-0024)."""

    __tablename__ = "signal_journal"
    __table_args__ = (
        UniqueConstraint(
            "instance_id", "src_table", "src_id", name="uq_signal_journal_instance_src",
        ),
        {"comment": "Сигнальный журнал (порция №3); append-only; dedup по натур. ключу движка "
                    "(instance, src_table, src_id); data — недоверенный JSON."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=False, index=True
    )
    src_table: Mapped[str] = mapped_column(String(24), nullable=False)  # натуральный ключ движка
    src_id: Mapped[int] = mapped_column(BigInteger, nullable=False)  # id строки worker-БД
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)  # порядок повтора (не дедуп)
    core: Mapped[str] = mapped_column(String(40), nullable=False)  # метка ядра (BORS/...)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    setup_id: Mapped[str] = mapped_column(String(80), nullable=False)   # {symbol}:{bar_time}
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)


class ScoutSnapshot(Base):
    """Снимок сетапа скаута (телеметрия S4→, ADR-0016 scout-канал). REPLACE-семантика per
    (instance, symbol, tf): новый пуш upsert'ит присланные пары и УДАЛЯЕТ выпавшие (сетап умер →
    строки нет; иначе канбан копит трупы). payload — весь контрактный снимок (недоверенный JSON,
    экранируется на ВЫВОДЕ, #53). Аудита нет (телеметрия, не действие оператора — закон №4)."""

    __tablename__ = "scout_snapshots"
    __table_args__ = (
        UniqueConstraint("instance_id", "symbol", "tf", name="uq_scout_instance_symbol_tf"),
        {"comment": "Снимки сетапов скаута (S4, ADR-0016); replace per (instance,symbol,tf); "
                    "payload — недоверенный JSON, экранируется на выводе."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=False, index=True
    )
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)   # недоверенный ввод
    tf: Mapped[str] = mapped_column(String(4), nullable=False)        # 4h|1h
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)      # весь контрактный снимок
    scan_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    orders_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Command(Base):
    """Команда боту (S4←, ADR-0002/0005). cmd_id = id. Канон: pause/resume/stop_close (start нет).

    Доставка — long-poll (как jobs); ack идемпотентен по cmd_id. stop_close «липкий» пока instance
    в stopping (OPS1). Каждая команда и её ack — строка audit_log (закон №4).
    """

    __tablename__ = "commands"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('pause','resume','stop_close','screener_run','dozor_apply','scan_now',"
            "'warm_apply')",
            name="ck_commands_kind",
        ),
        CheckConstraint(
            "status IN ('queued','delivered','acked','failed')", name="ck_commands_status"
        ),
        {"comment": "Очередь команд боту (S4←, ADR-0005); pause/resume/stop_close/screener_run."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # detail от бота на ack
    # вход команды (для screener_run: {run_id, params}); pause/resume/stop_close — payload не нужен
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ScreenerRun(Base):
    """Прогон скринера по параметрам (С7-2б). run_id=id. Оператор запускает командой screener_run;
    картридж исполняет ОТДЕЛЬНЫМ процессом и пушит findings. Статус queued→running→done|error.
    params/summary — недоверенный JSON (экранируется на выводе)."""

    __tablename__ = "screener_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','done','error')", name="ck_screener_runs_status"
        ),
        {"comment": "Прогоны скринера по параметрам (С7-2б); queued→running→done|error."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), nullable=False
    )
    params: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="queued")
    summary: Mapped[dict | None] = mapped_column(JSONB, nullable=True)  # воронка/счётчики
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScreenerFinding(Base):
    """Строка результата прогона скринера. data — весь finding (импульс/скор/selected/setup/
    reject_reason) недоверенным JSON (display-only). Удаляется каскадом с прогоном."""

    __tablename__ = "screener_findings"
    __table_args__ = (
        {"comment": "Результаты прогона скринера (С7-2б); data — недоверенный JSON."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("screener_runs.id", ondelete="CASCADE"), nullable=False
    )
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    data: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EngineState(Base):
    """Последнее движковое состояние инстанса (карточка бота, S7). Один ряд на инстанс (upsert):
    картридж пушит компакт каждый тик, ядро перезаписывает. payload — НЕДОВЕРЕННЫЙ JSON (позиции/
    ордера/equity/статус; секретов НЕТ по контракту картриджа), экранируется на выводе."""

    __tablename__ = "engine_states"
    __table_args__ = (
        {"comment": "Last engine_state per instance (карточка бота, S7); JSONB, replace-upsert."},
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), primary_key=True
    )
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BasketItem(Base):
    """Элемент Набора Оператора (НАБОР-1, витрина+хранение). Оператор отмечает сетап звёздочкой →
    монета с контекстом складывается в ГЛОБАЛЬНУЮ корзину (не per-instance; позже НАБОР-2 —
    боевой мост — уезжает боту отдельной спекой). НИЧЕГО не торгует. context — недоверенный JSON
    снимка сетапа (скор/стадия/A-B/входы/детектор), экранируется на выводе. uniq (symbol, tf):
    один ряд на монету+ТФ (повторная звёздочка — upsert). add/remove — строка audit_log (№4)."""

    __tablename__ = "basket_items"
    __table_args__ = (
        CheckConstraint("source IN ('scout','screener')", name="ck_basket_source"),
        UniqueConstraint("symbol", "tf", name="uq_basket_symbol_tf"),
        {"comment": "Набор Оператора (НАБОР-1, витрина+хранение); uniq монета+ТФ; "
                    "ничего не торгует; context недоверен, экранируется на выводе."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)   # недоверенный ввод
    tf: Mapped[str] = mapped_column(String(4), nullable=False)        # 4h|1h|—
    source: Mapped[str] = mapped_column(String(16), nullable=False)   # scout|screener
    context: Mapped[dict] = mapped_column(JSONB, nullable=False)      # снимок контекста сетапа
    note: Mapped[str | None] = mapped_column(Text, nullable=True)     # заметка Оператора (опц.)
    # кто отметил — свободная ссылка (как audit_log.actor), без жёсткого FK на users
    added_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ScoutSettings(Base):
    """Настройки дозора (скаута) на инстанс — ИСТОЧНИК ИСТИНЫ (Разведка-стол, S7, Q4 Куратора).
    Оператор крутит в панели → ядро хранит desired + журнал (audit_log) → картридж применяет
    env-оверрайдами и рестартит ТОЛЬКО скаут. desired — валидированный JSON порогов (age/turnover/
    spread/history/score/universe/list/tfs/primary_tf/fresh/scan/cal/rps). Один ряд на инстанс
    (upsert). Расхождение desired↔применённое видно по статусу команды dozor_apply."""

    __tablename__ = "scout_settings"
    __table_args__ = (
        {"comment": "Настройки дозора на инстанс (Разведка-стол, S7); ядро=истина, картридж "
                    "применяет; desired — валидированный JSON порогов скаута."},
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), primary_key=True
    )
    desired: Mapped[dict] = mapped_column(JSONB, nullable=False)   # валидированный набор порогов
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # кто менял — свободная ссылка (как audit_log.actor), без жёсткого FK на users
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class DynamicSettings(Base):
    """Критерии динамической вселенной на инстанс — ИСТОЧНИК ИСТИНЫ (S8 «Динамо-близнец», ADR-0020).
    Оператор крутит в разделе 5 «Динамика» Конструктора → ядро хранит desired + журнал (audit_log) →
    картридж забирает своим `/self` (boot + периодический re-fetch) и применяет ЖИВЬЁМ: провайдер
    читает файл-критерии в каждом `_recompute`, БЕЗ рестарта (ADR-0020 D1; провайдер = foreground-
    адаптер, рестарт = смерть контейнера). desired — JSON движко-скоупа: что бот БЕРЁТ
    из печки (min_score/stack_max/fresh_bars). Дозор-скоуп (скаут СМОТРИТ) — отдельный канал 0018,
    не смешиваем (ADR-0018 п.3 зеркально). Один ряд на инстанс (upsert)."""

    __tablename__ = "dynamic_settings"
    __table_args__ = (
        {"comment": "Критерии динамики на инстанс (S8/ADR-0020); ядро=истина, картридж "
                    "забирает своим /self и применяет живьём (min_score/stack_max/fresh_bars)."},
    )
    instance_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instances.id"), primary_key=True
    )
    desired: Mapped[dict] = mapped_column(JSONB, nullable=False)   # валидированные критерии отбора
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # кто менял — свободная ссылка (как audit_log.actor), без жёсткого FK на users
    updated_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)


class Contract(Base):
    __tablename__ = "contracts"
    __table_args__ = (
        CheckConstraint(
            "payment_model IN ('profit_hwm','capital_fixed','hybrid','subscription')",
            name="ck_contracts_payment_model",
        ),
        CheckConstraint("fee_pct >= 0 AND fee_pct < 1", name="ck_contracts_fee_pct"),
        CheckConstraint("mgmt_fee_pct >= 0", name="ck_contracts_mgmt_fee_pct"),
        CheckConstraint("hurdle_pct >= 0", name="ck_contracts_hurdle_pct"),
        CheckConstraint("billing_period IN ('month','quarter')", name="ck_contracts_bperiod"),
        CheckConstraint("capital >= 500", name="ck_contracts_capital_floor"),
        CheckConstraint("currency IN ('USDT','USDC')", name="ck_contracts_currency"),
        CheckConstraint("status IN ('draft','signed','suspended')", name="ck_contracts_status"),
        {"comment": "Договор клиента (Ф3): типизированные условия биллинга; fee_pct снапшотится "
         "в период (ADR-0011). billing_period v1=month, quarter — колонка на будущее (#26)."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    payment_model: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="profit_hwm"
    )
    fee_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default="0.15")
    high_water_mark: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    mgmt_fee_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default="0")
    hurdle_pct: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, server_default="0")
    billing_period: Mapped[str] = mapped_column(String(8), nullable=False, server_default="month")
    capital: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="1000")
    withdrawal_notice_days: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="USDT")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BillingPeriod(Base):
    __tablename__ = "billing_periods"
    __table_args__ = (
        CheckConstraint("status IN ('open','closed')", name="ck_billing_periods_status"),
        {"comment": "Период биллинга: счёт+клиент+инстанс во времени (роллап #23-доп). Закрытый "
         "immutable (триггер). hwm/cum_profit/commission — ADR-0011; fee_pct — снапшот."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchange_accounts.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    contract_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("contracts.id", ondelete="RESTRICT"), nullable=False
    )
    # instance_id — активный бот в периоде (per-instance роллап #23-доп); UUID без FK (бот сносится)
    instance_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    start_equity: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    end_equity: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_deposits: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, server_default="0"
    )
    period_net_trading: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    cum_profit: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    hwm: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, server_default="0")
    fee_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)  # снапшот
    commission: Mapped[Decimal | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, server_default="USDT")
    status: Mapped[str] = mapped_column(String(8), nullable=False, server_default="open")
    adjustments_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Cashflow(Base):
    __tablename__ = "cashflows"
    __table_args__ = (
        CheckConstraint("kind IN ('deposit','withdrawal')", name="ck_cashflows_kind"),
        CheckConstraint("amount > 0", name="ck_cashflows_amount_positive"),
        {"comment": "Пополнения/выводы клиента (ADR-0011 MON1). НЕ прибыль/убыток — исключаются "
         "из торгового Δ, сдвигают планку HWM на сумму (абсолютно, #24)."},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exchange_accounts.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)  # deposit|withdrawal (+CHECK)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # >0 (+CHECK)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)  # кто записал (аудит)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
